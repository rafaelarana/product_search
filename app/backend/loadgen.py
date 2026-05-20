"""In-app async load generator for the Benchmark tab.

Workers fire requests against the local FastAPI socket (no Apps edge auth,
so we measure backend latency without network noise) using httpx. Results
land in an in-memory job registry that the frontend polls.

The 100 sample queries are inlined here so the load gen has no I/O setup.
"""
from __future__ import annotations

import asyncio
import logging
import random
import statistics
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

import httpx
from pydantic import BaseModel, Field

log = logging.getLogger("loadgen")


# ---------------------------------------------------------------------------
# 100 WANDS-style queries (mirror of loadtest/src/queries.rs)
# ---------------------------------------------------------------------------
SAMPLE_QUERIES: list[str] = [
    "comfy reading chair for small living room",
    "mid-century modern accent chair",
    "leather club chair with ottoman",
    "swivel barrel chair in cream",
    "tufted velvet wingback chair",
    "small armchair for bedroom corner",
    "rocking chair for nursery",
    "outdoor adirondack chair set",
    "ergonomic office chair with lumbar support",
    "bar stool with backrest counter height",
    "sectional sofa with chaise gray",
    "compact apartment sofa under 70 inches",
    "leather recliner sofa power motion",
    "modular cloud couch deep seat",
    "sleeper sofa twin queen size",
    "round farmhouse dining table for 6",
    "live edge wood coffee table",
    "extendable dining table seats 10",
    "nesting side tables marble top",
    "console table with drawers entryway",
    "writing desk with hutch industrial",
    "queen platform bed with storage drawers",
    "king tufted upholstered headboard",
    "kids twin bunk bed with stairs",
    "memory foam mattress 12 inch queen",
    "cooling gel hybrid mattress king",
    "metal canopy bed frame",
    "tall narrow bookcase 6 shelves",
    "mid-century walnut dresser 6 drawers",
    "shoe storage bench entryway",
    "freestanding pantry cabinet kitchen",
    "tv stand for 75 inch screen",
    "8x10 vintage persian style area rug",
    "washable runner rug for hallway",
    "shag rug cream large living room",
    "outdoor patio rug weatherproof",
    "round jute rug 6 ft",
    "modern brass chandelier dining room",
    "arc floor lamp with marble base",
    "industrial pendant light kitchen island",
    "rechargeable cordless table lamp",
    "smart led bulb color changing",
    "large round mirror gold frame",
    "wall clock minimalist black",
    "abstract canvas art set of 3",
    "ceramic vase tall white",
    "throw pillow covers boho set of 4",
    "linen curtains blackout 96 inch",
    "scented soy candle vanilla",
    "100 percent cotton sheet set king",
    "down alternative comforter all season",
    "weighted blanket 15 lb queen",
    "duvet cover boho neutral",
    "mattress topper egg crate",
    "luxury turkish cotton bath towels",
    "freestanding tub modern slipper",
    "rain shower head with handheld",
    "shower curtain coastal blue",
    "bathroom vanity 36 inch single sink",
    "stainless steel kettle whistling",
    "cast iron skillet pre-seasoned 12 inch",
    "non-stick frying pan set ceramic",
    "stand mixer kitchen artisan",
    "espresso machine semi automatic",
    "air fryer 6 quart digital",
    "drip coffee maker programmable",
    "dutch oven enameled 7 qt",
    "knife block set japanese steel",
    "blender high powered smoothie",
    "stoneware dinnerware set service for 8",
    "wine glasses crystal set of 6",
    "flatware set modern matte black",
    "decorative serving platter ceramic",
    "patio dining set 6 seater wicker",
    "fire pit propane 30 inch",
    "outdoor sectional with cushions",
    "hammock with stand double",
    "garden bench wood for two",
    "umbrella patio offset 10 ft",
    "standing desk electric adjustable",
    "monitor arm dual gas spring",
    "bookcase ladder leaning oak",
    "filing cabinet 2 drawer locking",
    "kids play kitchen wooden",
    "toddler bed with rails low profile",
    "bean bag chair for teens",
    "raised dog bed cooling mesh",
    "cat tree tall multi level",
    "compact dishwasher 18 inch portable",
    "wine cooler dual zone 24 bottle",
    "garbage disposal 1 hp continuous feed",
    "artificial christmas tree 7 ft prelit",
    "pumpkin throw pillow fall",
    "luggage set hardside 3 piece",
    "yoga mat thick eco friendly",
    "humidifier cool mist large room",
    "robot vacuum self emptying",
    "tower fan oscillating quiet",
    "space heater small ceramic",
    "air purifier hepa true large room",
    "bidet attachment dual nozzle",
]


# ---------------------------------------------------------------------------
# Config / status / result models
# ---------------------------------------------------------------------------


