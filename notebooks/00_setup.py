# Databricks notebook source
# MAGIC %md
# MAGIC # 00 — Setup
# MAGIC
# MAGIC Creates the Unity Catalog catalog + schemas for the product recommender demo.

# COMMAND ----------

dbutils.widgets.text("catalog", "product_recommender_dev", "UC catalog")
catalog = dbutils.widgets.get("catalog")

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.lumen_bronze")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.lumen_silver")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.lumen_gold")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.lumen_bronze.lumen_raw")

print(f"Ready: {catalog}.lumen_{{bronze,silver,gold}}")
