"""FastAPI backend for the Lumen product recommender Databricks App.

Two parallel API surfaces:

- ``/api/search``                    — Standard mode (BGE-large every call)
- ``/api/search/fast``               — Turbo mode (LRU-cached embeddings)
- ``/api/product/{id}/similar``      — Standard recommender (HNSW per call)
- ``/api/product/{id}/similar/fast`` — Turbo recommender (precomputed neighbors)
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .embed import batch_embed, embed_cache, embed_query, embed_query_cached
from .lakebase import pool
from . import loadgen
from .loadgen import BenchmarkConfig, BenchmarkStatus, SAMPLE_QUERIES
from .result_cache import result_cache

log = logging.getLogger("product_recommender")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    pool.open()
    pool.wait()
    log.info("Lakebase pool opened (min=%d, max=%d)", pool.min_size, pool.max_size)
    # Kick off the cache pre-warm in the background so we serve traffic
    # immediately; hot queries become fast as the preload progresses.
    asyncio.create_task(_preload_caches())
    yield
    pool.close()


def _seed_query_ids(query: str, vec: list[float], mode: str, limit: int = 20) -> list[tuple[int, float]]:
    """Run the live search SQL once to compute the seed entry for a query."""
    with pool.connection() as conn, conn.cursor() as cur:
        if mode == "hybrid":
            cur.execute(
                "SELECT product_id, combined_score FROM "
                "search_products_hybrid(%s, %s::vector(1024), %s, %s)",
                [query, vec, None, limit],
            )
            return [(r["product_id"], float(r["combined_score"])) for r in cur.fetchall()]
        cur.execute(
            "SELECT product_id, similarity FROM "
            "search_products_semantic(%s::vector(1024), %s, %s)",
            [vec, None, limit],
        )
        return [(r["product_id"], float(r["similarity"])) for r in cur.fetchall()]


async def _preload_caches() -> None:
    """One-shot preload: batch-embed the seed queries, populate both caches."""
    t0 = time.perf_counter()
    queries = SAMPLE_QUERIES
    try:
        # 1. One Model Serving call for all seed queries.
        vecs = await asyncio.to_thread(batch_embed, queries)
        n_embed = embed_cache.preload(queries, vecs)
        log.info("preload: embed cache +%d (%.2fs)", n_embed, time.perf_counter() - t0)

        # 2. Compute and cache result IDs for each (query, mode) — no class filter.
        for q, vec in zip(queries, vecs):
            for mode in ("semantic", "hybrid"):
                try:
                    ids = await asyncio.to_thread(_seed_query_ids, q, vec, mode)
                    result_cache.put_preloaded(q, mode, None, ids)
                except Exception:  # pragma: no cover
                    log.exception("preload entry failed (q=%r mode=%s)", q, mode)
        result_cache.mark_ready()
        log.info("preload: result cache ready, %d entries (%.2fs total)",
                 result_cache.stats()["preloaded"], time.perf_counter() - t0)
    except Exception:  # pragma: no cover
        log.exception("preload failed")


app = FastAPI(title="Lumen", lifespan=lifespan)


# ---------- request/response models ------------------------------------------


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=200)
    mode: str = Field("semantic", pattern="^(semantic|hybrid)$")
    product_class: str | None = None
    limit: int = Field(20, ge=1, le=50)


class SearchHit(BaseModel):
    product_id: int
    product_name: str
    product_class: str | None
    category_hierarchy: str | None
    average_rating: float | None
    review_count: int | None
    score: float


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    embed_ms: int
    db_ms: int
    total_ms: int
    mode: str
    cache_hit: bool = False  # set by Turbo when ANY cache layer helped
    cache_layer: str = "none"  # one of: "none", "embed", "result"


class ProductDetail(BaseModel):
    product_id: int
    product_name: str
    product_class: str | None
    category_hierarchy: str | None
    product_description: str | None
    product_features: str | None
    average_rating: float | None
    review_count: int | None


class ClassFacet(BaseModel):
    product_class: str
    n: int


# ---------- shared helpers ---------------------------------------------------


def _run_search(qvec: list[float], req: SearchRequest, cur) -> tuple[list[SearchHit], str]:
    """Execute the search SQL function and shape hits. Returns (hits, score_col)."""
    if req.mode == "hybrid":
        cur.execute(
            "SELECT * FROM search_products_hybrid(%s, %s::vector(1024), %s, %s)",
            [req.q, qvec, req.product_class, req.limit],
        )
        score_col = "combined_score"
    else:
        cur.execute(
            "SELECT * FROM search_products_semantic(%s::vector(1024), %s, %s)",
            [qvec, req.product_class, req.limit],
        )
        score_col = "similarity"
    rows = cur.fetchall()
    hits = [
        SearchHit(
            product_id=r["product_id"],
            product_name=r["product_name"],
            product_class=r.get("product_class"),
            category_hierarchy=r.get("category_hierarchy"),
            average_rating=r.get("average_rating"),
            review_count=r.get("review_count"),
            score=float(r[score_col]),
        )
        for r in rows
    ]
    return hits, score_col


# ---------- endpoints --------------------------------------------------------


@app.get("/api/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/cache/stats")
def cache_stats() -> dict[str, object]:
    """Cache hit/miss counters for both Turbo layers."""
    return {
        "embed": embed_cache.stats(),
        "result": result_cache.stats(),
    }


@app.get("/api/classes", response_model=list[ClassFacet])
def list_classes(limit: int = 50) -> list[ClassFacet]:
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM list_product_classes(%s)", [limit])
        rows = cur.fetchall()
    return [ClassFacet(product_class=r["product_class"], n=r["n"]) for r in rows]


# --- Standard mode ----------------------------------------------------------


@app.post("/api/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    t_start = time.perf_counter()

    t_embed = time.perf_counter()
    qvec = embed_query(req.q)
    embed_ms = int((time.perf_counter() - t_embed) * 1000)

    t_db = time.perf_counter()
    with pool.connection() as conn, conn.cursor() as cur:
        hits, _ = _run_search(qvec, req, cur)
    db_ms = int((time.perf_counter() - t_db) * 1000)

    return SearchResponse(
        hits=hits,
        embed_ms=embed_ms,
        db_ms=db_ms,
        total_ms=int((time.perf_counter() - t_start) * 1000),
        mode=req.mode,
        cache_hit=False,
    )


@app.get("/api/product/{product_id}", response_model=ProductDetail)
def get_product(product_id: int) -> ProductDetail:
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM get_product(%s)", [product_id])
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, f"product {product_id} not found")
    return ProductDetail(**row)


@app.get("/api/product/{product_id}/similar", response_model=list[SearchHit])
def similar(product_id: int, limit: int = 8, same_class: bool = False) -> list[SearchHit]:
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM recommend_similar_products(%s, %s, %s)",
            [product_id, limit, same_class],
        )
        rows = cur.fetchall()
    return [
        SearchHit(
            product_id=r["product_id"],
            product_name=r["product_name"],
            product_class=r.get("product_class"),
            category_hierarchy=None,
            average_rating=r.get("average_rating"),
            review_count=r.get("review_count"),
            score=float(r["similarity"]),
        )
        for r in rows
    ]


# --- Turbo mode -------------------------------------------------------------


def _hits_from_cached(ids_and_scores: list[tuple[int, float]], limit: int, cur) -> list[SearchHit]:
    """Resolve cached (id, score) pairs into SearchHit rows via a single PK
    lookup against products_mv, preserving rank order."""
    ids = [i for i, _ in ids_and_scores[:limit]]
    if not ids:
        return []
    score_by_id = {i: s for i, s in ids_and_scores[:limit]}
    cur.execute(
        """
        SELECT product_id, product_name, product_class, category_hierarchy,
               average_rating, review_count
        FROM lumen_gold.products_mv
        WHERE product_id = ANY(%s)
        """,
        [ids],
    )
    rows_by_id = {r["product_id"]: r for r in cur.fetchall()}
    out: list[SearchHit] = []
    for pid in ids:
        r = rows_by_id.get(pid)
        if r is None:
            continue
        out.append(
            SearchHit(
                product_id=r["product_id"],
                product_name=r["product_name"],
                product_class=r.get("product_class"),
                category_hierarchy=r.get("category_hierarchy"),
                average_rating=r.get("average_rating"),
                review_count=r.get("review_count"),
                score=score_by_id[pid],
            )
        )
    return out


@app.post("/api/search/fast", response_model=SearchResponse)
def search_fast(req: SearchRequest) -> SearchResponse:
    """Turbo path. Layered cache:

    1. result cache  → (query, mode, class) → [(id, score)]: pure PK lookup
    2. embed cache   → query → vector: skip Model Serving, still HNSW
    3. fall through  → Model Serving + HNSW (cold path)
    """
    t_start = time.perf_counter()

    # Layer 1: result cache (only for the no-class-filter case at present).
    if req.product_class is None:
        cached = result_cache.get(req.q, req.mode, None)
        if cached is not None:
            t_db = time.perf_counter()
            with pool.connection() as conn, conn.cursor() as cur:
                hits = _hits_from_cached(cached, req.limit, cur)
            db_ms = int((time.perf_counter() - t_db) * 1000)
            return SearchResponse(
                hits=hits,
                embed_ms=0,
                db_ms=db_ms,
                total_ms=int((time.perf_counter() - t_start) * 1000),
                mode=req.mode,
                cache_hit=True,
                cache_layer="result",
            )

    # Layer 2: embedding cache.
    t_embed = time.perf_counter()
    qvec, embed_hit = embed_query_cached(req.q)
    embed_ms = int((time.perf_counter() - t_embed) * 1000)

    t_db = time.perf_counter()
    with pool.connection() as conn, conn.cursor() as cur:
        hits, _ = _run_search(qvec, req, cur)
    db_ms = int((time.perf_counter() - t_db) * 1000)

    return SearchResponse(
        hits=hits,
        embed_ms=embed_ms,
        db_ms=db_ms,
        total_ms=int((time.perf_counter() - t_start) * 1000),
        mode=req.mode,
        cache_hit=embed_hit,
        cache_layer="embed" if embed_hit else "none",
    )


@app.get("/api/product/{product_id}/similar/fast", response_model=list[SearchHit])
def similar_fast(product_id: int, limit: int = 8) -> list[SearchHit]:
    """Same shape as /similar but reads from the precomputed similar_top_k MV.

    Drops the per-call HNSW lookup; the response score is the rank position
    (1 = best) rendered as `1 - rank/limit` so the UI score badge still
    sorts/colors correctly.
    """
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM recommend_similar_products_fast(%s, %s)",
            [product_id, limit],
        )
        rows = cur.fetchall()
    return [
        SearchHit(
            product_id=r["product_id"],
            product_name=r["product_name"],
            product_class=r.get("product_class"),
            category_hierarchy=None,
            average_rating=r.get("average_rating"),
            review_count=r.get("review_count"),
            score=1.0 - (float(r["rank"]) - 1.0) / max(float(limit), 1.0),
        )
        for r in rows
    ]


# --- Benchmark ---------------------------------------------------------------


class BenchmarkStartResponse(BaseModel):
    job_id: str


@app.post("/api/benchmark/start", response_model=BenchmarkStartResponse)
async def benchmark_start(cfg: BenchmarkConfig) -> BenchmarkStartResponse:
    """Kick off an async load test against this app's local socket.

    MUST be `async def` so the asyncio.create_task() inside start_job() runs
    against FastAPI's main event loop. A sync handler would put us in a
    threadpool worker where create_task can't schedule on a running loop —
    the task gets created but never executes.
    """
    try:
        job = loadgen.start_job(cfg)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return BenchmarkStartResponse(job_id=job.job_id)


@app.get("/api/benchmark/current")
def benchmark_current() -> dict[str, str | None]:
    """Return the in-flight job_id (or null) so the UI can resume on reload."""
    job = loadgen.current_running_job()
    return {"job_id": job.job_id if job else None}


@app.get("/api/benchmark/{job_id}", response_model=BenchmarkStatus)
def benchmark_status(job_id: str) -> BenchmarkStatus:
    job = loadgen.get_job(job_id)
    if not job:
        raise HTTPException(404, f"job {job_id} not found")
    return loadgen.job_status(job)


@app.post("/api/benchmark/{job_id}/stop", response_model=BenchmarkStatus)
async def benchmark_stop(job_id: str) -> BenchmarkStatus:
    job = loadgen.get_job(job_id)
    if not job:
        raise HTTPException(404, f"job {job_id} not found")
    if job.state == "running":
        await loadgen.stop_job(job_id)
    return loadgen.job_status(job)


# ---------- static frontend --------------------------------------------------

_static_dir = Path(__file__).parent.parent / "frontend" / "dist"
if _static_dir.exists():
    app.mount("/assets", StaticFiles(directory=_static_dir / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:  # noqa: ARG001
        return FileResponse(_static_dir / "index.html")
