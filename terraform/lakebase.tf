# Lakebase AUTOSCALE — uses the `databricks_postgres_*` resource family.
# Distinguishing autoscale signals (vs Provisioned `databricks_database_instance`):
#   • numeric autoscaling_limit_min_cu / max_cu (1 CU ≈ 2 GB RAM on autoscale)
#   • suspend_timeout_duration (idle-suspend, scale-to-zero)
#   • resource name format: projects/{p}/branches/{b}/endpoints/{e}
#   • Public Beta — no drift detection, serial mutations per branch.

resource "databricks_postgres_project" "this" {
  project_id = var.lakebase_project_id

  spec = {
    pg_version   = var.lakebase_pg_version
    display_name = "Lumen — semantic product search"

    history_retention_duration = "604800s" # 7 days

    default_endpoint_settings = {
      autoscaling_limit_min_cu = var.lakebase_min_cu
      autoscaling_limit_max_cu = var.lakebase_max_cu
      suspend_timeout_duration = "${var.lakebase_suspend_seconds}s"
    }

    enable_pg_native_login = true
  }
}

# The "root" branch is implicitly created with the project — we replace it
# with our named branch so we can opt into is_protected + no_expiry.
resource "databricks_postgres_branch" "main" {
  branch_id        = var.lakebase_branch_id
  parent           = databricks_postgres_project.this.name
  replace_existing = true

  spec = {
    no_expiry    = true
    is_protected = true
  }
}

# Same pattern for the read/write endpoint — replace the implicit one so we
# control min/max CU and suspend behaviour.
resource "databricks_postgres_endpoint" "primary" {
  endpoint_id      = var.lakebase_endpoint_id
  parent           = databricks_postgres_branch.main.name
  replace_existing = true

  spec = {
    endpoint_type            = "ENDPOINT_TYPE_READ_WRITE"
    autoscaling_limit_min_cu = var.lakebase_min_cu
    autoscaling_limit_max_cu = var.lakebase_max_cu
    suspend_timeout_duration = "${var.lakebase_suspend_seconds}s"
  }

  depends_on = [databricks_postgres_branch.main]
}

# The apply-time user owns the database. Lakebase auto-creates a role for
# every user on first access (DATABRICKS_SUPERUSER), with role_id = the local
# part of the email with dots → dashes, e.g. rafael.arana@... → rafael-arana.
locals {
  user_local_part   = split("@", data.databricks_current_user.me.user_name)[0]
  apply_user_role   = replace(local.user_local_part, ".", "-")
  apply_user_role_n = "${databricks_postgres_branch.main.name}/roles/${local.apply_user_role}"
}

# Logical database the app connects to.
resource "databricks_postgres_database" "app_db" {
  database_id = var.lakebase_app_database
  parent      = databricks_postgres_branch.main.name

  spec = {
    postgres_database = var.lakebase_app_database
    role              = local.apply_user_role_n
  }

  depends_on = [databricks_postgres_endpoint.primary]
}
