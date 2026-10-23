import httpx
import pytest

from mls_mcp.config import Settings
from mls_mcp.mls import MLSClient, build_filter, odata_string, parse_listing
from mls_mcp.models import ListingStatus, PropertyFilter, PropertyType

RESO_RECORD = {
    "ListingId": "MLS-1",
    "ListPrice": 450000,
    "BedroomsTotal": 3,
    "BathroomsTotalDecimal": 2.5,
    "LivingArea": 1800,
    "LotSizeSquareFeet": 6000,
    "YearBuilt": 1998,
    "StandardStatus": "Active",
    "PropertyType": "Residential",
    "StreetAddress": "1 Main St",
    "City": "Austin",
    "StateOrProvince": "TX",
    "PostalCode": "78704",
    "CountyOrParish": "Travis",
    "Latitude": 30.25,
    "Longitude": -97.75,
    "PublicRemarks": "Quiet street near a park",
    "InteriorFeatures": "Hardwood Floors, Fireplace",
    "ListingContractDate": "2026-01-15",
}


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, mls_api_token="token", **overrides)


def test_build_filter_empty() -> None:
    assert build_filter(PropertyFilter()) == ""


def test_build_filter_escapes_quotes() -> None:
    assert odata_string("O'Brien") == "'O''Brien'"
    assert build_filter(PropertyFilter(city="O'Brien")) == "City eq 'O''Brien'"


def test_build_filter_ranges_and_enums() -> None:
    expression = build_filter(
        PropertyFilter(
            state="TX",
            statuses=[ListingStatus.ACTIVE, ListingStatus.SOLD],
            property_types=[PropertyType.CONDO, PropertyType.LAND],
            min_price=100,
            max_price=500,
            min_bedrooms=2,
            min_sqft=900,
            min_year_built=1950,
        )
    )
    assert "StateOrProvince eq 'TX'" in expression
    assert "(StandardStatus eq 'Active' or StandardStatus eq 'Closed')" in expression
    assert "PropertyType eq 'Residential' and PropertySubType eq 'Condominium'" in expression
    assert "PropertyType eq 'Land'" in expression
    assert "ListPrice ge 100" in expression
    assert "ListPrice le 500" in expression
    assert "BedroomsTotal ge 2" in expression
    assert "LivingArea ge 900" in expression
    assert "YearBuilt ge 1950" in expression


def test_parse_listing_maps_reso_fields() -> None:
    listing = parse_listing(RESO_RECORD)
    assert listing is not None
    assert listing.mls_number == "MLS-1"
    assert listing.address.city == "Austin"
    assert listing.address.county == "Travis"
    assert listing.location is not None and listing.location.latitude == 30.25
    assert listing.features == ["Hardwood Floors", "Fireplace"]
    assert listing.price_per_sqft == pytest.approx(250.0)


def test_parse_listing_skips_unusable_records() -> None:
    assert parse_listing({"ListPrice": 100}) is None
    assert parse_listing({"ListingId": "MLS-2"}) is None
    assert parse_listing({**RESO_RECORD, "ListPrice": -5}) is None


async def test_search_requests_odata_and_parses() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"value": [RESO_RECORD]})

    async with MLSClient(_settings(), transport=httpx.MockTransport(handler)) as client:
        listings = await client.search(PropertyFilter(city="Austin"), limit=10)

    assert [listing.listing_id for listing in listings] == ["MLS-1"]
    request = seen[0]
    assert request.headers["Authorization"] == "Bearer token"
    assert request.url.params["$filter"] == "City eq 'Austin'"
    assert request.url.params["$top"] == "10"


async def test_search_stops_on_short_page() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(int(request.url.params["$skip"]))
        return httpx.Response(200, json={"value": [RESO_RECORD] * 1})

    async with MLSClient(_settings(), transport=httpx.MockTransport(handler)) as client:
        listings = await client.search(limit=10, page_size=2)

    assert len(listings) == 1
    assert calls == [0]


async def test_search_requires_credentials() -> None:
    client = MLSClient(Settings(_env_file=None), transport=httpx.MockTransport(lambda _: None))
    with pytest.raises(RuntimeError):
        await client.search()
    await client.aclose()


async def test_client_credentials_flow() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "fresh"})
        return httpx.Response(200, json={"value": []})

    settings = Settings(
        _env_file=None,
        mls_api_base="https://mls.example/odata",
        mls_api_key="key",
        mls_api_secret="secret",
        mls_token_url="https://mls.example/token",
    )
    async with MLSClient(settings, transport=httpx.MockTransport(handler)) as client:
        assert await client.search() == []
        assert await client.search() == []

    token_calls = [request for request in seen if request.url.path.endswith("/token")]
    listing_calls = [request for request in seen if request.url.path == "/odata"]
    assert len(token_calls) == 1
    assert all(request.headers["Authorization"] == "Bearer fresh" for request in listing_calls)
