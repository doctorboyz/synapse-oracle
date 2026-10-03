"""Search cache — LRU + TTL cache for search results."""

import time
from collections import OrderedDict
from threading import Lock


class SearchCache:
    """Thread-safe LRU + TTL search result cache."""

    def __init__(self, max_size: int = 1000, ttl: int = 300):
        self._max_size = max_size
        self._ttl = ttl
        self._cache: OrderedDict[str, tuple] = OrderedDict()
        self._lock = Lock()

    def _make_key(self, query: str, tags: list[str] | None, mode: str, limit: int) -> str:
        tags_str = ",".join(sorted(tags)) if tags else "*"
        return f"{query}||{tags_str}||{mode}||{limit}"

    def get(self, query: str, tags: list[str] | None = None, mode: str = "hybrid",
            limit: int = 10) -> list | None:
        key = self._make_key(query, tags, mode, limit)
        with self._lock:
            if key not in self._cache:
                return None
            results, timestamp = self._cache[key]
            if time.time() - timestamp > self._ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return results

    def put(self, query: str, results: list, tags: list[str] | None = None,
            mode: str = "hybrid", limit: int = 10) -> None:
        key = self._make_key(query, tags, mode, limit)
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            self._cache[key] = (results, time.time())
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self, query: str | None = None, tags: list[str] | None = None) -> int:
        with self._lock:
            if query is None and tags is None:
                count = len(self._cache)
                self._cache.clear()
                return count
            keys_to_remove = []
            tag_str = ",".join(sorted(tags)) if tags else None
            for key in self._cache:
                parts = key.split("||")
                if len(parts) >= 2:
                    key_query = parts[0]
                    key_tags = parts[1]
                    if query and query != key_query:
                        continue
                    if tag_str and tag_str != key_tags and key_tags != "*":
                        continue
                    keys_to_remove.append(key)
            for key in keys_to_remove:
                del self._cache[key]
            return len(keys_to_remove)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "ttl": self._ttl,
            }