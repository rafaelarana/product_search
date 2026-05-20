"""Query-time embedding via Databricks Model Serving (BGE-large-en, 1024-dim)."""
from __future__ import annotations

from databricks.sdk import WorkspaceClient

from . import settings

_workspace = WorkspaceClient(
    host=settings.DATABRICKS_HOST or None,
    client_id=settings.DATABRICKS_CLIENT_ID,
    client_secret=settings.DATABRICKS_CLIENT_SECRET,
)


def embed_query(text: str) -> list[float]:
    """Return a 1024-dim BGE-large embedding for the user query."""
    resp = _workspace.serving_endpoints.query(
        name=settings.SERVING_ENDPOINT_EMBEDDING,
        input=[text],
    )
    # Foundation Models endpoints return objects with .data[N].embedding
    elt = resp.data[0]
    emb = elt.embedding if hasattr(elt, "embedding") else elt["embedding"]
    return list(emb)
