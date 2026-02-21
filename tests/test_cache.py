from __future__ import annotations

import time

from src.location_sentinel.storage.cache import TTLCache


class TestTTLCache:
    def test_set_get(self):
        c = TTLCache(default_ttl=60)
        c.set("k1", "v1")
        assert c.get("k1") == "v1"

    def test_miss(self):
        c = TTLCache(default_ttl=60)
        assert c.get("missing") is None

    def test_expiry(self):
        c = TTLCache(default_ttl=1)
        c.set("k1", "v1", ttl=1)
        assert c.get("k1") == "v1"
        time.sleep(1.1)
        assert c.get("k1") is None

    def test_delete(self):
        c = TTLCache(default_ttl=60)
        c.set("k1", "v1")
        c.delete("k1")
        assert c.get("k1") is None

    def test_clear(self):
        c = TTLCache(default_ttl=60)
        c.set("k1", "v1")
        c.set("k2", "v2")
        c.clear()
        assert c.get("k1") is None
        assert c.get("k2") is None

    def test_overwrite(self):
        c = TTLCache(default_ttl=60)
        c.set("k1", "v1")
        c.set("k1", "v2")
        assert c.get("k1") == "v2"
