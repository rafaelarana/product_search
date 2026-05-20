# Upload notebooks from the local repo into the workspace.
# `databricks_notebook` accepts SOURCE format and renders the Databricks notebook
# from the `# COMMAND ----------` cell separators.

locals {
  notebook_base = "/Workspace/Users/${data.databricks_current_user.me.user_name}/lumen-recommender/notebooks"
}

resource "databricks_notebook" "setup" {
  path     = "${local.notebook_base}/00_setup"
  source   = "${path.module}/../notebooks/00_setup.py"
  language = "PYTHON"
}

resource "databricks_notebook" "load_wands" {
  path     = "${local.notebook_base}/01_load_wands"
  source   = "${path.module}/../notebooks/01_load_wands.py"
  language = "PYTHON"
}

resource "databricks_notebook" "silver_gold" {
  path     = "${local.notebook_base}/02_silver_gold"
  source   = "${path.module}/../notebooks/02_silver_gold.py"
  language = "PYTHON"
}

resource "databricks_notebook" "embed_catalog" {
  path     = "${local.notebook_base}/03_embed_catalog"
  source   = "${path.module}/../notebooks/03_embed_catalog.py"
  language = "PYTHON"
}
