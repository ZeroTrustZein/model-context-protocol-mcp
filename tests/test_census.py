import httpx
import pytest

from mls_mcp.census import CensusClient
from mls_mcp.config import Settings


def _handler(rows: list[list[object]]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    return handler


async def test_demographics_maps_acs_columns() -> None:
    rows = [
        ["NAME", "B01003_001E", "B11001_001E", "B19013_001E", "B01002_001E", "B25077_001E"],
        ["ZCTA5 78704", "42000", "19000", "82000", "33.1", "540000"],
    ]
    settings = Settings(_env_file=None, census_api_key="key", census_api_base="https://census.test")
    async with CensusClient(settings, transport=httpx.MockTransport(_handler(rows))) as client:
        snapshot = await client.demographics("zip code:78704")

    assert snapshot.geography == "zip code:78704"
    assert snapshot.name == "ZCTA5 78704"
    assert snapshot.as_of_year == 2023
    assert snapshot.population == 42000
    assert isinstance(snapshot.population, int)
    assert snapshot.median_household_income == pytest.approx(82000)
    assert snapshot.median_home_value == pytest.approx(540000)


async def test_demographics_nulls_missing_sentinels() -> None:
    rows = [
        ["NAME", "B01003_001E", "B11001_001E", "B19013_001E", "B01002_001E", "B25077_001E"],
        ["ZCTA5 00000", "100", "-666666666", None, "0", "-666666666"],
    ]
    async with CensusClient(
        Settings(_env_file=None), transport=httpx.MockTransport(_handler(rows))
    ) as client:
        snapshot = await client.demographics("zip code:00000", year=2022)

    assert snapshot.households is None
    assert snapshot.median_household_income is None
    assert snapshot.median_home_value is None
    assert snapshot.population == 100
    assert snapshot.as_of_year == 2022


async def test_demographics_raises_without_rows() -> None:
    async with CensusClient(
        Settings(_env_file=None), transport=httpx.MockTransport(_handler(["NAME"]))
    ) as client:
        with pytest.raises(LookupError):
            await client.demographics("zip code:99999")
