from __future__ import annotations

import threading
import time
from typing import Any

from ..config import settings


class TTLCache:
    """Thread-safe in-memory cache with TTL expiry."""

    def __init__(self, default_ttl: int = settings.CACHE_TTL_SECONDS):
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl if ttl is not None else self._default_ttl
        with self._lock:
            self._store[key] = (value, time.time() + ttl)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def age_seconds(self, key: str) -> int:
        """Return how old a cached entry is, or 0 if not found."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return 0
            _, expires_at = entry
            age = self._default_ttl - (expires_at - time.time())
            return max(0, int(age))


cache = TTLCache()
