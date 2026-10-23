"""MCP server entry point: tools, logging and stdio transport."""

import logging

from mcp.server.mcpserver import MCPServer

from mls_mcp import __version__
from mls_mcp.census import CensusClient
from mls_mcp.config import get_settings
from mls_mcp.mls import MLSClient
from mls_mcp.models import PropertyFilter, SemanticSearchQuery
from mls_mcp.search import search_listings as rank_listings

SERVER_NAME = "mls-mcp"

mcp = MCPServer(SERVER_NAME, version=__version__)


@mcp.tool()
def server_info() -> dict[str, object]:
    """Report server name, version and non-secret configuration state."""
    settings = get_settings()
    return {
        "name": SERVER_NAME,
        "version": __version__,
        "mls_configured": bool(settings.mls_api_key or settings.mls_api_token),
        "census_configured": bool(settings.census_api_key),
        "vector_store_configured": bool(settings.vector_store_url),
    }


@mcp.tool()
async def search_listings(
    query: str,
    top_k: int = 10,
    city: str | None = None,
    state: str | None = None,
    postal_code: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_bedrooms: int | None = None,
    min_bathrooms: float | None = None,
    min_sqft: float | None = None,
    max_sqft: float | None = None,
) -> dict[str, object]:
    """Search MLS listings in natural language, ranked by query relevance."""
    filters = PropertyFilter(
        city=city,
        state=state,
        postal_code=postal_code,
        min_price=min_price,
        max_price=max_price,
        min_bedrooms=min_bedrooms,
        min_bathrooms=min_bathrooms,
        min_sqft=min_sqft,
        max_sqft=max_sqft,
    )
    # Widen the candidate pool so ranking has more than ``top_k`` rows to choose from.
    pool = max(top_k * 5, 50)
    async with MLSClient() as client:
        listings = await client.search(filters, limit=pool)
    results = rank_listings(
        listings, SemanticSearchQuery(query=query, top_k=top_k, filters=filters)
    )
    return results.model_dump(mode="json")


@mcp.tool()
async def get_demographics(
    geography: str,
    in_geography: str | None = None,
    year: int | None = None,
) -> dict[str, object]:
    """Census ACS snapshot for one geography, e.g. ``zip code:78704``."""
    async with CensusClient() as client:
        snapshot = await client.demographics(geography, in_clause=in_geography, year=year)
    return snapshot.model_dump(mode="json")


def configure_logging(level: str | None = None) -> None:
    """Send stderr logs at ``LOG_LEVEL`` so stdio transport stays clean."""
    logging.basicConfig(
        level=(level or get_settings().log_level).upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )
    # basicConfig is a no-op once any handler exists (uvicorn, pytest), so pin the level.
    logging.getLogger().setLevel((level or get_settings().log_level).upper())


def main() -> None:
    """Run over stdio (default transport)."""
    configure_logging()
    mcp.run()


if __name__ == "__main__":
    main()
