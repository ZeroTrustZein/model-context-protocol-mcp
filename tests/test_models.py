from datetime import date

import pytest
from pydantic import ValidationError

from mls_mcp.models import (
    Address,
    Demographics,
    GeoPoint,
    ListingStatus,
    PropertyFilter,
    PropertyListing,
    PropertyMatch,
    PropertyType,
    SearchResults,
    SemanticSearchQuery,
)


def _listing(**overrides: object) -> PropertyListing:
    payload: dict[str, object] = {
        "listing_id": "MLS-1",
        "list_price": 450000,
        "bedrooms": 3,
        "bathrooms": 2.5,
        "living_area_sqft": 1800,
        "year_built": 1998,
        "address": {"city": "Austin", "state": "TX", "postal_code": "78704"},
        "listed_at": "2026-01-15",
    }
    payload.update(overrides)
    return PropertyListing.model_validate(payload)


def test_listing_defaults_and_enums() -> None:
    listing = _listing()
    assert listing.status is ListingStatus.ACTIVE
    assert listing.property_type is PropertyType.RESIDENTIAL
    assert listing.listed_at == date(2026, 1, 15)
    assert listing.features == []


def test_listing_ignores_unknown_upstream_fields() -> None:
    listing = _listing(StandardStatus="Active", SomeProviderJunk=123)
    assert listing.listing_id == "MLS-1"


def test_listing_rejects_negative_price() -> None:
    with pytest.raises(ValidationError):
        _listing(list_price=-1)


def test_price_per_sqft_none_without_area() -> None:
    assert _listing().price_per_sqft == pytest.approx(250.0)
    assert _listing(living_area_sqft=0).price_per_sqft is None


def test_geo_point_bounds() -> None:
    assert GeoPoint(latitude=30.25, longitude=-97.75).latitude == 30.25
    with pytest.raises(ValidationError):
        GeoPoint(latitude=91, longitude=0)


def test_filter_matches_city_case_insensitively() -> None:
    listing = _listing()
    assert PropertyFilter(city="austin").matches(listing)
    assert not PropertyFilter(city="Dallas").matches(listing)


def test_filter_price_and_size_bounds() -> None:
    listing = _listing()
    assert PropertyFilter(min_price=400000, max_price=500000).matches(listing)
    assert not PropertyFilter(max_price=400000).matches(listing)
    assert not PropertyFilter(min_sqft=2000).matches(listing)


def test_filter_year_built_requires_known_year() -> None:
    unknown = _listing(year_built=None)
    assert not PropertyFilter(min_year_built=1950).matches(unknown)
    assert PropertyFilter().matches(unknown)


def test_filter_rejects_inverted_range() -> None:
    with pytest.raises(ValidationError):
        PropertyFilter(min_price=500, max_price=100)


def test_semantic_query_defaults() -> None:
    query = SemanticSearchQuery(query="  quiet street near a park  ")
    assert query.query == "quiet street near a park"
    assert query.top_k == 10
    assert query.filters is None


def test_search_results_round_trip() -> None:
    results = SearchResults(
        query="family home",
        matches=[PropertyMatch(listing=_listing(), score=0.87, highlights=["3 bed"])],
        total_considered=42,
    )
    restored = SearchResults.model_validate_json(results.model_dump_json())
    assert restored.matches[0].score == pytest.approx(0.87)
    assert restored.matches[0].listing.address.city == "Austin"


def test_demographics_requires_year() -> None:
    with pytest.raises(ValidationError):
        Demographics(geography="78704")
    snapshot = Demographics(geography="78704", as_of_year=2024, median_household_income=82000)
    assert snapshot.source == "census_acs"


def test_address_defaults() -> None:
    assert Address().street == ""
