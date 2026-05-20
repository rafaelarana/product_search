output "lakebase_project" {
  description = "Lakebase Autoscale project resource name"
  value       = databricks_postgres_project.this.name
}

output "lakebase_branch" {
  description = "Branch resource name (used in app config)"
  value       = databricks_postgres_branch.main.name
}

output "lakebase_endpoint" {
  description = "Read/write endpoint resource name"
  value       = databricks_postgres_endpoint.primary.name
}

output "lakebase_pg_version" {
  value = var.lakebase_pg_version
}

output "lakebase_min_cu" { value = var.lakebase_min_cu }
output "lakebase_max_cu" { value = var.lakebase_max_cu }
output "lakebase_suspend_seconds" { value = var.lakebase_suspend_seconds }

output "app_url" {
  description = "Databricks App URL"
  value       = databricks_app.lumen.url
}

output "app_sp_client_id" {
  description = "Service principal client_id used by the App"
  value       = databricks_app.lumen.service_principal_client_id
}

output "app_name" {
  value = databricks_app.lumen.name
}

output "catalog" {
  value = data.databricks_catalog.this.name
}

output "ingest_job_id" {
  value = databricks_job.ingest_and_embed.id
}

output "synced_table_full_name" {
  value = databricks_postgres_synced_table.products.synced_table_id
}

output "lakebase_dataset_full_name" {
  value = "${data.databricks_catalog.this.name}.${databricks_schema.gold.name}.products"
}
