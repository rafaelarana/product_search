# Databricks App. The App auto-creates its own service principal — we use its
# client_id below to mint a Postgres role for it.
#
# The `postgres` resource attaches the App to a specific Lakebase branch +
# logical database; this is what tells Databricks Apps which Lakebase to
# inject OAuth credentials for.

resource "databricks_app" "lumen" {
  name         = var.app_name
  description  = "Lumen — semantic product search on Lakebase Autoscale (BGE-large + pgvector HNSW)"
  compute_size = var.app_compute_size

  resources = [
    {
      name = "lakebase"
      postgres = {
        branch     = databricks_postgres_branch.main.name
        database   = databricks_postgres_database.app_db.name
        permission = "CAN_CONNECT_AND_CREATE"
      }
    },
    {
      name = "embedding_endpoint"
      serving_endpoint = {
        name       = var.embedding_endpoint_name
        permission = "CAN_QUERY"
      }
    },
  ]

  depends_on = [
    databricks_postgres_endpoint.primary,
    databricks_postgres_database.app_db,
  ]
}
