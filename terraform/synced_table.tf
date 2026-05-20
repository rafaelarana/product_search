# Synced Table: Delta lumen_gold.products → Lakebase public.products
#
# Mode: TRIGGERED — manual refresh, cheaper for a static-catalog demo.
# create_database_objects_if_missing creates the destination table for us.
# new_pipeline_spec lets DLT manage the pipeline.

resource "databricks_postgres_synced_table" "products" {
  synced_table_id = "${data.databricks_catalog.this.name}.${databricks_schema.gold.name}.products_synced"

  spec = {
    branch            = databricks_postgres_branch.main.name
    postgres_database = databricks_postgres_database.app_db.database_id

    source_table_full_name             = "${data.databricks_catalog.this.name}.${databricks_schema.gold.name}.products"
    primary_key_columns                = ["product_id"]
    scheduling_policy                  = "TRIGGERED"
    create_database_objects_if_missing = true

    new_pipeline_spec = {
      storage_catalog = data.databricks_catalog.this.name
      storage_schema  = databricks_schema.gold.name
    }
  }

  # Synced table can only be created after the gold table has rows.
  # The terraform_data resource below blocks on the job run completing.
  depends_on = [terraform_data.run_ingest_job]
}
