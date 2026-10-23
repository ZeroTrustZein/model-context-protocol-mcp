"""Domain types shared by the MLS, Census and semantic-search layers.

Only data shapes live here: no I/O, no transport concerns. Upstream feeds are
noisy, so every model ignores unknown keys instead of failing on them.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DomainModel(BaseModel):
    """Base for all domain types."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, str_strip_whitespace=True)


class PropertyType(str, Enum):
    RESIDENTIAL = "residential"
    CONDO = "condo"
    TOWNHOUSE = "townhouse"
    MULTI_FAMILY = "multi_family"
    LAND = "land"
    COMMERCIAL = "commercial"


class ListingStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    SOLD = "sold"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


class GeoPoint(DomainModel):
    """WGS-84 coordinate pair."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class Address(DomainModel):
    street: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    county: str | None = None


class PropertyListing(DomainModel):
    """One listing as served by the MLS feed."""

    listing_id: str = Field(min_length=1)
    mls_number: str | None = None
    status: ListingStatus = ListingStatus.ACTIVE
    property_type: PropertyType = PropertyType.RESIDENTIAL
    list_price: float = Field(ge=0)
    bedrooms: int = Field(default=0, ge=0)
    bathrooms: float = Field(default=0, ge=0)
    living_area_sqft: float = Field(default=0, ge=0)
    lot_size_sqft: float | None = Field(default=None, ge=0)
    year_built: int | None = Field(default=None, ge=1600, le=2200)
    address: Address = Field(default_factory=Address)
    location: GeoPoint | None = None
    listed_at: date | None = None
    updated_at: datetime | None = None
    description: str | None = None
    features: list[str] = Field(default_factory=list)

    @property
    def price_per_sqft(self) -> float | None:
        if self.living_area_sqft <= 0:
            return None
        return self.list_price / self.living_area_sqft


class Demographics(DomainModel):
    """Census ACS snapshot for one geography."""

    geography: str = Field(min_length=1, description="Zip, tract, county or place identifier")
    name: str = ""
    as_of_year: int = Field(ge=2000, le=2200)
    population: int | None = Field(default=None, ge=0)
    households: int | None = Field(default=None, ge=0)
    median_household_income: float | None = Field(default=None, ge=0)
    median_age: float | None = Field(default=None, ge=0)
    median_home_value: float | None = Field(default=None, ge=0)
    unemployment_rate: float | None = Field(default=None, ge=0, le=100)
    poverty_rate: float | None = Field(default=None, ge=0, le=100)
    source: str = "census_acs"


class PropertyFilter(DomainModel):
    """Schema filter shared by OData listing queries and semantic search."""

    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    statuses: list[ListingStatus] = Field(default_factory=list)
    property_types: list[PropertyType] = Field(default_factory=list)
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    min_bedrooms: int | None = Field(default=None, ge=0)
    min_bathrooms: float | None = Field(default=None, ge=0)
    min_sqft: float | None = Field(default=None, ge=0)
    max_sqft: float | None = Field(default=None, ge=0)
    min_year_built: int | None = Field(default=None, ge=1600)

    @model_validator(mode="after")
    def _ranges_are_ordered(self) -> PropertyFilter:
        for low, high in (
            (self.min_price, self.max_price),
            (self.min_sqft, self.max_sqft),
        ):
            if low is not None and high is not None and low > high:
                raise ValueError(f"lower bound {low} exceeds upper bound {high}")
        return self

    def matches(self, listing: PropertyListing) -> bool:
        """True when the listing satisfies every set constraint."""
        if self.city and listing.address.city.casefold() != self.city.casefold():
            return False
        if self.state and listing.address.state.casefold() != self.state.casefold():
            return False
        if self.postal_code and listing.address.postal_code != self.postal_code:
            return False
        if self.statuses and listing.status not in self.statuses:
            return False
        if self.property_types and listing.property_type not in self.property_types:
            return False
        checks = (
            (self.min_price, listing.list_price, False),
            (self.max_price, listing.list_price, True),
            (self.min_bedrooms, listing.bedrooms, False),
            (self.min_bathrooms, listing.bathrooms, False),
            (self.min_sqft, listing.living_area_sqft, False),
            (self.max_sqft, listing.living_area_sqft, True),
        )
        for bound, value, upper in checks:
            if bound is None:
                continue
            if upper and value > bound:
                return False
            if not upper and value < bound:
                return False
        if self.min_year_built is not None:
            if listing.year_built is None or listing.year_built < self.min_year_built:
                return False
        return True


class SemanticSearchQuery(DomainModel):
    """Natural-language property search request."""

    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    filters: PropertyFilter | None = None


class PropertyMatch(DomainModel):
    listing: PropertyListing
    score: float = Field(ge=0.0, le=1.0)
    highlights: list[str] = Field(default_factory=list)


class SearchResults(DomainModel):
    query: str
    matches: list[PropertyMatch] = Field(default_factory=list)
    total_considered: int = Field(default=0, ge=0)


__all__ = [
    "Address",
    "Demographics",
    "DomainModel",
    "GeoPoint",
    "ListingStatus",
    "PropertyFilter",
    "PropertyListing",
    "PropertyMatch",
    "PropertyType",
    "SearchResults",
    "SemanticSearchQuery",
]
