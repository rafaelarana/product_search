# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Load WANDS dataset into Bronze
# MAGIC
# MAGIC Downloads the Wayfair WANDS dataset (~43K products, MIT license) and lands
# MAGIC the three CSVs into a UC managed volume, then registers Bronze tables.
# MAGIC
# MAGIC Source: https://github.com/wayfair/WANDS

# COMMAND ----------

dbutils.widgets.text("catalog", "product_recommender_dev", "UC catalog")
catalog = dbutils.widgets.get("catalog")
volume_path = f"/Volumes/{catalog}/lumen_bronze/lumen_raw"

# COMMAND ----------

# MAGIC %sh
# MAGIC set -e
# MAGIC cd /tmp
# MAGIC rm -rf WANDS && git clone --depth=1 https://github.com/wayfair/WANDS.git
# MAGIC ls -la /tmp/WANDS/dataset/

# COMMAND ----------

import shutil, os

for f in ["product.csv", "query.csv", "label.csv"]:
    src = f"/tmp/WANDS/dataset/{f}"
    dst = f"{volume_path}/{f}"
    shutil.copy(src, dst)
    print(f"Copied {src} → {dst} ({os.path.getsize(dst)/1e6:.1f} MB)")

# COMMAND ----------

# WANDS uses tab-separated CSVs. Some headers contain spaces (e.g.
# "category hierarchy") which Delta rejects — normalize to snake_case.
def _read_tsv(path):
    df = spark.read.option("header", True).option("sep", "\t").csv(path)
    for c in df.columns:
        df = df.withColumnRenamed(c, c.strip().replace(" ", "_").lower())
    return df

products = _read_tsv(f"{volume_path}/product.csv")
queries  = _read_tsv(f"{volume_path}/query.csv")
labels   = _read_tsv(f"{volume_path}/label.csv")

print(f"products: {products.count():,}")
print(f"queries:  {queries.count():,}")
print(f"labels:   {labels.count():,}")
products.printSchema()

# COMMAND ----------

(products.write.mode("overwrite")
 .option("overwriteSchema", "true")
 .saveAsTable(f"{catalog}.lumen_bronze.products"))
(queries.write.mode("overwrite")
 .option("overwriteSchema", "true")
 .saveAsTable(f"{catalog}.lumen_bronze.queries"))
(labels.write.mode("overwrite")
 .option("overwriteSchema", "true")
 .saveAsTable(f"{catalog}.lumen_bronze.labels"))

print("Bronze tables written.")
