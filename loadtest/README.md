# Lumen Load Test

A Rust load-test driver for the deployed Lumen app, using
[**Goose**](https://book.goose.rs) (async Rust load-testing framework, inspired
by Locust). Goose handles concurrency, ramp-up, run time, and reports full
latency percentiles + throughput out of the box — we just declare the
transaction.

## What it does

- Picks one of **100 WANDS-style queries** at random (`src/queries.rs`)
- Routes 70% to `mode=semantic`, 30% to `mode=hybrid` — tracked separately
- POSTs to `/api/search` on the running app
- Reports per-mode and aggregated **req/s, mean/median/p75/p95/p98/p99/p99.9/max**,
  HTTP status code mix, errors

## Build

```bash
cargo build --release
```

## Auth

The app sits behind Databricks workspace OAuth. Export a bearer token before
each run (tokens last ~1 hour):

```bash
export LUMEN_TOKEN=$(databricks auth token --profile azure-video \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
```

## Run

A 5-minute, 20-user test with HTML report and per-request log:

```bash
./target/release/lumen-loadtest \
  --host https://lumen-recommender-7405604561430667.7.azure.databricksapps.com \
  -u 20 \
  -r 5 \
  -t 5m \
  --no-reset-metrics \
  --report-file report.html \
  --request-log requests.jsonl
```

### Flags worth knowing

| Flag | Meaning |
|---|---|
| `-u N` | Concurrent users |
| `-r N` | Users spawned per second during ramp-up |
| `-t <time>` | Run duration, e.g. `30s`, `5m`, `1h` |
| `--no-reset-metrics` | Keep ramp-up samples in the final report (default discards them) |
| `--report-file <path>` | Write a self-contained HTML report |
| `--request-log <path>` | Per-request JSONL log (one line per request) |
| `--throttle-requests <N>` | Cap aggregate rate at N req/s |

Full list: `./target/release/lumen-loadtest -h`.

## Sample output

```
=== PER REQUEST METRICS ===
 Name                     |   # reqs |  # fails | req/s | fail/s
 POST search:hybrid       |      104 |   0 (0%) |  3.35 |   0.00
 POST search:semantic     |      399 |   0 (0%) | 12.87 |   0.00
 Aggregated               |      503 |   0 (0%) | 16.23 |   0.00

 Slowest page load within specified percentile of requests (ms):
 Name                     |   50% |   75% |   98% |   99% | 99.9% |
 POST search:hybrid       |   260 |   290 |   900 | 1,000 | 2,541 |
 POST search:semantic     |   220 |   270 |   800 | 1,000 | 2,000 |
 Aggregated               |   230 |   280 |   800 | 1,000 | 2,000 |
```

## Tuning the mix

- **More users**: `-u 50`. Watch Lakebase autoscale up from `0.5 CU` toward `2 CU`
  if requests/sec exceed what one CU handles (~1k–5k QPS depending on cache).
- **Pure semantic**: edit `SEMANTIC_WEIGHT` in `src/main.rs` to `100`.
- **Different queries**: append to `src/queries.rs`; recompile.
- **Rate-limit**: `--throttle-requests 50` caps the test at 50 req/s for a
  controlled SLO check.
