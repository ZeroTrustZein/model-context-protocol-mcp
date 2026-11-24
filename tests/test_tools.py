"""Tool-level tests: registration plus the stub-backed search/demographics tools."""

import logging

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


def test_server_info_flags_follow_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            mls_api_key="k",
            census_api_key="k",
            vector_store_url="https://vector.test",
        ),
    )
    info = server.server_info()
    assert info["mls_configured"] is True
    assert info["census_configured"] is True
    assert info["vector_store_configured"] is True

    monkeypatch.setattr(server, "get_settings", lambda: Settings(_env_file=None))
    info = server.server_info()
    assert info["mls_configured"] is False
    assert info["census_configured"] is False
    assert info["vector_store_configured"] is False


class _RecordingMLS:
    def __init__(self) -> None:
        self.limits: list[int] = []

    async def __aenter__(self) -> "_RecordingMLS":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def search(self, filters: object, *, limit: int) -> list[object]:
        self.limits.append(limit)
        return []


@pytest.mark.parametrize(("top_k", "pool"), [(3, 50), (20, 100)])
async def test_search_listings_widens_candidate_pool(
    monkeypatch: pytest.MonkeyPatch, top_k: int, pool: int
) -> None:
    client = _RecordingMLS()
    monkeypatch.setattr(server, "MLSClient", lambda: client)
    await server.search_listings("park", top_k=top_k)
    assert client.limits == [pool]


async def test_get_demographics_forwards_optional_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ACS_ROWS)

    monkeypatch.setattr(
        server,
        "CensusClient",
        lambda: CensusClient(_settings(), transport=httpx.MockTransport(handler)),
    )
    result = await server.get_demographics("county:453", in_geography="state:48", year=2022)
    assert result["as_of_year"] == 2022
    assert seen[0].url.path.endswith("/2022/acs/acs5")
    assert seen[0].url.params["in"] == "state:48"


def test_configure_logging_uses_settings_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server, "get_settings", lambda: Settings(_env_file=None, log_level="warning")
    )
    server.configure_logging()
    assert logging.getLogger().level == logging.WARNING


def test_main_runs_stdio_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(server, "configure_logging", lambda: calls.append("log"))
    monkeypatch.setattr(server.mcp, "run", lambda: calls.append("run"))
    server.main()
    assert calls == ["log", "run"]
