"""In-memory TTL cache for upstream GET payloads.

Upstream calls (MLS OData pages, Census snapshots) are expensive and rarely
change within a session, so clients memoise decoded JSON here. Values are
payloads, never responses: reuse across callers is safe because httpx responses
are closed before anything is cached.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx


class TTLCache:
    """Keyed cache with per-entry expiry. ``ttl_seconds <= 0`` disables caching."""

    def __init__(
        self,
        ttl_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._entries[key]
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        if self._ttl > 0:
            self._entries[key] = (self._clock() + self._ttl, value)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


async def fetch_json(
    client: httpx.AsyncClient,
    cache: TTLCache,
    url: str,
    *,
    params: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """GET ``url`` and decode JSON, memoised on URL plus query parameters.

    Auth headers stay out of the key: one process authenticates as one principal.
    """
    key = (url, tuple(sorted((params or {}).items())))
    cached = cache.get(key)
    if cached is not None:
        return cached
    response = await client.get(url, params=params, headers=headers)
    response.raise_for_status()
    payload = response.json()
    cache.set(key, payload)
    return payload


__all__ = ["TTLCache", "fetch_json"]
