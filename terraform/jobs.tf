# One job runs the data pipeline: load WANDS → silver/gold → embed catalog.

resource "databricks_job" "ingest_and_embed" {
  name                = "[${var.name_prefix}] Ingest + Embed WANDS"
  description         = "Loads WANDS into UC, builds gold.products with embedding_text, batch-embeds via ai_query."
  max_concurrent_runs = 1

  job_cluster {
    job_cluster_key = "small"
    new_cluster {
      spark_version      = "15.4.x-scala2.12"
      node_type_id       = "Standard_D4ds_v5"
      num_workers        = 2
      data_security_mode = "SINGLE_USER"
    }
  }

  task {
    task_key = "setup"
    notebook_task {
      notebook_path   = databricks_notebook.setup.path
      base_parameters = { catalog = data.databricks_catalog.this.name }
    }
    job_cluster_key = "small"
  }

  task {
    task_key = "load_wands"
    depends_on { task_key = "setup" }
    notebook_task {
      notebook_path   = databricks_notebook.load_wands.path
      base_parameters = { catalog = data.databricks_catalog.this.name }
    }
    job_cluster_key = "small"
  }

  task {
    task_key = "silver_gold"
    depends_on { task_key = "load_wands" }
    notebook_task {
      notebook_path   = databricks_notebook.silver_gold.path
      base_parameters = { catalog = data.databricks_catalog.this.name }
    }
    job_cluster_key = "small"
  }

  task {
    task_key = "embed_catalog"
    depends_on { task_key = "silver_gold" }
    notebook_task {
      notebook_path = databricks_notebook.embed_catalog.path
      base_parameters = {
        catalog  = data.databricks_catalog.this.name
        endpoint = var.embedding_endpoint_name
      }
    }
    job_cluster_key = "small"
  }
}
