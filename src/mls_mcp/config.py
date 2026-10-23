"""Runtime configuration, loaded from the environment (see .env.example)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings. Secrets stay in the environment, never in code."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mls_api_base: str = "https://api.example-mls.com/reso/odata"
    mls_api_key: str = ""
    mls_api_secret: str = ""
    mls_api_token: str = ""
    mls_token_url: str = ""

    census_api_base: str = "https://api.census.gov/data"
    census_api_key: str = ""

    vector_store_url: str = ""
    vector_store_collection: str = "property_listings"
    embedding_model: str = "text-embedding-3-small"

    log_level: str = "INFO"
    http_timeout_seconds: float = 30.0
    cache_ttl_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
