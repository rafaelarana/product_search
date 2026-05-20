# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Embed catalog
# MAGIC
# MAGIC Generates 1024-dim BGE-large embeddings for all products using `ai_query`.
# MAGIC Incremental: only rows where `embedding IS NULL`.

# COMMAND ----------

dbutils.widgets.text("catalog", "product_recommender_dev", "UC catalog")
dbutils.widgets.text("endpoint", "databricks-bge-large-en", "Embedding serving endpoint")
catalog = dbutils.widgets.get("catalog")
endpoint = dbutils.widgets.get("endpoint")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Embed missing rows
# MAGIC
# MAGIC `ai_query` returns a struct/array directly. For BGE-large it's `array<float>`
# MAGIC of length 1024. We update `gold.products` in place.

# COMMAND ----------

spark.sql(f"""
MERGE INTO {catalog}.lumen_gold.products t
USING (
  SELECT
    product_id,
    CAST(ai_query('{endpoint}', embedding_text) AS ARRAY<FLOAT>) AS new_embedding
  FROM {catalog}.lumen_gold.products
  WHERE embedding IS NULL
) s
ON t.product_id = s.product_id
WHEN MATCHED THEN UPDATE SET t.embedding = s.new_embedding
""")

remaining = spark.sql(
    f"SELECT count(*) AS n FROM {catalog}.lumen_gold.products WHERE embedding IS NULL"
).first()["n"]
total = spark.sql(f"SELECT count(*) AS n FROM {catalog}.lumen_gold.products").first()["n"]
print(f"Embedded: {total - remaining:,}/{total:,}  (remaining: {remaining:,})")

# COMMAND ----------

# Quick sanity check on embedding shape
sample = spark.sql(
    f"SELECT product_id, size(embedding) AS dim FROM {catalog}.lumen_gold.products "
    f"WHERE embedding IS NOT NULL LIMIT 5"
).collect()
for r in sample:
    print(f"product_id={r.product_id}  dim={r.dim}")
assert all(r.dim == 1024 for r in sample), "Expected 1024-dim BGE-large embeddings"
