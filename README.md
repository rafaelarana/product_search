# Lumen — Semantic Product Search on Lakebase Autoscale

A Databricks App demo: semantic + hybrid product search and "similar products"
recommendations over the [WANDS](https://github.com/wayfair/WANDS) Wayfair
dataset (~43K products), backed by **Lakebase Autoscale + pgvector**.

Architecture follows the patterns in [`doc/Lakebase_Validacion_Tecnica_ECommerce.md`](doc/Lakebase_Validacion_Tecnica_ECommerce.md).

> **Lakebase Autoscale, not Provisioned.** The provider uses the
> `databricks_postgres_*` resource family (Public Beta), with numeric
> `autoscaling_limit_min_cu`/`max_cu` and `suspend_timeout_duration` — this
> is what makes it Autoscale. The older `databricks_database_instance` resource
> with `capacity = "CU_1"` is the Provisioned product, which we do **not** use.

## Stack

| Layer | Tech |
|---|---|
| Data | WANDS CSVs → Bronze/Silver/Gold Delta in Unity Catalog |
| Embeddings | `databricks-bge-large-en` (1024-dim) via `ai_query` |
| Serving DB | **Lakebase Autoscale** (PG 17) with `pgvector` HNSW + tsvector GIN |
| Sync | `databricks_postgres_synced_table` (TRIGGERED) |
| Backend | FastAPI + psycopg3 pool with OAuth token rotation |
| Frontend | React + Vite + Tailwind, dark-mode "Lumen" branding |
| **All infra** | Terraform (`terraform/` directory) |

## Deploy

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # edit defaults if needed
terraform init
terraform plan
terraform apply
```

A single `terraform apply` provisions, in order:

1. UC catalog + bronze/silver/gold schemas + raw volume
2. 4 notebooks uploaded to the workspace
3. Ingest+embed job created **and triggered** (waits to completion)
4. Lakebase Autoscale project + branch + endpoint + database
5. Databricks App (auto-creates its service principal)
6. Postgres role for the App's SP (OAuth)
7. Synced Table: `gold.products` → Lakebase `public.products`
8. Bootstrap SQL applied: pgvector extension, HNSW + GIN indexes,
   4 SQL functions (`search_products_semantic`, `_hybrid`,
   `recommend_similar_products`, `list_product_classes`), GRANTs to App SP
9. Frontend `npm run build`, app source uploaded to workspace
10. `databricks apps deploy` to ship the running app

```bash
terraform output app_url   # open the running demo
```

## What "Autoscale" looks like in the plan

Look for these in `terraform plan` output (this is how you confirm Autoscale, not Provisioned):

```hcl
resource "databricks_postgres_endpoint" "primary" {
  spec = {
    endpoint_type            = "ENDPOINT_TYPE_READ_WRITE"
    autoscaling_limit_min_cu = 0.5      # numeric, NOT a CU_n enum
    autoscaling_limit_max_cu = 2.0
    suspend_timeout_duration = "604800s"
  }
}
```

If you see `databricks_database_instance` with `capacity = "CU_1"`, that's
the **Provisioned** product and would be wrong.

## Repo layout

```
terraform/                  # ← all infra
├── versions.tf             # provider pinned (>= 1.50.0 for postgres_* support)
├── providers.tf            # databricks provider, profile = azure-video
├── variables.tf            # tunables (CU min/max, suspend, names)
├── catalog.tf              # UC catalog + schemas + volume
├── notebooks.tf            # upload 4 notebooks
├── jobs.tf                 # ingest+embed job
├── lakebase.tf             # postgres_project + branch + endpoint + database (AUTOSCALE)
├── app.tf                  # databricks_app with lakebase + serving_endpoint resources
├── role.tf                 # postgres_role for App SP (LAKEBASE_OAUTH_V1)
├── synced_table.tf         # postgres_synced_table (TRIGGERED)
├── bootstrap.tf            # terraform_data: run job + run SQL + upload+deploy app
└── outputs.tf              # endpoint name, app url, SP client_id

notebooks/                  # 00_setup → 04_lakebase_bootstrap.sql
scripts/
└── run_lakebase_sql.py     # OAuth → psycopg → execute bootstrap SQL
app/
├── app.yaml                # Databricks App manifest
├── backend/                # FastAPI: /search, /recommend, /product, /classes
└── frontend/               # React + Vite + Tailwind
doc/
└── Lakebase_Validacion_Tecnica_ECommerce.md
```

## Local dev loop

```bash
# backend (auth comes from azure-video profile)
cd app
pip install -r requirements.txt
export DATABRICKS_CONFIG_PROFILE=azure-video
export LAKEBASE_INSTANCE_NAME=$(terraform -chdir=../terraform output -raw lakebase_endpoint)
export LAKEBASE_USER=$(terraform -chdir=../terraform output -raw app_sp_client_id)
uvicorn backend.main:app --reload --port 8000

# frontend (separate terminal)
cd app/frontend
npm install
npm run dev    # http://localhost:5173, proxies /api → :8000
```

## Tear down

```bash
cd terraform
terraform destroy
```

This deletes the Lakebase project (and all branches/endpoints with it),
the App, the synced table pipeline, the UC catalog (cascade-deletes
schemas, tables, volume), and the workspace notebooks.

## References

- [Lakebase Autoscale docs](https://docs.databricks.com/aws/en/oltp/projects/about)
- [Manage computes (CU sizing)](https://docs.databricks.com/aws/en/oltp/projects/manage-computes)
- [Terraform `databricks_postgres_project`](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/postgres_project)
- [WANDS dataset](https://github.com/wayfair/WANDS) (MIT)
- [Databricks product-search accelerator](https://github.com/databricks-industry-solutions/product-search) (reference)