class BenchmarkConfig(BaseModel):
    workers: int = Field(10, ge=1, le=100)
    duration_s: int = Field(30, ge=5, le=300)
    turbo_pct: int = Field(50, ge=0, le=100, description="% of requests to /api/search/fast")
    hybrid_pct: int = Field(30, ge=0, le=100, description="% of requests using hybrid mode")
    limit: int = Field(20, ge=1, le=50)


JobState = Literal["running", "done", "failed", "stopped"]


class BucketStats(BaseModel):
    name: str
    requests: int
    errors: int
    req_per_s: float
    avg_ms: float
    min_ms: float
    p50_ms: float
    p75_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


class BenchmarkResult(BaseModel):
    config: BenchmarkConfig
    elapsed_s: float
    total_requests: int
    total_errors: int
    aggregate_rps: float
    buckets: list[BucketStats]
    aggregate: BucketStats
    status_codes: dict[str, int]


class BenchmarkStatus(BaseModel):
    job_id: str
    state: JobState
    started_at: float
    elapsed_s: float
    config: BenchmarkConfig
    progress_pct: int
    result: BenchmarkResult | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Job registry (in-memory; fine for a single-replica demo app)
# ---------------------------------------------------------------------------


@dataclass
class _Job:
    job_id: str
    config: BenchmarkConfig
    state: JobState = "running"
    started_at: float = field(default_factory=time.time)
    elapsed_s: float = 0.0
    result: BenchmarkResult | None = None
    error: str | None = None
    task: asyncio.Task | None = None

    @property
    def progress_pct(self) -> int:
        if self.state != "running":
            return 100
        return min(100, int(100 * self.elapsed_s / max(self.config.duration_s, 1)))


_jobs: dict[str, _Job] = {}
_current_job_id: str | None = None


def get_job(job_id: str) -> _Job | None:
    return _jobs.get(job_id)


def any_running() -> bool:
    return any(j.state == "running" for j in _jobs.values())


def current_running_job() -> _Job | None:
    """Return the in-flight job, if any. Used by the UI to recover state."""
    if _current_job_id is None:
        return None
    job = _jobs.get(_current_job_id)
    if job is None or job.state != "running":
        return None
    return job


async def stop_job(job_id: str) -> bool:
    """Cancel the asyncio task backing a running job. Returns True if stopped."""
    job = _jobs.get(job_id)
    if job is None or job.state != "running" or job.task is None:
        return False
    job.task.cancel()
    try:
        await job.task
    except (asyncio.CancelledError, Exception):
        pass
    return True


# ---------------------------------------------------------------------------
# Workers + result aggregation
# ---------------------------------------------------------------------------


@dataclass
class _Sample:
    bucket: str  # e.g. "turbo:semantic"
    duration_ms: float
    status: int
    ok: bool


def _pick(turbo_pct: int, hybrid_pct: int) -> tuple[str, str, str]:
    """Return (url, search_mode, bucket_name)."""
    path = "turbo" if random.randint(0, 99) < turbo_pct else "standard"
    mode = "hybrid" if random.randint(0, 99) < hybrid_pct else "semantic"
    url = "/api/search/fast" if path == "turbo" else "/api/search"
    return url, mode, f"{path}:{mode}"


async def _worker(
    client: httpx.AsyncClient,
    deadline: float,
    cfg: BenchmarkConfig,
    samples: list[_Sample],
) -> None:
    while True:
        if asyncio.get_event_loop().time() >= deadline:
            return
        url, mode, bucket = _pick(cfg.turbo_pct, cfg.hybrid_pct)
        q = random.choice(SAMPLE_QUERIES)
        body = {"q": q, "mode": mode, "limit": cfg.limit}
        t0 = time.perf_counter()
        try:
            resp = await client.post(url, json=body, timeout=30.0)
            dt = (time.perf_counter() - t0) * 1000
            samples.append(
                _Sample(bucket=bucket, duration_ms=dt, status=resp.status_code, ok=resp.is_success)
            )
        except Exception:
            dt = (time.perf_counter() - t0) * 1000
            samples.append(_Sample(bucket=bucket, duration_ms=dt, status=0, ok=False))


def _quantile(sorted_data: list[float], q: float) -> float:
    if not sorted_data:
        return 0.0
    if len(sorted_data) == 1:
        return sorted_data[0]
    idx = q * (len(sorted_data) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_data) - 1)
    frac = idx - lo
    return sorted_data[lo] + (sorted_data[hi] - sorted_data[lo]) * frac


