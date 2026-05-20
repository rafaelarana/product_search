# Post-apply procedural steps that Terraform alone can't express:
#   1. Run the ingest+embed job once (populates gold.products with embeddings).
#   2. Run the Lakebase bootstrap SQL (extensions, indexes, functions, grants).
#   3. Upload the app source to the workspace path the App reads from.
#
# Each uses `terraform_data` (built-in) with `local-exec` provisioners. The
# triggers_replace map causes a re-run when the upstream resource changes.

# --- 1. Trigger the ingest + embed job --------------------------------------
resource "terraform_data" "run_ingest_job" {
  triggers_replace = {
    job_id  = databricks_job.ingest_and_embed.id
    catalog = data.databricks_catalog.this.name
  }

  provisioner "local-exec" {
    command = <<-EOT
      databricks jobs run-now ${databricks_job.ingest_and_embed.id} \
        --profile ${var.databricks_profile} \
        --timeout 60m
    EOT
  }

  depends_on = [
    databricks_job.ingest_and_embed,
    databricks_volume.raw,
  ]
}

# --- 2. Run the Lakebase bootstrap SQL --------------------------------------
# Creates extensions, indexes, functions, and GRANTs to the App's SP.
# Uses a small Python helper that mints an OAuth token via the SDK and
# executes the SQL with psycopg.
resource "terraform_data" "bootstrap_lakebase_sql" {
  triggers_replace = {
    endpoint = databricks_postgres_endpoint.primary.name
    role     = local.app_sp_role_name
    sql_hash = filesha256("${path.module}/../notebooks/04_lakebase_bootstrap.sql")
  }

  provisioner "local-exec" {
    command = <<-EOT
      ${path.module}/../.venv/bin/python ${path.module}/../scripts/run_lakebase_sql.py \
        --profile ${var.databricks_profile} \
        --instance ${databricks_postgres_endpoint.primary.name} \
        --database ${databricks_postgres_database.app_db.database_id} \
        --app-sp-client-id ${databricks_app.lumen.service_principal_client_id} \
        --sql ${path.module}/../notebooks/04_lakebase_bootstrap.sql
    EOT
  }

  depends_on = [
    databricks_postgres_synced_table.products,
    databricks_app.lumen,
  ]
}

# --- 3. Upload app source to workspace --------------------------------------
# Databricks Apps read their source from a workspace path. We stage ONLY the
# runtime files into .app-bundle/ (not node_modules), build the frontend,
# then upload the staging dir.
resource "terraform_data" "upload_app_source" {
  triggers_replace = {
    # Hash only the source files we actually ship.
    app_hash = sha256(join("", concat(
      [for f in fileset("${path.module}/../app", "app.yaml") : filesha256("${path.module}/../app/${f}")],
      [for f in fileset("${path.module}/../app", "requirements.txt") : filesha256("${path.module}/../app/${f}")],
      [for f in fileset("${path.module}/../app/backend", "**/*.py") : filesha256("${path.module}/../app/backend/${f}")],
      [for f in fileset("${path.module}/../app/frontend/src", "**") : filesha256("${path.module}/../app/frontend/src/${f}")],
      [for f in fileset("${path.module}/../app/frontend", "*.json") : filesha256("${path.module}/../app/frontend/${f}")],
      [for f in fileset("${path.module}/../app/frontend", "*.{ts,js,html}") : filesha256("${path.module}/../app/frontend/${f}")],
    )))
  }

  # Build the frontend (creates app/frontend/dist/).
  provisioner "local-exec" {
    working_dir = "${path.module}/../app/frontend"
    command     = "npm install --no-audit --no-fund --silent && npm run build"
  }

  # Stage runtime files into .app-bundle/.
  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    command     = <<-EOT
      rm -rf .app-bundle && mkdir -p .app-bundle/frontend
      cp app/app.yaml app/requirements.txt .app-bundle/
      cp -r app/backend .app-bundle/
      cp -r app/frontend/dist .app-bundle/frontend/dist
    EOT
  }

  # Upload the staging dir.
  provisioner "local-exec" {
    command = <<-EOT
      databricks workspace import-dir \
        --profile ${var.databricks_profile} \
        --overwrite \
        ${path.module}/../.app-bundle \
        ${var.app_workspace_source_path}
    EOT
  }

  depends_on = [databricks_app.lumen]
}

# --- 4. Deploy the app from the uploaded source ------------------------------
resource "terraform_data" "deploy_app" {
  triggers_replace = {
    upload_id = terraform_data.upload_app_source.id
    bootstrap = terraform_data.bootstrap_lakebase_sql.id
  }

  provisioner "local-exec" {
    command = <<-EOT
      databricks apps deploy ${var.app_name} \
        --profile ${var.databricks_profile} \
        --source-code-path ${var.app_workspace_source_path}
    EOT
  }

  depends_on = [
    terraform_data.upload_app_source,
    terraform_data.bootstrap_lakebase_sql,
  ]
}
