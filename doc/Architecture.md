# Lumen — Architecture

> **What this is:** A reference architecture for an e-commerce semantic search
> and product recommendation system on Databricks, built end-to-end on
> **Lakebase Autoscale + pgvector**, fronted by a **Databricks App** (FastAPI
> + React), and deployed entirely from **Terraform**.
>
> **Scale:** ~43K products (WANDS / Wayfair public dataset, MIT license),
> 1024-dim BGE-large embeddings, sub-second p99 at 80+ req/s on 0.5–2 CU.

---

## 1. System overview

Two planes:

- **Data plane** (Lakehouse): ingests raw WANDS CSVs, builds bronze→silver→gold
  Delta tables, and batch-embeds every product using a Databricks-hosted
  foundation model. Lives in Unity Catalog under `classic_stable_89j9qf.lumen_*`.
- **Serving plane** (Lakebase): a Postgres 17 Autoscale instance with
  `pgvector`. A **Synced Table** replicates the gold Delta table into Postgres.
  A materialized view casts the replicated `jsonb` embeddings into `vector(1024)`
  and the HNSW index sits on the MV. Five PL/pgSQL serving functions expose
  search and recommendation as cheap, type-safe SQL calls.

The **Databricks App** runs FastAPI + a built React frontend. It generates
query-time embeddings via Model Serving (BGE-large) and queries Lakebase via a
psycopg3 connection pool that mints a fresh OAuth token per connection.

---

## 2. Architecture diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            DATA PLANE — LAKEHOUSE                            │
│                          (Unity Catalog managed storage)                     │
│                                                                              │
│   github.com/wayfair/WANDS                                                   │
│         │  product.csv  query.csv  label.csv  (TSV, ~43K products)           │
│         ▼                                                                    │
│   ┌─────────────────────────────────────────────┐                            │
│   │ UC Volume: lumen_bronze.lumen_raw           │  ← landed by notebook 01   │
│   └─────────────────────────────────────────────┘                            │
│         │                                                                    │
│         ▼                                                                    │
│   ┌─────────────────────────────────────────────┐                            │
│   │ lumen_bronze.products / queries / labels    │  raw TSV → Delta           │
│   └─────────────────────────────────────────────┘                            │
│         │   notebook 02:  clean, type, normalize column names                │
│         ▼                                                                    │
│   ┌─────────────────────────────────────────────┐                            │
│   │ lumen_silver.products                       │  clean + typed + PK        │
│   └─────────────────────────────────────────────┘                            │
│         │   notebook 02:  concat name|class|hierarchy|desc|features          │
│         ▼                                                                    │
│   ┌─────────────────────────────────────────────┐                            │
│   │ lumen_gold.products                         │  + embedding_text          │
│   │  • PK product_id  • CDF enabled             │  + embedding ARRAY<FLOAT>  │
│   └─────────────────────────────────────────────┘  (initially NULL)          │
│         │   notebook 03:  MERGE … ai_query('databricks-bge-large-en', …)     │
│         │                                                                    │
│         └─────────┬──────────────────────────────────────────────────────┐   │
│                   │                                                      │   │
│                   ▼                                                      ▼   │
│         ┌─────────────────────┐                          ┌──────────────────┐│
│         │ Model Serving       │                          │ Synced Table     ││
│         │ databricks-bge-     │                          │ pipeline         ││
│         │ large-en (1024-dim) │                          │ (TRIGGERED, DLT) ││
│         └─────────────────────┘                          └──────────────────┘│
│                                                                  │           │
└──────────────────────────────────────────────────────────────────┼───────────┘
                                                                   │
                                                                   ▼  (Delta CDF)
┌──────────────────────────────────────────────────────────────────────────────┐
│                       SERVING PLANE — LAKEBASE AUTOSCALE                     │
│             projects/ecommerce-search-demo/branches/production               │
│                           PG 17 · 0.5–2 CU · suspend 7d                      │
│                                                                              │
│   ┌─────────────────────────────────────────────┐                            │
│   │ lumen_gold.products_synced  (read-only)     │  ← Synced Table sink       │
│   │  • embedding stored as jsonb                │  (auto-created by sync)    │
│   └─────────────────────────────────────────────┘                            │
│         │   bootstrap SQL:  embedding::text::vector(1024)                    │
│         ▼                                                                    │
│   ┌─────────────────────────────────────────────┐                            │
│   │ lumen_gold.products_mv  (MATERIALIZED VIEW) │  ← typed for pgvector      │
│   │  • embedding vector(1024)                   │                            │
│   │  • search_vector tsvector                   │                            │
│   │  Indexes:                                   │                            │
│   │    HNSW    on embedding (cosine ops)        │                            │
│   │    GIN     on search_vector                 │                            │
│   │    B-tree  on product_class                 │                            │
│   │    UNIQUE  on product_id (for REFRESH)      │                            │
│   └─────────────────────────────────────────────┘                            │
│         │                                                                    │
│         ▼                                                                    │
│   ┌─────────────────────────────────────────────┐                            │
│   │ Serving functions (public schema)           │                            │
│   │  • search_products_semantic(vec, class?, n) │                            │
│   │  • search_products_hybrid(text, vec, …)     │  RRF combine vec + FTS     │
│   │  • recommend_similar_products(id, n, same?) │                            │
│   │  • list_product_classes(n)                  │  facet counts              │
│   │  • get_product(id)                          │                            │
│   └─────────────────────────────────────────────┘                            │
│                                                                              │
│   Roles & grants:                                                            │
│    • rafael-arana (USER, DATABRICKS_SUPERUSER) — owns objects                │
│    • dbrx-apps-<sp-uuid> (SERVICE_PRINCIPAL, no createdb/role/bypassrls)     │
│      ↳ EXECUTE on the 5 serving functions, SELECT on lumen_gold.*            │
└──────────────────────────────────────────────────────────────────────────────┘
                                                                   ▲
                                                  psycopg3 pool    │ OAuth token
                                                  port 5432, SSL   │ (per-connection refresh)
                                                                   │
