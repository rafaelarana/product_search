# The Databricks App auto-creates a Postgres role for its service principal
# when the App is created (role_id = "dbrx-apps-<sp-uuid>", postgres_role =
# the SP's client_id, attributes = no createdb/createrole/bypassrls).
#
# Database-level GRANTs to that role are applied via SQL in the bootstrap
# helper (scripts/run_lakebase_sql.py).

locals {
  app_sp_role_name = "${databricks_postgres_branch.main.name}/roles/dbrx-apps-${databricks_app.lumen.service_principal_client_id}"
}
