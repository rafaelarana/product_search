# Lumen — Setup on a fresh workspace

End-to-end setup: prerequisites, the exact dependency/build order, and a single
script (`scripts/setup.sh`, uv-based) that runs it. For the system design see
[`Architecture.md`](./Architecture.md); for search internals see
[`Search.md`](./Search.md).

## Table of contents

- [What gets built](#what-gets-built)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Build order & dependencies](#build-order--dependencies)
- [Manual steps (script equivalent)](#manual-steps-script-equivalent)
- [Optional: eval harness & load test](#optional-eval-harness--load-test)
- [Verify](#verify)
- [Troubleshooting](#troubleshooting)
- [Tear down](#tear-down)

---

## What gets built

A single `terraform apply` provisions everything in order: UC schemas + volume,
4 notebooks, the ingest+embed **job** (run to completion), a **Lakebase
Autoscale** project/branch/endpoint/database, the **Databricks App** (+ its
service principal and Postgres role), the **Synced Table**, the **bootstrap
SQL** (pgvector/indexes/functions/grants), and finally the **frontend build +
app deploy**. The result is a running search demo at `terraform output app_url`.

---

## Prerequisites

### Local tools

| Tool | Min version | Why | Install |
|---|---|---|---|
| **Databricks CLI** | 1.0.0 | auth profile, run job, deploy app | <https://docs.databricks.com/dev-tools/cli/install.html> |
| **Terraform** | ≥ 1.6.0 | all infra (`terraform/`) | <https://developer.hashicorp.com/terraform/install> |
| **uv** | recent | create the Python venv the bootstrap step uses | <https://docs.astral.sh/uv/> |
| **Python** | 3.10+ | `scripts/run_lakebase_sql.py` (via the venv) | bundled / uv-managed |
| **Node + npm** | Node 18+ | Terraform runs `npm install && npm run build` for the frontend | <https://nodejs.org> |
| Rust / cargo | — | *optional* — only for the `loadtest/` Goose load test | <https://rustup.rs> |

`psql` is **not** required (the scripts use psycopg).

### Workspace requirements

- A **Databricks workspace** with a CLI profile you can authenticate (OAuth U2M
  via `databricks auth login`). Default profile name: `azure-video`.
- An **existing Unity Catalog catalog** (`catalog_name`, default
  `classic_stable_89j9qf`). Terraform **references it as a data source — it does
  not create it**; it only creates `lumen_bronze` / `lumen_silver` /
  `lumen_gold` schemas + a `lumen_raw` volume inside it.
- The **embedding endpoint** `databricks-bge-large-en` available (Foundation
  Model APIs) — used for batch + query embeddings.
- **Lakebase Autoscale** (the `databricks_postgres_*` resource family, Public
  Beta) enabled for your workspace/region.
- Permissions to: create schemas/volumes, upload notebooks, create + run a job
  (job cluster: `Standard_D4ds_v5` × 2), create a Lakebase project, and create a
  Databricks App.

> **Key gotcha:** Terraform's bootstrap step shells out to
> `../.venv/bin/python` (see `terraform/bootstrap.tf`). That repo-root `.venv`
> **must exist with `databricks-sdk` + `psycopg[binary]` before
> `terraform apply`** — `scripts/setup.sh` (step 3) creates it for you.

---

## Quick start

```bash
# From the repo root. Safe by default: tools + profile + venv + tfvars + init + plan.
scripts/setup.sh --profile azure-video --catalog classic_stable_89j9qf

# Review the plan, then provision (prompts before apply):
scripts/setup.sh --profile azure-video --catalog classic_stable_89j9qf --apply

# Open the running app:
terraform -chdir=terraform output app_url
```

Flags: `--profile NAME`, `--catalog NAME`, `--apply` (run `terraform apply`),
`--yes` (skip the apply confirmation), `--skip-terraform` (only set up tooling +
venv + tfvars).

The script is **idempotent**: re-running it reuses an existing `.venv` and never
overwrites an existing `terraform.tfvars`.

---

## Build order & dependencies

The order matters — each step depends on the previous:

1. **Local tools** — CLI, terraform, uv, node/npm must be on `PATH`.
2. **Databricks profile** — `databricks auth login --profile <name>`. Terraform
   reads auth from this profile (`terraform/providers.tf`); the CLI uses it to
   run the job and deploy the app.
3. **Python venv (uv)** — `.venv/` at the repo root with `databricks-sdk` +
   `psycopg[binary]` (+ `pgvector`). **Required before apply** because
   `terraform/bootstrap.tf` calls `../.venv/bin/python scripts/run_lakebase_sql.py`
   to apply the Lakebase bootstrap SQL.
4. **`terraform.tfvars`** — copy from `terraform.tfvars.example`; set
   `databricks_profile` and `catalog_name` (the catalog must already exist).
5. **`terraform init`** — download the `databricks` provider (≥ 1.50.0 for the
   `postgres_*` resources).
6. **`terraform plan`** — preview. Confirm you see Lakebase **Autoscale**
   (`autoscaling_limit_min_cu` numeric), not the Provisioned
   `databricks_database_instance`.
7. **`terraform apply`** — provisions, in dependency order:
   1. UC schemas (`lumen_bronze/silver/gold`) + `lumen_raw` volume
   2. 4 notebooks uploaded to the workspace
   3. Ingest+embed **job** created **and run to completion** (loads WANDS →
      gold + embeddings; ~10 min on the job cluster)
   4. Lakebase Autoscale project → branch → endpoint → database
   5. Databricks App (auto-creates its service principal)
   6. Postgres role for the App SP (`LAKEBASE_OAUTH_V1`)
   7. Synced Table: `lumen_gold.products` → Lakebase
   8. **Bootstrap SQL** via the `.venv` python (extensions, HNSW + GIN +
      trigram indexes, serving functions, GRANTs)
   9. Frontend `npm install && npm run build`, source staged + uploaded
   10. `databricks apps deploy` → running app

The frontend toolchain (npm) is invoked **by Terraform during apply** — you only
need Node installed; the script does not pre-build it.

---

## Manual steps (script equivalent)

If you prefer to run it by hand:

```bash
# 2. profile
databricks auth login --profile azure-video

# 3. venv (the one terraform/bootstrap.tf invokes)
uv venv .venv
uv pip install --python .venv/bin/python -r scripts/requirements-setup.txt

# 4. tfvars
cd terraform
cp terraform.tfvars.example terraform.tfvars   # edit databricks_profile / catalog_name

# 5–7. provision
terraform init
terraform plan
terraform apply
terraform output app_url
```

---

## Optional: eval harness & load test

These are **post-deploy** and independent of the main build.

```bash
# Search-quality eval (NDCG / Recall / MRR vs WANDS) — see eval/README.md
uv pip install --python .venv/bin/python -r eval/requirements.txt
python -m eval.run_eval --profile azure-video \
  --instance "$(terraform -chdir=terraform output -raw lakebase_endpoint)" \
  --database appdb --tag baseline

# Rust/Goose load test (latency) — see loadtest/README.md
cd loadtest && cargo run --release -- --host <app-url> -u 20 -t 2m
```

To apply only the FTS search tuning to an existing Lakebase (no full apply):

```bash
.venv/bin/python scripts/apply_search_tuning.py --profile azure-video \
  --instance "$(terraform -chdir=terraform output -raw lakebase_endpoint)" \
  --database appdb
```

---

## Verify

```bash
terraform -chdir=terraform output app_url     # open in a browser
```

Then exercise both modes from the UI (semantic / hybrid). For a local dev loop
(backend + Vite frontend), see the [README](../README.md#local-dev-loop).

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `../.venv/bin/python: No such file` during apply | The repo-root venv is missing — run `scripts/setup.sh --skip-terraform` (or the step-3 manual commands) first. |
| `Could not resolve catalog '<name>'` | `catalog_name` doesn't exist in the workspace. Point it at an existing catalog (Terraform won't create one). |
| `serving endpoint databricks-bge-large-en not found` | Foundation Model APIs / the endpoint isn't available in this workspace/region. |
| `default auth: cannot configure default credentials` | The CLI profile token expired — `databricks auth login --profile <name>`. |
| Plan shows `databricks_database_instance` with `capacity = "CU_1"` | That's **Provisioned**, not Autoscale — wrong resource family; check the provider version (≥ 1.50.0) and `lakebase.tf`. |
| `npm: command not found` during apply | Install Node ≥ 18; Terraform builds the frontend during apply. |
| Job run times out | The ingest+embed job can take ~10 min; the `local-exec` uses `--timeout 60m`. Re-run with `terraform apply` (the trigger re-fires on change). |

---

## Tear down

```bash
terraform -chdir=terraform destroy
```

Deletes the Lakebase project (with all branches/endpoints), the App, the synced
table, the `lumen_*` schemas + volume, and the workspace notebooks. The
referenced UC catalog itself is **not** deleted (Terraform never created it).
