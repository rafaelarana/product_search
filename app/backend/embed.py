"""Query-time embedding via Databricks Model Serving (BGE-large-en, 1024-dim).

Two entry points:

- :func:`embed_query`         — always hits Model Serving (used by /api/search)
- :func:`embed_query_cached`  — thread-safe LRU cache around the same call
                                 (used by /api/search/fast in "Turbo" mode)
"""
from __future__ import annotations

import threading
from collections import OrderedDict

from databricks.sdk import WorkspaceClient

from . import settings

_workspace = WorkspaceClient(
    host=settings.DATABRICKS_HOST or None,
    client_id=settings.DATABRICKS_CLIENT_ID,
    client_secret=settings.DATABRICKS_CLIENT_SECRET,
)


def embed_query(text: str) -> list[float]:
    """Return a 1024-dim BGE-large embedding for the user query.

    Always hits Model Serving — used by the Standard /api/search path.
    """
    resp = _workspace.serving_endpoints.query(
        name=settings.SERVING_ENDPOINT_EMBEDDING,
        input=[text],
    )
    # Foundation Models endpoints return objects with .data[N].embedding
    elt = resp.data[0]
    emb = elt.embedding if hasattr(elt, "embedding") else elt["embedding"]
    return list(emb)


def batch_embed(texts: list[str]) -> list[list[float]]:
    """Embed many queries in a single Model Serving call.

    Used by the preload step at startup so we don't pay 100 round-trip costs.
    """
    if not texts:
        return []
    resp = _workspace.serving_endpoints.query(
        name=settings.SERVING_ENDPOINT_EMBEDDING,
        input=texts,
    )
    out: list[list[float]] = []
    for elt in resp.data:
        emb = elt.embedding if hasattr(elt, "embedding") else elt["embedding"]
        out.append(list(emb))
    return out


class _EmbedCache:
    """Thread-safe LRU cache keyed by normalized query text.

    Used by Turbo mode to skip the Model Serving round-trip when a query
    repeats. The cache is process-local — on a multi-replica deployment, each
    replica builds its own warm set. For an e-commerce workload where the
    query distribution is heavily Zipfian, that's fine (each replica still
    sees ~80% of head queries within the first few minutes).
    """

    def __init__(self, maxsize: int = 10_000) -> None:
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()
        self.maxsize = maxsize
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _normalize(q: str) -> str:
        return " ".join(q.strip().lower().split())

    def get_or_compute(self, q: str) -> tuple[list[float], bool]:
        """Return ``(embedding, cache_hit)``.

        On a hit, returns the cached vector without touching Model Serving.
        On a miss, calls :func:`embed_query` outside the lock and stores the
        result.
        """
        key = self._normalize(q)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self.hits += 1
                return self._cache[key], True

        # Miss — compute outside the lock so concurrent miss-distinct keys
        # don't serialize on the embedding call.
        vec = embed_query(key)

        with self._lock:
            # Double-check in case another thread won the race.
            if key in self._cache:
                self.hits += 1
            else:
                self.misses += 1
                self._cache[key] = vec
                if len(self._cache) > self.maxsize:
                    self._cache.popitem(last=False)
            return vec, False

    def preload(self, queries: list[str], vectors: list[list[float]]) -> int:
        """Insert pre-computed (query, vector) pairs from a batch embed call.

        Returns the number of new entries inserted (does not overwrite hits).
        """
        n = 0
        with self._lock:
            for q, vec in zip(queries, vectors):
                key = self._normalize(q)
                if key in self._cache:
                    continue
                self._cache[key] = vec
                self._cache.move_to_end(key)
                if len(self._cache) > self.maxsize:
                    self._cache.popitem(last=False)
                n += 1
        return n

    def stats(self) -> dict[str, int]:
        with self._lock:
            total = self.hits + self.misses
            ratio_pct = int(100 * self.hits / total) if total else 0
            return {
                "size": len(self._cache),
                "maxsize": self.maxsize,
                "hits": self.hits,
                "misses": self.misses,
                "hit_ratio_pct": ratio_pct,
            }


# Module-level singleton.
embed_cache = _EmbedCache(maxsize=10_000)


def embed_query_cached(q: str) -> tuple[list[float], bool]:
    """Cached variant. Returns ``(embedding, cache_hit)``."""
    return embed_cache.get_or_compute(q)
