import os

DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST", "").rstrip("/")

# Full endpoint resource name, e.g.
#   projects/ecommerce-search-demo/branches/production/endpoints/primary
LAKEBASE_ENDPOINT = os.environ["LAKEBASE_ENDPOINT"]

LAKEBASE_DATABASE = os.environ.get("LAKEBASE_DATABASE", "appdb")

# In a Databricks App, DATABRICKS_CLIENT_ID is the App's auto-created service
# principal client_id — this is also the Postgres user.
LAKEBASE_USER = os.environ.get("LAKEBASE_USER") or os.environ["DATABRICKS_CLIENT_ID"]

SERVING_ENDPOINT_EMBEDDING = os.environ.get(
    "SERVING_ENDPOINT_EMBEDDING", "databricks-bge-large-en"
)

POOL_MIN_SIZE = int(os.environ.get("POOL_MIN_SIZE", "1"))
POOL_MAX_SIZE = int(os.environ.get("POOL_MAX_SIZE", "10"))

# Databricks Apps inject these for the app's own service principal.
DATABRICKS_CLIENT_ID = os.environ.get("DATABRICKS_CLIENT_ID")
DATABRICKS_CLIENT_SECRET = os.environ.get("DATABRICKS_CLIENT_SECRET")
