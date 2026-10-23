"""RESO Web API (OData) listing client.

Maps the internal :class:`PropertyFilter` onto an OData ``$filter`` expression
and the noisy upstream payload back onto :class:`PropertyListing`.

Auth order: static ``MLS_API_TOKEN`` bearer, else OAuth2 client-credentials
against ``MLS_TOKEN_URL`` using the API key/secret pair.
"""

from __future__ import annotations

import httpx

from mls_mcp.cache import TTLCache, fetch_json
from mls_mcp.config import Settings, get_settings
from mls_mcp.models import (
    Address,
    GeoPoint,
    ListingStatus,
    PropertyFilter,
    PropertyListing,
    PropertyType,
)

STATUS_LABELS: dict[ListingStatus, str] = {
    ListingStatus.ACTIVE: "Active",
    ListingStatus.PENDING: "Pending",
    ListingStatus.SOLD: "Closed",
    ListingStatus.WITHDRAWN: "Withdrawn",
    ListingStatus.EXPIRED: "Expired",
}

# RESO PropertyType plus the PropertySubType that carries our finer distinctions.
TYPE_LABELS: dict[PropertyType, tuple[str, str | None]] = {
    PropertyType.RESIDENTIAL: ("Residential", None),
    PropertyType.CONDO: ("Residential", "Condominium"),
    PropertyType.TOWNHOUSE: ("Residential", "Townhouse"),
    PropertyType.MULTI_FAMILY: ("Residential", "Multi Family"),
    PropertyType.LAND: ("Land", None),
    PropertyType.COMMERCIAL: ("Commercial", None),
}


def odata_string(value: str) -> str:
    """Quote a literal for OData (single quotes doubled)."""
    return "'" + value.replace("'", "''") + "'"


def build_filter(filters: PropertyFilter) -> str:
    """OData ``$filter`` body for a filter, or ``""`` when unconstrained."""
    clauses: list[str] = []

    if filters.city:
        clauses.append(f"City eq {odata_string(filters.city)}")
    if filters.state:
        clauses.append(f"StateOrProvince eq {odata_string(filters.state)}")
    if filters.postal_code:
        clauses.append(f"PostalCode eq {odata_string(filters.postal_code)}")
    if filters.statuses:
        options = " or ".join(
            f"StandardStatus eq {odata_string(STATUS_LABELS[status])}"
            for status in filters.statuses
        )
        clauses.append(f"({options})")
    if filters.property_types:
        options = " or ".join(
            f"(PropertyType eq {odata_string(label)} and PropertySubType eq {odata_string(sub)})"
            if sub
            else f"PropertyType eq {odata_string(label)}"
            for label, sub in (
                TYPE_LABELS[property_type] for property_type in filters.property_types
            )
        )
        clauses.append(f"({options})")

    for field, value, operator in (
        ("ListPrice", filters.min_price, "ge"),
        ("ListPrice", filters.max_price, "le"),
        ("BedroomsTotal", filters.min_bedrooms, "ge"),
        ("BathroomsTotalDecimal", filters.min_bathrooms, "ge"),
        ("LivingArea", filters.min_sqft, "ge"),
        ("LivingArea", filters.max_sqft, "le"),
        ("YearBuilt", filters.min_year_built, "ge"),
    ):
        if value is not None:
            clauses.append(f"{field} {operator} {value}")

    return " and ".join(clauses)


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _enum_by_value(enum_type, raw: object, default):
    if not isinstance(raw, str):
        return default
    normalised = raw.strip().casefold().replace(" ", "_")
    for member in enum_type:
        if member.value == normalised:
            return member
    if enum_type is ListingStatus and normalised == "closed":
        return ListingStatus.SOLD
    return default


