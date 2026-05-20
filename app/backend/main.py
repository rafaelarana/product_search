"""FastAPI backend for the Lumen product recommender Databricks App.

Two parallel API surfaces:

- ``/api/search``                    — Standard mode (BGE-large every call)
- ``/api/search/fast``               — Turbo mode (LRU-cached embeddings)
- ``/api/product/{id}/similar``      — Standard recommender (HNSW per call)
- ``/api/product/{id}/similar/fast`` — Turbo recommender (precomputed neighbors)
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .embed import embed_cache, embed_query, embed_query_cached
from .lakebase import pool
from . import loadgen
from .loadgen import BenchmarkConfig, BenchmarkStatus

log = logging.getLogger("product_recommender")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    pool.open()
    pool.wait()
    log.info("Lakebase pool opened")
    yield
    pool.close()


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
    cache_hit: bool = False  # only set by Turbo mode


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
def cache_stats() -> dict[str, int]:
    """Embedding-cache hit/miss counters (Turbo mode visibility)."""
    return embed_cache.stats()


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


@app.post("/api/search/fast", response_model=SearchResponse)
def search_fast(req: SearchRequest) -> SearchResponse:
    """Same as /api/search but uses the LRU embedding cache.

    First call for a given normalized query string still hits Model Serving;
    every subsequent call returns instantly from in-memory cache.
    """
    t_start = time.perf_counter()

    t_embed = time.perf_counter()
    qvec, cache_hit = embed_query_cached(req.q)
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
        cache_hit=cache_hit,
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
