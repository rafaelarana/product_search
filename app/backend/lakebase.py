"""Lakebase Autoscale connection pool with OAuth token rotation.

Pattern from validation doc §3: each new connection out of the pool fetches a
fresh OAuth token via the Postgres-Autoscale API. psycopg pool handles reuse,
retry, and warmup.
"""
from __future__ import annotations

import logging
from typing import Any

import psycopg
from databricks.sdk import WorkspaceClient
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import settings

log = logging.getLogger(__name__)

_workspace = WorkspaceClient(
    host=settings.DATABRICKS_HOST or None,
    client_id=settings.DATABRICKS_CLIENT_ID,
    client_secret=settings.DATABRICKS_CLIENT_SECRET,
)


def _get_endpoint_host() -> str:
    """Resolve the Lakebase Autoscale endpoint's read-write DNS."""
    endpoint = _workspace.api_client.do(
        "GET", f"/api/2.0/postgres/{settings.LAKEBASE_ENDPOINT}"
    )
    return endpoint["status"]["hosts"]["host"]


_HOST = _get_endpoint_host()


class OAuthConnection(psycopg.Connection):
    """A psycopg connection that fetches a fresh OAuth token on each connect."""

    @classmethod
    def connect(cls, conninfo: str = "", **kwargs: Any) -> "OAuthConnection":
        cred = _workspace.api_client.do(
            "POST",
            "/api/2.0/postgres/credentials",
            body={"endpoint": settings.LAKEBASE_ENDPOINT},
        )
        kwargs["password"] = cred["token"]
        return super().connect(conninfo, **kwargs)  # type: ignore[return-value]


def _configure(conn: psycopg.Connection) -> None:
    """Per-connection setup: register pgvector type, dict row factory."""
    register_vector(conn)
    conn.row_factory = dict_row


pool: ConnectionPool = ConnectionPool(
    conninfo=(
        f"dbname={settings.LAKEBASE_DATABASE} "
        f"user={settings.LAKEBASE_USER} "
        f"host={_HOST} port=5432 sslmode=require"
    ),
    connection_class=OAuthConnection,
    min_size=settings.POOL_MIN_SIZE,
    max_size=settings.POOL_MAX_SIZE,
    configure=_configure,
    open=False,  # opened in main.py lifespan
)
