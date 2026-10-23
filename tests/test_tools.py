"""Tool-level tests: registration plus the stub-backed search/demographics tools."""

import httpx
import pytest
from mcp.server.mcpserver import MCPServer

from mls_mcp import server
from mls_mcp.census import CensusClient
from mls_mcp.config import Settings
from mls_mcp.mls import MLSClient

RESO_RECORDS = [
    {
        "ListingId": "MLS-1",
        "ListPrice": 450000,
        "BedroomsTotal": 3,
        "LivingArea": 1800,
        "City": "Austin",
        "StateOrProvince": "TX",
        "PublicRemarks": "Quiet street near a park with a fireplace",
    },
    {
        "ListingId": "MLS-2",
        "ListPrice": 300000,
        "BedroomsTotal": 2,
        "LivingArea": 1200,
        "City": "Austin",
        "StateOrProvince": "TX",
        "PublicRemarks": "Downtown loft",
    },
]

ACS_ROWS = [
    ["NAME", "B01003_001E", "B11001_001E", "B19013_001E", "B01002_001E", "B25077_001E"],
    ["ZCTA5 78704", "12000", "5800", "72000", "34.5", "560000"],
]


def _settings() -> Settings:
    return Settings(_env_file=None, mls_api_token="token")


def _stub_mls(monkeypatch: pytest.MonkeyPatch, records: list[dict[str, object]]) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"value": records}))
    monkeypatch.setattr(
        server,
        "MLSClient",
        lambda: MLSClient(_settings(), transport=transport),
    )


def _stub_census(monkeypatch: pytest.MonkeyPatch, rows: list[list[str]]) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=rows))
    monkeypatch.setattr(
        server,
        "CensusClient",
        lambda: CensusClient(_settings(), transport=transport),
    )


async def test_tools_are_registered() -> None:
    names = {tool.name for tool in await server.mcp.list_tools()}
    assert {"server_info", "search_listings", "get_demographics"} <= names


async def test_search_listings_ranks_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_mls(monkeypatch, RESO_RECORDS)
    result = await server.search_listings("park fireplace", top_k=2)
    assert result["query"] == "park fireplace"
    assert result["total_considered"] == 2
    matches = result["matches"]
    assert [match["listing"]["listing_id"] for match in matches] == ["MLS-1"]
    assert matches[0]["score"] > 0


async def test_search_listings_passes_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    transport = httpx.MockTransport(
        lambda request: (
            seen.append(request.url.params.get("$filter", "")),
            httpx.Response(200, json={"value": []}),
        )[1]
    )
    monkeypatch.setattr(server, "MLSClient", lambda: MLSClient(_settings(), transport=transport))
    result = await server.search_listings("loft", city="Austin", max_price=500000)
    assert result["matches"] == []
    assert seen and "City eq 'Austin'" in seen[0] and "ListPrice le 500000.0" in seen[0]


async def test_get_demographics(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_census(monkeypatch, ACS_ROWS)
    result = await server.get_demographics("zip code:78704")
    assert result["geography"] == "zip code:78704"
    assert result["population"] == 12000
    assert result["median_household_income"] == 72000


async def test_call_tool_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_census(monkeypatch, ACS_ROWS)
    contents = await server.mcp.call_tool("get_demographics", {"geography": "zip code:78704"})
    assert "78704" in str(contents)


def test_rank_alias_matches_search_module() -> None:
    from mls_mcp.search import search_listings

    assert server.rank_listings is search_listings


def test_server_instance() -> None:
    assert isinstance(server.mcp, MCPServer)
    assert server.mcp.name == server.SERVER_NAME
