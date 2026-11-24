"""Ranking for natural-language property search.

Scoring is lexical (idf-weighted query-term coverage) so natural-language search
works without an embedding backend; a vector store can supply ``score``/``highlights``
through the same :class:`SearchResults` shape later.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from mls_mcp.models import (
    PropertyFilter,
    PropertyListing,
    PropertyMatch,
    SearchResults,
    SemanticSearchQuery,
)

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens; underscores in enum values become separators."""
    return _TOKEN.findall(text.casefold().replace("_", " "))


def _document(listing: PropertyListing) -> str:
    return " ".join(
        (
            listing.description or "",
            " ".join(listing.features),
            listing.address.street,
            listing.address.city,
            listing.address.state,
            listing.property_type.value,
        )
    )


def search_listings(
    listings: list[PropertyListing],
    query: SemanticSearchQuery,
) -> SearchResults:
    """Filter, score and rank ``listings`` against a natural-language query."""
    filters: PropertyFilter | None = query.filters
    candidates = [listing for listing in listings if filters is None or filters.matches(listing)]
    terms = set(tokenize(query.query))
    if not terms or not candidates:
        return SearchResults(query=query.query, matches=[], total_considered=len(candidates))

    documents = [Counter(tokenize(_document(listing))) for listing in candidates]
    document_frequency = Counter(term for document in documents for term in document)
    weights = {
        term: math.log(1 + len(documents) / document_frequency[term])
        for term in terms
        if term in document_frequency
    }
    if not weights:
        return SearchResults(query=query.query, matches=[], total_considered=len(candidates))
    total_weight = sum(weights.values())

    matches: list[PropertyMatch] = []
    for listing, document in zip(candidates, documents, strict=True):
        hits = {term: weight for term, weight in weights.items() if term in document}
        score = sum(hits.values()) / total_weight
        if score > 0 and score >= query.min_score:
            matches.append(
                PropertyMatch(listing=listing, score=score, highlights=sorted(hits))
            )
    matches.sort(key=lambda match: match.score, reverse=True)
    return SearchResults(
        query=query.query,
        matches=matches[: query.top_k],
        total_considered=len(candidates),
    )


__all__ = ["search_listings", "tokenize"]