┌──────────────────────────────────────────────────────────────────┴───────────┐
│                           DATABRICKS APP — "lumen-recommender"               │
│                          MEDIUM compute · auto-created SP                    │
│                                                                              │
│   FastAPI (Python 3.11)              │      React + Vite + Tailwind (Lumen)  │
│   ────────────────────────────       │      ───────────────────────────────  │
│    GET  /api/healthz                 │      Search page  · grid · facets     │
│    GET  /api/classes                 │      PDP          · similar products  │
│    POST /api/search?mode=…           │      Latency badge (embed / db / total)│
│    GET  /api/product/{id}            │                                       │
│    GET  /api/product/{id}/similar    │      Served as static from FastAPI    │
│                                                                              │
│   ┌─────────────┐    ┌─────────────────────────┐   ┌──────────────────────┐  │
│   │ embed.py    │───▶│ Model Serving           │   │ lakebase.py          │  │
│   │ /v1/...embed│    │ databricks-bge-large-en │   │ psycopg3 pool        │  │
│   └─────────────┘    └─────────────────────────┘   │ OAuthConnection      │  │
│                                                    │ register_vector      │  │
│                                                    └──────────────────────┘  │
│                                                                              │
│   Resources declared in app.tf →  postgres { branch, database, CONNECT }     │
│                                   serving_endpoint { CAN_QUERY }             │
│                                                                              │
│   The App's auto-created SP gets a Postgres role auto-created for it on the  │
│   branch (role_id = "dbrx-apps-<sp-uuid>"). GRANTs are applied in the        │
│   bootstrap SQL step by scripts/run_lakebase_sql.py.                         │
└──────────────────────────────────────────────────────────────────────────────┘
                                                                   ▲
                                                                   │ HTTPS + OAuth
                                                                   │
┌──────────────────────────────────────────────────────────────────┴───────────┐
│                          USER / LOAD TEST (Rust + goose)                     │
│                                                                              │
│   Browser → https://lumen-recommender-<workspace-id>.azure.databricksapps.com│
│   Load test → 100 WANDS-style queries × 20 users × 2 min = 10K reqs / 0 errs │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Mermaid view (rendered in GitHub)

```mermaid
flowchart LR
    subgraph Lakehouse
        W[(WANDS CSVs)] --> V[UC Volume<br/>lumen_bronze.lumen_raw]
        V --> B[Bronze Delta<br/>lumen_bronze.products]
        B --> S[Silver Delta<br/>lumen_silver.products]
        S --> G[Gold Delta<br/>lumen_gold.products<br/>+ embedding_text]
        G -- ai_query --> MS[Model Serving<br/>databricks-bge-large-en<br/>1024-dim]
        MS --> G
    end
    G -- TRIGGERED sync --> ST[Synced Table<br/>lumen_gold.products_synced<br/>embedding as jsonb]
    subgraph Lakebase[Lakebase Autoscale · PG17 · 0.5–2 CU]
        ST -- cast jsonb->vector --> MV[Materialized View<br/>lumen_gold.products_mv<br/>HNSW + GIN]
        MV --> FN[PL/pgSQL serving fns<br/>semantic / hybrid / similar]
    end
    subgraph App[Databricks App]
        API[FastAPI<br/>/api/search · /api/similar]
        UI[React UI]
        EM[embed.py] --> MS2[Model Serving<br/>BGE-large]
        API --> EM
        API -- psycopg3 pool + OAuth --> FN
        UI --> API
    end
    USER([User / load test]) -- HTTPS OAuth --> UI
```

---

## 3. Data plane (Lakehouse)

### 3.1 Source

