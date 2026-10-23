"""MCP server entry point.

Domain tools are registered by later modules on the shared ``mcp`` instance.
"""

import logging

from mcp.server.mcpserver import MCPServer

from mls_mcp import __version__
from mls_mcp.config import get_settings

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
