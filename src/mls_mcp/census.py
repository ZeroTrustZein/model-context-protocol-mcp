"""US Census ACS client: one demographic snapshot per geography."""

from __future__ import annotations

import httpx

from mls_mcp.config import Settings, get_settings
from mls_mcp.models import Demographics

DEFAULT_YEAR = 2023
DEFAULT_DATASET = "acs/acs5"

# ACS variable -> Demographics field.
VARIABLES: dict[str, str] = {
    "NAME": "name",
    "B01003_001E": "population",
    "B11001_001E": "households",
    "B19013_001E": "median_household_income",
    "B01002_001E": "median_age",
    "B25077_001E": "median_home_value",
}


def _number(value: object, integer: bool = False) -> float | int | None:
    """ACS reports missing data as a negative sentinel or null."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return int(number) if integer else number


class CensusClient:
    """Async ACS client. Pass ``transport`` to stub HTTP in tests."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        year: int = DEFAULT_YEAR,
    ) -> None:
        self._settings = settings or get_settings()
        self._year = year
        self._client = httpx.AsyncClient(
            base_url=self._settings.census_api_base.rstrip("/"),
            timeout=self._settings.http_timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> CensusClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def demographics(
        self,
        for_clause: str,
        *,
        in_clause: str | None = None,
        year: int | None = None,
    ) -> Demographics:
        """Fetch one snapshot. ``for_clause`` e.g. ``"zip code:78704"``."""
        params: dict[str, str] = {
            "get": ",".join(VARIABLES),
            "for": for_clause,
        }
        if in_clause:
            params["in"] = in_clause
        if self._settings.census_api_key:
            params["key"] = self._settings.census_api_key

        resolved_year = year or self._year
        response = await self._client.get(f"/{resolved_year}/{DEFAULT_DATASET}", params=params)
        response.raise_for_status()
        rows = response.json()
        if len(rows) < 2:
            raise LookupError(f"no ACS data for {for_clause}")

        header, row = rows[0], rows[1]
        values = dict(zip(header, row, strict=False))
        fields = {name: values.get(variable) for variable, name in VARIABLES.items()}
        return Demographics(
            geography=for_clause,
            name=str(fields["name"] or for_clause),
            as_of_year=resolved_year,
            population=_number(fields["population"], integer=True),
            households=_number(fields["households"], integer=True),
            median_household_income=_number(fields["median_household_income"]),
            median_age=_number(fields["median_age"]),
            median_home_value=_number(fields["median_home_value"]),
        )


__all__ = ["CensusClient", "DEFAULT_DATASET", "DEFAULT_YEAR", "VARIABLES"]