def parse_listing(raw: dict[str, object]) -> PropertyListing | None:
    """Map one RESO record to a listing; ``None`` when the record has no id."""
    listing_id = raw.get("ListingId") or raw.get("ListingKey") or raw.get("MLSNumber")
    price = _as_float(raw.get("ListPrice"))
    if not listing_id or price is None:
        return None

    latitude = _as_float(raw.get("Latitude"))
    longitude = _as_float(raw.get("Longitude"))
    features = _as_list(raw.get("InteriorFeatures")) + _as_list(raw.get("ExteriorFeatures"))

    try:
        return PropertyListing(
            listing_id=str(listing_id).strip(),
            mls_number=str(raw["ListingId"]).strip() if raw.get("ListingId") else None,
            status=_enum_by_value(ListingStatus, raw.get("StandardStatus"), ListingStatus.ACTIVE),
            property_type=_enum_by_value(
                PropertyType, raw.get("PropertyType"), PropertyType.RESIDENTIAL
            ),
            list_price=price,
            bedrooms=int(_as_float(raw.get("BedroomsTotal")) or 0),
            bathrooms=_as_float(raw.get("BathroomsTotalDecimal")) or 0.0,
            living_area_sqft=_as_float(raw.get("LivingArea")) or 0.0,
            lot_size_sqft=_as_float(raw.get("LotSizeSquareFeet")),
            year_built=int(year) if (year := _as_float(raw.get("YearBuilt"))) else None,
            address=Address(
                street=str(raw.get("StreetAddress") or ""),
                city=str(raw.get("City") or ""),
                state=str(raw.get("StateOrProvince") or ""),
                postal_code=str(raw.get("PostalCode") or ""),
                county=str(raw["CountyOrParish"]) if raw.get("CountyOrParish") else None,
            ),
            location=(
                GeoPoint(latitude=latitude, longitude=longitude)
                if latitude is not None and longitude is not None
                else None
            ),
            listed_at=raw.get("ListingContractDate") or None,
            updated_at=raw.get("ModificationTimestamp") or None,
            description=str(raw["PublicRemarks"]) if raw.get("PublicRemarks") else None,
            features=features,
        )
    except ValueError:
        return None


class MLSClient:
    """Async RESO client. Pass ``transport`` to stub HTTP in tests."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        cache: TTLCache | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = httpx.AsyncClient(
            base_url=self._settings.mls_api_base.rstrip("/"),
            timeout=self._settings.http_timeout_seconds,
            transport=transport,
        )
        self._cache = cache or TTLCache(self._settings.cache_ttl_seconds)
        self._token = ""

    async def __aenter__(self) -> MLSClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            settings = self._settings
            if settings.mls_api_token:
                self._token = settings.mls_api_token
            elif settings.mls_api_key and settings.mls_api_secret and settings.mls_token_url:
                response = await self._client.post(
                    settings.mls_token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": settings.mls_api_key,
                        "client_secret": settings.mls_api_secret,
                    },
                )
                response.raise_for_status()
                self._token = str(response.json()["access_token"])
            else:
                raise RuntimeError(
                    "MLS credentials missing: set MLS_API_TOKEN, or MLS_API_KEY + "
                    "MLS_API_SECRET + MLS_TOKEN_URL"
                )
        return {"Authorization": f"Bearer {self._token}"}

    async def _page(self, params: dict[str, object]) -> list[PropertyListing]:
        payload = await fetch_json(
            self._client,
            self._cache,
            "",
            params=params,
            headers=await self._auth_headers(),
        )
        records = payload.get("value") or []
        return [listing for raw in records if (listing := parse_listing(raw)) is not None]

    async def search(
        self,
        filters: PropertyFilter | None = None,
        *,
        limit: int = 50,
        page_size: int = 100,
    ) -> list[PropertyListing]:
        """Fetch up to ``limit`` listings matching ``filters``, newest first."""
        if limit < 1:
            return []
        expression = build_filter(filters) if filters is not None else ""
        listings: list[PropertyListing] = []
        skip = 0
        while len(listings) < limit:
            take = min(page_size, limit - len(listings))
            params: dict[str, object] = {
                "$top": take,
                "$skip": skip,
                "$orderby": "ModificationTimestamp desc",
            }
            if expression:
                params["$filter"] = expression
            page = await self._page(params)
            listings.extend(page)
            skip += take
            if len(page) < take:
                break
        return listings[:limit]


__all__ = [
    "MLSClient",
    "STATUS_LABELS",
    "TYPE_LABELS",
    "build_filter",
    "odata_string",
    "parse_listing",
]
