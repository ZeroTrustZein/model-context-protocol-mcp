"""MLS + demographics MCP server."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mls-mcp")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.1.0"

__all__ = ["__version__"]
