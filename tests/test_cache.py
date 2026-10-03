"""Tests for SearchCache — LRU + TTL thread-safe cache."""

import time
import threading
import pytest

from src.cache import SearchCache


class TestCacheGetPut:
    def test_get_missing_returns_none(self):
        cache = SearchCache()
        assert cache.get("hello", tags=["test"]) is None

    def test_put_and_get_basic(self):
        cache = SearchCache()
        cache.put("hello", [{"id": 1}], tags=["test"], mode="hybrid", limit=10)
        result = cache.get("hello", tags=["test"], mode="hybrid", limit=10)
        assert result == [{"id": 1}]

    def test_get_with_different_params_misses(self):
        cache = SearchCache()
        cache.put("hello", [{"id": 1}], tags=["test"], mode="hybrid", limit=10)
        assert cache.get("hello", tags=["test"], mode="fts") is None
        assert cache.get("hello", tags=["other"], mode="hybrid") is None
        assert cache.get("hello", tags=["test"], mode="hybrid", limit=5) is None

    def test_put_overwrites_existing(self):
        cache = SearchCache()
        cache.put("hello", [{"id": 1}], tags=["test"])
        cache.put("hello", [{"id": 2}], tags=["test"])
        result = cache.get("hello", tags=["test"])
        assert result == [{"id": 2}]

    def test_put_moves_to_end(self):
        cache = SearchCache(max_size=2)
        cache.put("a", [1], tags=["s"])
        cache.put("b", [2], tags=["s"])
        cache.put("a", [1], tags=["s"])  # touch a
        cache.put("c", [3], tags=["s"])  # should evict b, not a
        assert cache.get("a", tags=["s"]) == [1]
        assert cache.get("b", tags=["s"]) is None
        assert cache.get("c", tags=["s"]) == [3]


class TestCacheLRU:
    def test_lru_eviction_oldest(self):
        cache = SearchCache(max_size=3)
        cache.put("a", [1], tags=["s"])
        cache.put("b", [2], tags=["s"])
        cache.put("c", [3], tags=["s"])
        cache.put("d", [4], tags=["s"])
        assert cache.get("a", tags=["s"]) is None
        assert cache.get("b", tags=["s"]) == [2]
        assert cache.get("c", tags=["s"]) == [3]
        assert cache.get("d", tags=["s"]) == [4]

    def test_get_refreshes_lru_position(self):
        cache = SearchCache(max_size=3)
        cache.put("a", [1], tags=["s"])
        cache.put("b", [2], tags=["s"])
        cache.put("c", [3], tags=["s"])
        cache.get("a", tags=["s"])  # refresh a
        cache.put("d", [4], tags=["s"])  # should evict b
        assert cache.get("a", tags=["s"]) == [1]
        assert cache.get("b", tags=["s"]) is None
        assert cache.get("c", tags=["s"]) == [3]
        assert cache.get("d", tags=["s"]) == [4]


class TestCacheTTL:
    def test_ttl_expiry(self):
        cache = SearchCache(ttl=0)
        cache.put("hello", [{"id": 1}], tags=["test"])
        time.sleep(0.01)
        assert cache.get("hello", tags=["test"]) is None

    def test_ttl_does_not_expire_immediately(self):
        cache = SearchCache(ttl=60)
        cache.put("hello", [{"id": 1}], tags=["test"])
        assert cache.get("hello", tags=["test"]) == [{"id": 1}]

    def test_ttl_expiry_removes_key(self):
        cache = SearchCache(ttl=0)
        cache.put("hello", [{"id": 1}], tags=["test"])
        time.sleep(0.01)
        cache.get("hello", tags=["test"])  # trigger cleanup
        assert cache.stats()["size"] == 0


