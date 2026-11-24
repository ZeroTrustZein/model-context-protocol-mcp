import httpx
import pytest

from mls_mcp.cache import TTLCache, fetch_json
from mls_mcp.config import Settings


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_cache_returns_value_within_ttl_and_expires_after() -> None:
    clock = Clock()
    cache = TTLCache(ttl_seconds=10, clock=clock)
    cache.set("k", {"v": 1})
    assert cache.get("k") == {"v": 1}

    clock.now = 11
    assert cache.get("k") is None
    assert len(cache) == 0


def test_cache_disabled_when_ttl_is_zero() -> None:
    cache = TTLCache(ttl_seconds=0)
    cache.set("k", 1)
    assert cache.get("k") is None


async def test_fetch_json_memoises_by_params() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"value": len(seen)})

    cache = TTLCache(ttl_seconds=60)
    async with httpx.AsyncClient(
        base_url="https://upstream.test", transport=httpx.MockTransport(handler)
    ) as client:
        first = await fetch_json(client, cache, "/odata", params={"$top": 1})
        second = await fetch_json(client, cache, "/odata", params={"$top": 1})
        third = await fetch_json(client, cache, "/odata", params={"$top": 2})

    assert first == second == {"value": 1}
    assert third == {"value": 2}
    assert len(seen) == 2


async def test_client_caches_repeated_upstream_calls() -> None:
    from mls_mcp.census import CensusClient

    rows = [
        ["NAME", "B01003_001E", "B11001_001E", "B19013_001E", "B01002_001E", "B25077_001E"],
        ["ZCTA5 78704", "42000", "19000", "82000", "33.1", "540000"],
    ]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=rows)

    settings = Settings(_env_file=None, census_api_base="https://census.test")
    async with CensusClient(settings, transport=httpx.MockTransport(handler)) as client:
        await client.demographics("zip code:78704")
        await client.demographics("zip code:78704")

    assert len(calls) == 1


async def test_client_cache_can_be_disabled() -> None:
    from mls_mcp.census import CensusClient

    rows = [["NAME", "B01003_001E"], ["ZCTA5 78704", "42000"]]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=rows)

    settings = Settings(_env_file=None, census_api_base="https://census.test", cache_ttl_seconds=0)
    async with CensusClient(
        settings, transport=httpx.MockTransport(handler), cache=TTLCache(0)
    ) as client:
        await client.demographics("zip code:78704")
        await client.demographics("zip code:78704")

    assert len(calls) == 2


def test_cache_clear() -> None:
    cache = TTLCache(ttl_seconds=60)
    cache.set("k", 1)
    cache.clear()
    assert len(cache) == 0
    assert cache.get("k") is None


async def test_fetch_json_raises_and_does_not_cache_errors() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500, json={"error": "boom"})

    cache = TTLCache(ttl_seconds=60)
    async with httpx.AsyncClient(
        base_url="https://upstream.test", transport=httpx.MockTransport(handler)
    ) as client:
        for _ in range(2):
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_json(client, cache, "/odata")

    assert len(calls) == 2
