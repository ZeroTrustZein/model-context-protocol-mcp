import logging

import pytest

import mls_mcp
from mls_mcp.config import Settings, get_settings
from mls_mcp.server import SERVER_NAME, configure_logging, mcp, server_info


def test_version_is_exposed() -> None:
    assert isinstance(mls_mcp.__version__, str) and mls_mcp.__version__


def test_server_name() -> None:
    assert mcp.name == SERVER_NAME == "mls-mcp"


def test_server_info_reports_configuration_state() -> None:
    info = server_info()
    assert info["name"] == SERVER_NAME
    assert isinstance(info["mls_configured"], bool)


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.vector_store_collection == "property_listings"
    assert settings.http_timeout_seconds > 0


def test_configure_logging_applies_level() -> None:
    configure_logging("debug")
    assert logging.getLogger().level == logging.DEBUG


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CACHE_TTL_SECONDS", "42")
    assert Settings(_env_file=None).cache_ttl_seconds == 42


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
