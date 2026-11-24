import pytest

from mls_mcp.models import PropertyFilter, PropertyListing, SemanticSearchQuery
from mls_mcp.search import search_listings, tokenize


def _listing(listing_id: str, description: str, **overrides: object) -> PropertyListing:
    payload: dict[str, object] = {
        "listing_id": listing_id,
        "list_price": 450000,
        "living_area_sqft": 1800,
        "description": description,
        "address": {"city": "Austin", "state": "TX", "postal_code": "78704"},
    }
    payload.update(overrides)
    return PropertyListing.model_validate(payload)


CORPUS = [
    _listing("A", "Quiet street near a park with mature trees"),
    _listing("B", "Downtown condo steps from transit"),
    _listing("C", "Family home near a park with a big yard", features=["Fireplace"]),
    _listing("D", "Waterfront estate", list_price=5_000_000),
]


def test_tokenize_normalises() -> None:
    assert tokenize("Multi_Family, Near-A-Park!") == ["multi", "family", "near", "a", "park"]


def test_ranking_prefers_more_query_terms() -> None:
    results = search_listings(CORPUS, SemanticSearchQuery(query="park near"))
    assert [match.listing.listing_id for match in results.matches] == ["A", "C"]
    assert results.matches[0].score == pytest.approx(1.0)
    assert set(results.matches[0].highlights) == {"park", "near"}
    assert results.total_considered == len(CORPUS)


def test_filters_limit_candidates() -> None:
    query = SemanticSearchQuery(query="park", filters=PropertyFilter(max_price=500000))
    results = search_listings(CORPUS, query)
    assert [match.listing.listing_id for match in results.matches] == ["A", "C"]
    assert results.total_considered == 3


def test_top_k_and_min_score() -> None:
    query = SemanticSearchQuery(query="park near yard", top_k=1)
    assert len(search_listings(CORPUS, query).matches) == 1
    strict = SemanticSearchQuery(query="park near yard", min_score=0.99)
    assert [match.listing.listing_id for match in search_listings(CORPUS, strict).matches] == ["C"]


def test_unmatched_query_returns_nothing() -> None:
    results = search_listings(CORPUS, SemanticSearchQuery(query="zeppelin hangar"))
    assert results.matches == []
    assert results.total_considered == len(CORPUS)


def test_empty_query_terms_return_nothing() -> None:
    results = search_listings(CORPUS, SemanticSearchQuery(query="!!! ???"))
    assert results.matches == []
    assert results.total_considered == len(CORPUS)


def test_empty_candidate_pool() -> None:
    results = search_listings([], SemanticSearchQuery(query="park"))
    assert results.matches == []
    assert results.total_considered == 0


def test_filters_can_exclude_everything() -> None:
    query = SemanticSearchQuery(query="park", filters=PropertyFilter(min_price=10_000_000))
    results = search_listings(CORPUS, query)
    assert results.matches == []
    assert results.total_considered == 0