[WANDS](https://github.com/wayfair/WANDS) — Wayfair's public product search
relevance benchmark, MIT-licensed:

| File | Rows | Schema |
|---|---:|---|
| `product.csv` | 42,994 | `product_id`, `product_name`, `product_class`, `category_hierarchy`, `product_description`, `product_features`, `rating_count`, `average_rating`, `review_count` |
| `query.csv` | 480 | `query_id`, `query`, `query_class` |
| `label.csv` | 233,448 | `id`, `query_id`, `product_id`, `label` (Exact / Partial / Irrelevant) |

The pipeline today only uses `product.csv`; the labels can power evaluation
(NDCG@k / recall@k) later.

### 3.2 Medallion layout

All in catalog `classic_stable_89j9qf` (the workspace's default-storage UC
catalog — we chose this over creating a new catalog to avoid the Default
Storage / provider compatibility issue).

| Layer | Schema | Tables | Notes |
|---|---|---|---|
| **Raw** | — | UC Volume `lumen_bronze.lumen_raw` | WANDS CSVs |
| **Bronze** | `lumen_bronze` | `products`, `queries`, `labels` | TSV → Delta, headers normalized (space→underscore) |
| **Silver** | `lumen_silver` | `products` | Typed, trimmed, PK = `product_id` |
| **Gold** | `lumen_gold` | `products` | + `embedding_text` (concat) + `embedding ARRAY<FLOAT>` (1024-dim) + CDF enabled |

### 3.3 Embedding strategy

`embedding_text` (the input to BGE-large) concatenates the five most signal-rich
WANDS fields with a separator:

```sql
concat_ws(' | ',
  nullif(product_name,        ''),
  nullif(product_class,       ''),
  nullif(category_hierarchy,  ''),
  nullif(product_description, ''),
  nullif(product_features,    '')
)
```

This is intentionally richer than the [databricks-industry-solutions/product-search](https://github.com/databricks-industry-solutions/product-search)
reference accelerator, which embeds description-only. Adding class, hierarchy,
and features improves recall on short, structured queries like *"comfy reading
chair for small living room"* — note in the load test it returned all three
hits as `Accent Chairs`.

### 3.4 Batch embedding

Notebook `03_embed_catalog.py` does an idempotent **incremental MERGE**:

```sql
MERGE INTO lumen_gold.products t
USING (
  SELECT product_id,
         CAST(ai_query('databricks-bge-large-en', embedding_text) AS ARRAY<FLOAT>) AS new_embedding
  FROM lumen_gold.products
  WHERE embedding IS NULL
) s
ON t.product_id = s.product_id
WHEN MATCHED THEN UPDATE SET t.embedding = s.new_embedding
```

`ai_query` is the SQL/DataFrame primitive for calling any Model Serving
endpoint (foundation models or custom) directly from Spark. For 43K rows on a
2-worker `Standard_D4ds_v5` cluster, this takes ~3–5 minutes.

### 3.5 Job orchestration

A single **Lakeflow Job** (Terraform `databricks_job.ingest_and_embed`)
chains four notebook tasks:

```
setup → load_wands → silver_gold → embed_catalog
```

Each task runs on a shared `small` job cluster (2 workers, single-user mode).
Terraform triggers it once on apply via `terraform_data.run_ingest_job` and
blocks until completion using `databricks jobs run-now --timeout 60m` (the CLI
is synchronous by default).

---

## 4. Serving plane (Lakebase Autoscale)

### 4.1 Project / branch / endpoint

| Resource | Value |
|---|---|
| Project | `projects/ecommerce-search-demo` |
| Branch | `production` (`is_protected = true`, `no_expiry = true`) |
| Endpoint | `primary` (`ENDPOINT_TYPE_READ_WRITE`) |
| PG version | **17** |
| Autoscale | `autoscaling_limit_min_cu = 0.5`, `max_cu = 2.0` |
| Suspend | `suspend_timeout_duration = "604800s"` (7 days — effectively always-on for the demo) |
| DNS | `ep-muddy-math-e154i90y.database.eastus2.azuredatabricks.net` |

**Autoscale signals to grep for** (vs. the Provisioned product):

- ✅ Terraform resource family: `databricks_postgres_*`
- ✅ Numeric `autoscaling_limit_min_cu`/`max_cu` (NOT the `CU_n` enum)
- ✅ Resource name format `projects/.../branches/.../endpoints/...`
- ✅ `suspend_timeout_duration` field present
- ❌ NOT `databricks_database_instance` with `capacity = "CU_1"` (that's Provisioned)

On Autoscale, 1 CU ≈ 2 GB RAM. The 0.5–2 CU range gives ~1–4 GB working memory
which is far more than enough for 43K × 1024-dim float embeddings (~170 MB
raw, ~300 MB with HNSW overhead).

### 4.2 Logical database & roles

- Database: `appdb` (owned by `rafael-arana`, the apply-time superuser)
- Auto-created PG role for the apply-time user: `rafael-arana`
  - `identity_type = USER`, `bypassrls`, `createdb`, `createrole`, `DATABRICKS_SUPERUSER`
- Auto-created PG role for the App's SP: `dbrx-apps-3c33a1f0-…`
  - `identity_type = SERVICE_PRINCIPAL`, `auth_method = LAKEBASE_OAUTH_V1`
  - No createdb / createrole / bypassrls — least privilege

Both roles are **auto-provisioned** the first time their identity touches the
branch — Terraform doesn't (and shouldn't) try to recreate them. GRANTs are
applied via SQL (see §4.5).

### 4.3 Synced Table

```hcl
resource "databricks_postgres_synced_table" "products" {
  synced_table_id = "classic_stable_89j9qf.lumen_gold.products_synced"
  spec = {
    branch                             = "projects/.../branches/production"
    postgres_database                  = "appdb"
    source_table_full_name             = "classic_stable_89j9qf.lumen_gold.products"
    primary_key_columns                = ["product_id"]
    scheduling_policy                  = "TRIGGERED"
    create_database_objects_if_missing = true
    new_pipeline_spec = {
      storage_catalog = "classic_stable_89j9qf"
      storage_schema  = "lumen_gold"
    }
  }
}
```

Mode: **TRIGGERED** (manual refresh). The other options are `SNAPSHOT` (one-off)
and `CONTINUOUS` (always-on, more expensive). For a static demo catalog,
TRIGGERED is the cheapest mode and re-runs in seconds via the Pipelines API
when the source Delta changes.

Behind the scenes, the Synced Table is a Lakeflow Declarative Pipeline that
reads the Delta CDF and writes to Postgres. The destination table in
Lakebase is `lumen_gold.products_synced` (the schema name mirrors the UC source).

**Important gotcha:** Synced Tables map Delta `ARRAY<FLOAT>` to Postgres
`jsonb`, not `vector(N)`. That's why we need the materialized view layer.

### 4.4 Materialized view (the jsonb→vector bridge)

```sql
CREATE MATERIALIZED VIEW lumen_gold.products_mv AS
SELECT
    product_id, product_name, product_class, category_hierarchy,
    product_description, product_features,
    average_rating, review_count,
    embedding::text::vector(1024) AS embedding,
    to_tsvector('english',
        coalesce(product_name, '')        || ' ' ||
        coalesce(product_description, '') || ' ' ||
        coalesce(product_class, '')
    ) AS search_vector
FROM lumen_gold.products_synced
WHERE embedding IS NOT NULL;
```

Indexes on the MV:

| Index | Type | Purpose |
|---|---|---|
| `idx_products_mv_pk` | UNIQUE B-tree on `product_id` | Enables `REFRESH MATERIALIZED VIEW CONCURRENTLY` |
| `idx_products_mv_embedding` | **HNSW** with `vector_cosine_ops`, `m=16`, `ef_construction=200` | Approximate nearest neighbor (vector search) |
| `idx_products_mv_class` | B-tree on `product_class` | Pre-filter facet |
| `idx_products_mv_fts` | GIN on `search_vector` | Full-text search for hybrid mode |

HNSW is the right choice for this catalog size; IVFFlat starts paying off
only above ~1M vectors.

`REFRESH MATERIALIZED VIEW` requires a Lakebase-internal function that the
apply-time user can't EXECUTE, so refreshes today require a privileged role.
For this demo the initial `CREATE` populates the view and the data is static —
not a concern. For dynamic catalogs, the refresh would run as a privileged
service-principal job on the branch.

### 4.5 Serving functions

Five PL/pgSQL functions in `public` (the App SP only ever calls these, never
touches tables directly):

| Function | Signature | What it does |
|---|---|---|
| `search_products_semantic` | `(vector(1024), text class?, int n)` | ANN over MV, optional class pre-filter |
| `search_products_hybrid` | `(text q, vector(1024), text class?, int n, float vw=0.7, float tw=0.3)` | Vector + FTS, combined via Reciprocal Rank Fusion |
| `recommend_similar_products` | `(int product_id, int n, bool same_class?)` | Read source embedding → ANN |
| `list_product_classes` | `(int n)` | Top-N class facet counts (for UI dropdown) |
| `get_product` | `(int product_id)` | Single-row lookup with description + features |

All declared `STABLE` so the planner can cache calls within a transaction.

Hybrid search uses **Reciprocal Rank Fusion** to combine vector-rank and
FTS-rank into a single score:

```
rrf_score = vw / (60 + vec_rank) + tw / (60 + text_rank)
```

with `vw = 0.7` and `tw = 0.3` by default (favors semantic over keyword,
appropriate for embedding-quality queries).

### 4.6 GRANTs (least-privilege)

```sql
GRANT CONNECT ON DATABASE appdb               TO "<app-sp-uuid>";
GRANT USAGE   ON SCHEMA public                TO "<app-sp-uuid>";
GRANT USAGE   ON SCHEMA lumen_gold            TO "<app-sp-uuid>";
GRANT SELECT  ON ALL TABLES IN SCHEMA lumen_gold TO "<app-sp-uuid>";

-- One GRANT per function. Cannot use `ALL FUNCTIONS IN SCHEMA public`
-- because Lakebase exposes system functions (e.g. neon_emit_reverse_etl_commit)
-- in `public` that we don't own and can't re-grant.
GRANT EXECUTE ON FUNCTION search_products_semantic(vector, text, int)                   TO "<app-sp-uuid>";
GRANT EXECUTE ON FUNCTION search_products_hybrid(text, vector, text, int, float, float) TO "<app-sp-uuid>";
GRANT EXECUTE ON FUNCTION recommend_similar_products(int, int, boolean)                 TO "<app-sp-uuid>";
GRANT EXECUTE ON FUNCTION list_product_classes(int)                                     TO "<app-sp-uuid>";
GRANT EXECUTE ON FUNCTION get_product(int)                                              TO "<app-sp-uuid>";
```

The App SP role can call the five functions and read the synced data — and
nothing else.

---

## 5. The Databricks App

### 5.1 Stack

- **Backend:** FastAPI on Python 3.11, served by `uvicorn` on port 8000
- **Frontend:** React 18 + Vite + Tailwind, built to static assets and served
  by FastAPI (`StaticFiles` mount + SPA fallback)
- **Compute:** `MEDIUM` (1 vCPU / 4 GB)
- **Auth:** Databricks workspace OAuth at the edge (every request authenticated
  by Databricks before reaching uvicorn)

### 5.2 Resources injected

Declared in `terraform/app.tf`:

```hcl
resources = [
  { name = "lakebase",
    postgres = { branch = "...", database = "...", permission = "CAN_CONNECT_AND_CREATE" } },
  { name = "embedding_endpoint",
    serving_endpoint = { name = "databricks-bge-large-en", permission = "CAN_QUERY" } },
]
```

When the App is created, Databricks Apps:

1. Mints an OAuth service principal for the app
2. Wires the App's SP into the named Lakebase branch (so the SP can mint
   short-lived OAuth tokens for the endpoint)
3. Grants the App's SP `CAN_QUERY` on the Model Serving endpoint

### 5.3 Token rotation (psycopg3 + OAuth)

`backend/lakebase.py` subclasses `psycopg.Connection` so every new connection
out of the pool refreshes the OAuth token:

```python
class OAuthConnection(psycopg.Connection):
    @classmethod
    def connect(cls, conninfo="", **kwargs):
        cred = _workspace.api_client.do(
            "POST",
            "/api/2.0/postgres/credentials",
            body={"endpoint": settings.LAKEBASE_ENDPOINT},
        )
        kwargs["password"] = cred["token"]
        return super().connect(conninfo, **kwargs)
```

The pool size is min=1, max=10. Each connection lives until idle-timeout or
token-expiry (~1 hour); refreshes happen transparently on the next checkout.

`register_vector(conn)` is called on each new connection so psycopg encodes
Python lists of floats as `vector(N)` correctly — note we still pass
`%s::vector(1024)` casts in the SQL to be explicit (the pgvector type adapter
sends `double precision[]` otherwise, which the functions can't accept).

### 5.4 API surface

| Endpoint | Description |
|---|---|
| `GET  /api/healthz` | Liveness check |
| `GET  /api/classes` | Facet counts for the UI dropdown |
| `POST /api/search` | Body: `{q, mode: semantic\|hybrid, product_class?, limit}` → returns hits + per-stage latency (`embed_ms`, `db_ms`, `total_ms`) |
| `GET  /api/product/{id}` | Single product detail |
| `GET  /api/product/{id}/similar` | Similar products via embedding cosine |

The latency breakdown returned with every search response is what powers the
"embed / db / total" badge in the UI — useful for live demos.

---

## 6. Databricks components used

### 6.1 Data layer

| Component | Use | Resource |
|---|---|---|
| **Unity Catalog** | Catalog, schemas, volumes, tables, governance | `databricks_catalog` (data source), `databricks_schema`, `databricks_volume` |
| **Delta Lake** | Storage format for bronze/silver/gold | implicit via `saveAsTable` / `CREATE TABLE` |
| **Change Data Feed** | Source for the Synced Table pipeline | `ALTER TABLE … SET TBLPROPERTIES (delta.enableChangeDataFeed = true)` |
| **Lakeflow Jobs** | Multi-task orchestration of the ingest+embed pipeline | `databricks_job` with 4 notebook tasks |
| **`ai_query`** | SQL/DataFrame entry point to Model Serving | inline in notebook 03 |
| **Model Serving (foundation)** | BGE-large endpoint for embeddings (batch + query-time) | `databricks-bge-large-en` (pre-existing, 1024-dim) |

### 6.2 Serving layer

| Component | Use | Resource |
|---|---|---|
| **Lakebase Autoscale** | OLTP Postgres for low-latency serving | `databricks_postgres_project`, `_branch`, `_endpoint`, `_database` |
| **Synced Tables** | Continuous/triggered Delta → Postgres replication | `databricks_postgres_synced_table` |
| **pgvector** | Vector similarity in Postgres | `CREATE EXTENSION vector` in bootstrap SQL |
| **databricks_auth (PG extension)** | OAuth token auth flow inside the database | `CREATE EXTENSION databricks_auth` |
| **pg_stat_statements** | Query observability | `CREATE EXTENSION pg_stat_statements` |

### 6.3 Application layer

| Component | Use | Resource |
|---|---|---|
| **Databricks Apps** | Runtime for the FastAPI + React app | `databricks_app` with `postgres` + `serving_endpoint` resources |
| **Service Principals** | App identity; auto-managed by Apps | `databricks_app.service_principal_client_id` (computed) |
| **Postgres Roles** | Identity inside Lakebase | auto-created on first access; referenced as `dbrx-apps-<sp-uuid>` |

### 6.4 Infra-as-code

| Component | Use |
|---|---|
| **Databricks Terraform provider** | Sole source of infrastructure truth — every resource above is declarative |
| **`terraform_data` + `local-exec`** | Procedural glue for: triggering the job, running bootstrap SQL via psycopg, staging+uploading App source, deploying the App |
| **Databricks CLI** | Used inside `local-exec` blocks for: `jobs run-now`, `workspace import-dir`, `apps deploy` |

---

## 7. Authentication & authorization

Three identities and three credential flows:

```
   Apply-time user (you)                       App SP (auto)                 End user (browser)
   ─────────────────────                       ─────────────                 ───────────────────
   • Workspace admin                           • Created on app creation     • Workspace OAuth
   • PG superuser (auto-role)                  • PG role auto-created        • Edge auth on the
   • Used by terraform apply                   • Used by FastAPI runtime       App URL
   • OAuth from local CLI profile              • OAuth via Databricks Apps   • Token forwarded by
                                                 injected env vars             Apps to backend
                                                 (DATABRICKS_CLIENT_ID/SECRET)
```

**Apply-time flow** (just creates resources; runs SQL once):

```
~/.databrickscfg [azure-video]
    └─ OAuth token →  Databricks REST API  →  creates project/branch/endpoint/db/app
                                          →  Lakebase /api/2.0/postgres/credentials
                                          →  psycopg connect as rafael.arana@databricks.com
                                          →  CREATE EXTENSION / MV / FUNCTIONS / GRANTS
```

**App runtime flow** (every request):

```
Browser → Databricks Apps edge auth (OAuth)
       → uvicorn (App SP context, env: DATABRICKS_CLIENT_ID/SECRET)
       → embed.py        ┐
                         ├─ Model Serving query  →  BGE-large endpoint
       → lakebase.py     ┘
            ↓
       psycopg3 ConnectionPool
            ↓ (on each new conn)
       POST /api/2.0/postgres/credentials  →  short-lived PG token
            ↓
       PG connect (SSL, user=<app-sp-uuid>, password=token)
            ↓
       cur.execute("SELECT * FROM search_products_semantic(%s::vector(1024), …)")
            ↓
       HNSW lookup over products_mv  →  result rows  →  JSON response
```

Tokens are short-lived (1 hour). The pool fetches a fresh one each time
a new connection is opened (cheap; ~10 ms) — there's never a long-lived
secret stored anywhere.

---

## 8. Data flow walk-throughs

### 8.1 Build-time: WANDS → embedded gold

(One-shot, triggered by `terraform apply` via `terraform_data.run_ingest_job`)

1. `00_setup` creates `lumen_bronze`, `lumen_silver`, `lumen_gold` schemas
   and the `lumen_raw` volume in UC.
2. `01_load_wands` shells out to `git clone wayfair/WANDS`, copies the three
   CSVs into the volume, reads them with `sep="\t"`, normalizes column names
   (`category hierarchy` → `category_hierarchy`), writes to `lumen_bronze.{products,queries,labels}`.
3. `02_silver_gold` casts types, dedups, registers PK on `product_id`, builds
   `embedding_text`, enables CDF on the gold table.
4. `03_embed_catalog` MERGEs `ai_query('databricks-bge-large-en', embedding_text)`
   into the `embedding` column. Idempotent — only embeds NULL rows.
5. Sync to Postgres is automatic from this point: the `databricks_postgres_synced_table`
   resource manages a DLT pipeline that reads the Delta CDF and writes to
   `lumen_gold.products_synced` in Lakebase.
6. The bootstrap SQL step (`terraform_data.bootstrap_lakebase_sql`) creates the
   materialized view, builds HNSW + GIN + B-tree indexes, defines the 5
   serving functions, and grants the App SP `EXECUTE` on each.

### 8.2 Search request (semantic mode)

End-to-end latency budget for `POST /api/search` (from the 2-min load test):

```
User → App edge (HTTPS + workspace OAuth)               ~30  ms  RTT to Azure East US 2
App edge → FastAPI                                       ~2  ms
FastAPI → Model Serving (embed_query)                   ~50–250 ms  ← dominant
                                                                       BGE-large p99 ~250ms cold,
                                                                       ~50–80ms warm
FastAPI → Lakebase                                       ~5  ms  connection acquire from pool
                                                                  (or +10ms if pool refill needed)
Lakebase HNSW + class filter + function exec            ~5–50 ms   ← cheap
FastAPI ← Lakebase result rows                           ~2  ms
FastAPI → User (JSON)                                    ~30 ms RTT
────────────────────────────────────────────────────────────────
Total p50: ~230 ms · p99: ~500 ms (observed)
```

### 8.3 Similar-products request

`GET /api/product/{id}/similar?limit=8` — slightly faster than search because
there's no embedding call:

```
PG: recommend_similar_products(id, limit, same_class):
    1. fetch source embedding by PK    (~1 ms, B-tree index)
    2. HNSW ANN with class filter      (~5–20 ms)
    3. return rows excluding source PK
```

Total round-trip from the load test environment: ~120 ms p50.

---

## 9. Performance characteristics (observed)

From the 2-minute load test (20 concurrent users, 70/30 semantic/hybrid mix):

| Metric | Aggregate | semantic | hybrid |
|---|---:|---:|---:|
| **Requests** | 10,130 | 7,772 | 2,358 |
| **Throughput (req/s)** | 81.69 | 62.68 | 19.02 |
| **Errors** | 0 (0%) | 0 | 0 |
| **p50 (ms)** | 230 | 230 | 230 |
| **p75 (ms)** | 250 | 250 | 250 |
| **p98 (ms)** | 440 | 440 | 460 |
| **p99 (ms)** | 500 | 490 | 600 |
| **p99.9 (ms)** | 1000 | 1000 | 1000 |
| **max (ms)** | 1684 | 1551 | 1684 |

Notes:

- Median rock-steady at 230 ms across all 10,130 requests — Lakebase autoscale
  + connection pool absorbed load with no warmup tail.
- The bottleneck is Model Serving (BGE-large), not pgvector. Lakebase HNSW
  resolves in ~5–20 ms even cold.
- Hybrid is ~100 ms slower at p99 — expected since it runs vector ANN + FTS
  + RRF combine, ~3× the work.
- We never crossed 1 CU's stated capacity (1.7K–20K point-gets/sec per CU
  depending on cache). The 0.5 → 2 CU autoscale never had to engage.

---

## 10. Operational notes

### 10.1 Recreating from scratch

```bash
cd terraform
terraform apply
```

This is the only command needed. It:

1. Creates UC schemas + volume in `classic_stable_89j9qf`
2. Uploads 4 notebooks
3. Creates the ingest+embed job and triggers it (waits to completion, ~10 min)
4. Creates Lakebase Autoscale project + branch + endpoint + database
5. Creates the Databricks App + auto-creates its service principal
6. Triggers the Synced Table to replicate gold → Postgres
7. Builds & uploads the React frontend + Python backend to `/Workspace/Apps/lumen-recommender`
8. Runs bootstrap SQL (extensions, MV, indexes, functions, grants)
9. Deploys the app — returns when state = `SUCCEEDED`

### 10.2 Tear-down

```bash
terraform destroy
```

Drops the App, the Synced Table pipeline, the Lakebase project (and all
branches/endpoints/databases/roles inside it), the job, the notebooks, the
schemas, and the volume. Catalog `classic_stable_89j9qf` is preserved (we
referenced it via `data` block, not as a managed resource).

### 10.3 Refreshing data

Three change scenarios:

| Change | Action |
|---|---|
| Add/update products in the Delta gold table | Re-run the embed task (or the whole job); Synced Table picks up CDF automatically |
| Rebuild embeddings (e.g. new model) | TRUNCATE the `embedding` column, re-run `03_embed_catalog` |
| Just change app code (frontend or backend) | `terraform apply` — the upload-and-deploy provisioners detect file hash changes and re-deploy |

The synced table is TRIGGERED — to force an immediate refresh, hit the
DLT pipeline directly via the Pipelines REST API (UI: pipeline → "Run").

### 10.4 Cost (rough order of magnitude)

| Item | Driver | Estimate |
|---|---|---|
| Lakebase Autoscale 0.5–2 CU, no scale-to-zero | always-on | ~$3.5K–$7K / year |
| Model Serving (BGE-large) | pay-per-token, batch + query | dominated by batch (one-time ~few cents for 43K) + ongoing query (cheap) |
| Databricks App MEDIUM | per-hour app compute | ~$30 / day if always-on |
| UC storage | tiny — 43K rows ~50 MB | negligible |
| Job cluster (one-shot ingest) | 2× Standard_D4ds_v5 for ~10 min | ~$0.50 per run |

For a customer-facing e-commerce search backend at this scale, the validation
doc's claim of $3.5K–$7K/year for the serving layer holds.

### 10.5 Things we know are imperfect

| Thing | Why it's fine for now | What you'd do for prod |
|---|---|---|
| `REFRESH MATERIALIZED VIEW` needs privileged role | Demo data is static | Run refresh via a privileged SP, scheduled |
| Schemas live in a shared workspace catalog (`classic_stable_89j9qf`) | Avoids the Default-Storage / Terraform-provider gap | Provision a dedicated catalog with explicit `storage_root` |
| App auth is workspace-OAuth only (anyone in the workspace can hit the app) | Internal demo | Add finer-grained authz (group membership check, or an audience-bound JWT) |
| Hybrid weights are hardcoded (0.7 vec / 0.3 text) | Sensible defaults | Make them per-customer or tunable via query string |
| No A/B / eval pipeline using WANDS labels yet | Out of scope for the demo | Plug labels into a notebook that computes NDCG@10 / recall@k per mode |

---

## 11. File layout

```
product_recommender/
├── terraform/                          # ← single source of truth
│   ├── versions.tf                     # databricks provider >= 1.50
│   ├── providers.tf                    # azure-video profile
│   ├── variables.tf                    # tunables (CU min/max, suspend, etc.)
│   ├── catalog.tf                      # UC schemas + volume (catalog via data source)
│   ├── notebooks.tf                    # 4 databricks_notebook resources
│   ├── jobs.tf                         # ingest+embed Lakeflow job
│   ├── lakebase.tf                     # postgres_project + branch + endpoint + database
│   ├── app.tf                          # databricks_app + postgres/serving_endpoint resources
│   ├── role.tf                         # local for the App SP's auto-created PG role name
│   ├── synced_table.tf                 # gold → Postgres replication
│   ├── bootstrap.tf                    # terraform_data: run job, run SQL, upload+deploy app
│   └── outputs.tf                      # app_url, lakebase_endpoint, etc.
│
├── notebooks/                          # 4 Spark notebooks + 1 SQL bootstrap
│   ├── 00_setup.py
│   ├── 01_load_wands.py                # WANDS clone + bronze
│   ├── 02_silver_gold.py               # cleanup + embedding_text + PK + CDF
│   ├── 03_embed_catalog.py             # ai_query('databricks-bge-large-en', …) MERGE
│   └── 04_lakebase_bootstrap.sql       # extensions + MV + HNSW + functions
│
├── scripts/
│   └── run_lakebase_sql.py             # OAuth + psycopg helper for bootstrap SQL
│
├── app/                                # Databricks App source
│   ├── app.yaml                        # uvicorn command + env vars
│   ├── requirements.txt
│   ├── backend/                        # FastAPI
│   │   ├── main.py                     # /api routes
│   │   ├── lakebase.py                 # psycopg3 OAuthConnection + pool
│   │   ├── embed.py                    # BGE-large via Model Serving
│   │   └── settings.py
│   └── frontend/                       # Vite + React + Tailwind, dark "Lumen" theme
│       ├── src/{App.tsx, pages/, components/, lib/api.ts}
│       └── ... (package.json, tailwind/vite/ts configs)
│
├── loadtest/                           # Rust + Goose load tester
│   ├── Cargo.toml
│   ├── README.md
│   └── src/
│       ├── main.rs                     # Goose scenario, 70/30 mode mix
│       └── queries.rs                  # 100 WANDS-style queries
│
└── doc/
    ├── Lakebase_Validacion_Tecnica_ECommerce.md   # the original validation doc
    └── Architecture.md                            # this file
```

---

## 12. Key references

- [Lakebase Autoscale docs](https://docs.databricks.com/aws/en/oltp/projects/about)
- [Manage computes (CU sizing)](https://docs.databricks.com/aws/en/oltp/projects/manage-computes)
- [Connect external apps to Lakebase](https://docs.databricks.com/aws/en/oltp/projects/external-apps-connect)
- [Terraform `databricks_postgres_project`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/postgres_project) (+ `_branch`, `_endpoint`, `_database`, `_role`, `_synced_table`)
- [Terraform `databricks_app`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/app)
- [Databricks Apps overview](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/)
- [AI Functions (`ai_query`)](https://docs.databricks.com/aws/en/large-language-models/ai-functions)
- [WANDS dataset (Wayfair, MIT)](https://github.com/wayfair/WANDS)
- [Databricks product-search accelerator](https://github.com/databricks-industry-solutions/product-search) (reference for the embedding-text strategy)
- [pgvector HNSW](https://github.com/pgvector/pgvector#hnsw)
- [Goose load testing framework](https://book.goose.rs)