def _bucket_stats(name: str, samples: list[_Sample], elapsed_s: float) -> BucketStats:
    durations = sorted(s.duration_ms for s in samples if s.ok)
    errors = sum(1 for s in samples if not s.ok)
    rps = len(samples) / elapsed_s if elapsed_s > 0 else 0.0
    if not durations:
        return BucketStats(
            name=name, requests=len(samples), errors=errors, req_per_s=rps,
            avg_ms=0, min_ms=0, p50_ms=0, p75_ms=0, p95_ms=0, p99_ms=0, max_ms=0,
        )
    return BucketStats(
        name=name,
        requests=len(samples),
        errors=errors,
        req_per_s=round(rps, 2),
        avg_ms=round(statistics.mean(durations), 1),
        min_ms=round(durations[0], 1),
        p50_ms=round(_quantile(durations, 0.50), 1),
        p75_ms=round(_quantile(durations, 0.75), 1),
        p95_ms=round(_quantile(durations, 0.95), 1),
        p99_ms=round(_quantile(durations, 0.99), 1),
        max_ms=round(durations[-1], 1),
    )


def _build_result(cfg: BenchmarkConfig, samples: list[_Sample], elapsed_s: float) -> BenchmarkResult:
    by_bucket: dict[str, list[_Sample]] = {}
    for s in samples:
        by_bucket.setdefault(s.bucket, []).append(s)

    buckets = [_bucket_stats(name, by_bucket[name], elapsed_s) for name in sorted(by_bucket)]
    aggregate = _bucket_stats("aggregate", samples, elapsed_s)
    status_codes = dict(Counter(str(s.status) for s in samples))

    return BenchmarkResult(
        config=cfg,
        elapsed_s=round(elapsed_s, 2),
        total_requests=len(samples),
        total_errors=sum(1 for s in samples if not s.ok),
        aggregate_rps=aggregate.req_per_s,
        buckets=buckets,
        aggregate=aggregate,
        status_codes=status_codes,
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def _run_job(job: _Job, base_url: str) -> None:
    global _current_job_id
    cfg = job.config
    samples: list[_Sample] = []
    started = time.perf_counter()
    deadline = asyncio.get_event_loop().time() + cfg.duration_s

    progress_task: asyncio.Task | None = None
    cancelled = False
    failure: Exception | None = None

    async def update_progress() -> None:
        while True:
            await asyncio.sleep(0.5)
            job.elapsed_s = round(time.perf_counter() - started, 2)

    try:
        limits = httpx.Limits(
            max_connections=cfg.workers * 2,
            max_keepalive_connections=cfg.workers,
        )
        async with httpx.AsyncClient(base_url=base_url, limits=limits) as client:
            progress_task = asyncio.create_task(update_progress())
            workers = [
                asyncio.create_task(_worker(client, deadline, cfg, samples))
                for _ in range(cfg.workers)
            ]
            try:
                await asyncio.gather(*workers)
            except asyncio.CancelledError:
                cancelled = True
                for w in workers:
                    w.cancel()
                # Drain so we don't leak.
                await asyncio.gather(*workers, return_exceptions=True)
                raise
    except asyncio.CancelledError:
        cancelled = True
    except Exception as e:  # pragma: no cover
        log.exception("benchmark job failed")
        failure = e
    finally:
        if progress_task:
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass

    elapsed = time.perf_counter() - started
    job.elapsed_s = round(elapsed, 2)

    # Always compute partial results from whatever samples we got.
    if samples:
        job.result = _build_result(cfg, samples, elapsed)

    if cancelled:
        job.state = "stopped"
        log.info("benchmark %s stopped after %.1fs (%d samples)",
                 job.job_id, elapsed, len(samples))
    elif failure is not None:
        job.state = "failed"
        job.error = str(failure)
    else:
        job.state = "done"
        if job.result:
            log.info(
                "benchmark %s done: %d reqs / %.1f rps / p50=%.1f p99=%.1f",
                job.job_id, job.result.total_requests, job.result.aggregate_rps,
                job.result.aggregate.p50_ms, job.result.aggregate.p99_ms,
            )

    if _current_job_id == job.job_id:
        _current_job_id = None


def start_job(cfg: BenchmarkConfig, base_url: str = "http://127.0.0.1:8000") -> _Job:
    global _current_job_id
    if any_running():
        raise RuntimeError("a benchmark is already running")
    job = _Job(job_id=uuid.uuid4().hex[:12], config=cfg)
    _jobs[job.job_id] = job
    _current_job_id = job.job_id
    job.task = asyncio.create_task(_run_job(job, base_url=base_url))
    return job


def job_status(job: _Job) -> BenchmarkStatus:
    return BenchmarkStatus(
        job_id=job.job_id,
        state=job.state,
        started_at=job.started_at,
        elapsed_s=job.elapsed_s,
        config=job.config,
        progress_pct=job.progress_pct,
        result=job.result,
        error=job.error,
    )