class TestCacheInvalidate:
    def test_invalidate_all(self):
        cache = SearchCache()
        cache.put("a", [1], tags=["s1"])
        cache.put("b", [2], tags=["s2"])
        count = cache.invalidate()
        assert count == 2
        assert cache.get("a", tags=["s1"]) is None
        assert cache.get("b", tags=["s2"]) is None

    def test_invalidate_by_query(self):
        cache = SearchCache()
        cache.put("a", [1], tags=["s1"])
        cache.put("b", [2], tags=["s2"])
        cache.put("a", [3], tags=["s3"])
        count = cache.invalidate(query="a")
        assert count == 2
        assert cache.get("a", tags=["s1"]) is None
        assert cache.get("b", tags=["s2"]) == [2]
        assert cache.get("a", tags=["s3"]) is None

    def test_invalidate_by_tags(self):
        cache = SearchCache()
        cache.put("a", [1], tags=["s1"])
        cache.put("b", [2], tags=["s1"])
        cache.put("c", [3], tags=["s2"])
        count = cache.invalidate(tags=["s1"])
        assert count == 2
        assert cache.get("a", tags=["s1"]) is None
        assert cache.get("b", tags=["s1"]) is None
        assert cache.get("c", tags=["s2"]) == [3]

    def test_invalidate_by_query_and_tags(self):
        cache = SearchCache()
        cache.put("a", [1], tags=["s1"])
        cache.put("a", [2], tags=["s2"])
        cache.put("b", [3], tags=["s1"])
        count = cache.invalidate(query="a", tags=["s1"])
        assert count == 1
        assert cache.get("a", tags=["s1"]) is None
        assert cache.get("a", tags=["s2"]) == [2]
        assert cache.get("b", tags=["s1"]) == [3]

    def test_invalidate_removes_wildcard_entries_when_tags_specified(self):
        cache = SearchCache()
        cache.put("a", [1], tags=None)  # stored with "*"
        cache.put("b", [2], tags=["s1"])
        count = cache.invalidate(tags=["s1"])
        assert count == 2
        assert cache.get("a", tags=None) is None
        assert cache.get("b", tags=["s1"]) is None


class TestCacheClear:
    def test_clear_removes_all(self):
        cache = SearchCache()
        cache.put("a", [1], tags=["s"])
        cache.clear()
        assert cache.get("a", tags=["s"]) is None
        assert cache.stats()["size"] == 0


class TestCacheStats:
    def test_stats_empty(self):
        cache = SearchCache(max_size=500, ttl=60)
        stats = cache.stats()
        assert stats == {"size": 0, "max_size": 500, "ttl": 60}

    def test_stats_with_entries(self):
        cache = SearchCache(max_size=100, ttl=30)
        cache.put("a", [1], tags=["s"])
        cache.put("b", [2], tags=["s"])
        stats = cache.stats()
        assert stats["size"] == 2
        assert stats["max_size"] == 100
        assert stats["ttl"] == 30


class TestCacheThreadSafety:
    def test_concurrent_put_and_get(self):
        cache = SearchCache(max_size=100)
        errors = []

        def worker(i):
            try:
                cache.put(f"q{i}", [i], tags=["s"])
                result = cache.get(f"q{i}", tags=["s"])
                if result != [i]:
                    errors.append(f"mismatch on {i}: {result}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert cache.stats()["size"] == 50

    def test_concurrent_invalidate(self):
        cache = SearchCache()
        for i in range(100):
            cache.put(f"q{i}", [i], tags=["s"])

        def putter():
            for i in range(100, 200):
                cache.put(f"q{i}", [i], tags=["s"])

        def invalidator():
            cache.invalidate(query="q50")

        threads = [
            threading.Thread(target=putter),
            threading.Thread(target=invalidator),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = cache.stats()
        assert 0 <= stats["size"] <= 199

    def test_concurrent_ttl_expiry(self):
        cache = SearchCache(ttl=0)

        def putter():
            for i in range(50):
                cache.put(f"q{i}", [i], tags=["s"])

        def getter():
            for i in range(50):
                cache.get(f"q{i}", tags=["s"])

        threads = [
            threading.Thread(target=putter),
            threading.Thread(target=getter),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = cache.stats()
        assert isinstance(stats["size"], int)


class TestCacheKeyConstruction:
    def test_none_tags_becomes_star(self):
        cache = SearchCache()
        cache.put("hello", [{"id": 1}], tags=None)
        result = cache.get("hello", tags=None)
        assert result == [{"id": 1}]

    def test_key_uniqueness(self):
        cache = SearchCache()
        cache.put("hello", [1], tags=["s"], mode="hybrid", limit=10)
        cache.put("hello", [2], tags=["s"], mode="fts", limit=10)
        cache.put("hello", [3], tags=["s"], mode="hybrid", limit=5)
        assert cache.get("hello", tags=["s"], mode="hybrid", limit=10) == [1]
        assert cache.get("hello", tags=["s"], mode="fts", limit=10) == [2]
        assert cache.get("hello", tags=["s"], mode="hybrid", limit=5) == [3]
