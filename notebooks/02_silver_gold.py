# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Silver + Gold
# MAGIC
# MAGIC - Silver: cleaned, typed product rows
# MAGIC - Gold: business-ready table with `embedding_text` (richer than the reference accelerator)

# COMMAND ----------

dbutils.widgets.text("catalog", "product_recommender_dev", "UC catalog")
catalog = dbutils.widgets.get("catalog")

# COMMAND ----------

# Silver: typed, deduped, with a stable primary key
spark.sql(f"""
CREATE OR REPLACE TABLE {catalog}.lumen_silver.products AS
SELECT
  CAST(product_id AS INT)            AS product_id,
  TRIM(product_name)                 AS product_name,
  TRIM(product_class)                AS product_class,
  TRIM(category_hierarchy)           AS category_hierarchy,
  TRIM(product_description)          AS product_description,
  TRIM(product_features)             AS product_features,
  CAST(rating_count AS INT)          AS rating_count,
  CAST(average_rating AS DOUBLE)     AS average_rating,
  CAST(review_count AS INT)          AS review_count,
  current_timestamp()                AS updated_at
FROM {catalog}.lumen_bronze.products
WHERE product_id IS NOT NULL
""")

# COMMAND ----------

# Gold: add embedding_text (used as input to bge-large in 03_embed_catalog)
# Strategy: name | class | category_hierarchy | description | features
# (richer than reference accelerator which used description only)
spark.sql(f"""
CREATE OR REPLACE TABLE {catalog}.lumen_gold.products AS
SELECT
  product_id,
  product_name,
  product_class,
  category_hierarchy,
  product_description,
  product_features,
  rating_count,
  average_rating,
  review_count,
  concat_ws(' | ',
    nullif(product_name, ''),
    nullif(product_class, ''),
    nullif(category_hierarchy, ''),
    nullif(product_description, ''),
    nullif(product_features, '')
  ) AS embedding_text,
  CAST(NULL AS ARRAY<FLOAT>) AS embedding,
  updated_at
FROM {catalog}.lumen_silver.products
""")

# Add primary key constraint so Synced Tables can use it
spark.sql(f"ALTER TABLE {catalog}.lumen_gold.products ALTER COLUMN product_id SET NOT NULL")
spark.sql(f"ALTER TABLE {catalog}.lumen_gold.products ADD CONSTRAINT pk_products PRIMARY KEY (product_id)")

# Enable Change Data Feed (required for Synced Tables in continuous/triggered mode)
spark.sql(f"ALTER TABLE {catalog}.lumen_gold.products SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")

print(f"{catalog}.lumen_gold.products ready — {spark.table(f'{catalog}.lumen_gold.products').count():,} rows")
