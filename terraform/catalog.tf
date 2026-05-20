# Reuse an existing managed catalog instead of creating a new one
# (the workspace has Default Storage on the metastore and the provider can't
# yet create catalogs in that mode without an explicit storage_root).
#
# Schemas are namespaced with `lumen_` to avoid colliding with other users
# of the shared catalog.

data "databricks_current_user" "me" {}

data "databricks_catalog" "this" {
  name = var.catalog_name
}

resource "databricks_schema" "bronze" {
  catalog_name  = data.databricks_catalog.this.name
  name          = "lumen_bronze"
  force_destroy = true
}

resource "databricks_schema" "silver" {
  catalog_name  = data.databricks_catalog.this.name
  name          = "lumen_silver"
  force_destroy = true
}

resource "databricks_schema" "gold" {
  catalog_name  = data.databricks_catalog.this.name
  name          = "lumen_gold"
  force_destroy = true
}

resource "databricks_volume" "raw" {
  catalog_name = data.databricks_catalog.this.name
  schema_name  = databricks_schema.bronze.name
  name         = "lumen_raw"
  volume_type  = "MANAGED"
}
