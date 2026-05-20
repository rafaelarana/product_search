terraform {
  required_version = ">= 1.6.0"
  required_providers {
    databricks = {
      source = "databricks/databricks"
      # Lakebase Autoscale (databricks_postgres_*) is Public Beta.
      # Pin to a recent version that includes these resources.
      version = ">= 1.50.0"
    }
  }
}
