"""Result-level cache: ``(query, mode, product_class) → [(product_id, score)]``.

Skips both the Model Serving call AND the pgvector HNSW search for queries
seen at startup. Populated by a background preload task in ``main.py``
lifespan from a seed list of common queries.

Same key normalization as :class:`embed._EmbedCache`. ``product_class=None``
is the no-filter case (most search traffic).
"""
from __future__ import annotations

import threading
from collections import OrderedDict

# Stored value: ordered list of (product_id, score). Score is similarity for
# semantic mode, RRF combined_score for hybrid.
CachedHits = list[tuple[int, float]]


def _normalize(q: str) -> str:
    return " ".join(q.strip().lower().split())


class _ResultCache:
    def __init__(self, maxsize: int = 10_000) -> None:
        self._cache: OrderedDict[tuple[str, str, str | None], CachedHits] = OrderedDict()
        self._lock = threading.Lock()
        self.maxsize = maxsize
        self.hits = 0
        self.misses = 0
        self.preloaded = 0  # count of entries inserted by the preloader
        self.ready = False  # set True once preload finishes

    def get(self, query: str, mode: str, product_class: str | None) -> CachedHits | None:
        key = (_normalize(query), mode, product_class)
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None:
                self._cache.move_to_end(key)
                self.hits += 1
                return entry
            self.misses += 1
            return None

    def put(self, query: str, mode: str, product_class: str | None, hits: CachedHits) -> None:
        key = (_normalize(query), mode, product_class)
        with self._lock:
            self._cache[key] = hits
            self._cache.move_to_end(key)
            if len(self._cache) > self.maxsize:
                self._cache.popitem(last=False)

    def put_preloaded(self, query: str, mode: str, product_class: str | None,
                      hits: CachedHits) -> None:
        """Same as put() but counts toward the preloaded total."""
        self.put(query, mode, product_class, hits)
        with self._lock:
            self.preloaded += 1

    def mark_ready(self) -> None:
        with self._lock:
            self.ready = True

    def stats(self) -> dict[str, object]:
        with self._lock:
            total = self.hits + self.misses
            ratio_pct = int(100 * self.hits / total) if total else 0
            return {
                "size": len(self._cache),
                "maxsize": self.maxsize,
                "hits": self.hits,
                "misses": self.misses,
                "hit_ratio_pct": ratio_pct,
                "preloaded": self.preloaded,
                "ready": self.ready,
            }


# Module-level singleton.
result_cache = _ResultCache(maxsize=10_000)
