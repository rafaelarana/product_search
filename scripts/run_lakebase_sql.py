#!/usr/bin/env python3
"""Run the Lakebase bootstrap SQL against a Lakebase Autoscale branch.

Calls the Postgres-Autoscale API directly (not the database/instances API)
because the Python SDK doesn't yet expose ws.postgres.* on stable releases.

Endpoints used:
    GET  /api/2.0/postgres/projects/{p}/branches/{b}/endpoints/{e}
    POST /api/2.0/postgres/credentials  body: {"endpoint": "<name>"}

Usage:
    python3 scripts/run_lakebase_sql.py \\
        --profile azure-video \\
        --instance projects/<id>/branches/<id>/endpoints/<id> \\
        --database appdb \\
        --app-sp-client-id <uuid> \\
        --sql notebooks/04_lakebase_bootstrap.sql

Dependencies: databricks-sdk, psycopg[binary].
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import psycopg
    from databricks.sdk import WorkspaceClient
except ImportError:  # pragma: no cover
    print(
        "Missing deps. Install with:\n"
        "  pip install 'databricks-sdk>=0.89.0' 'psycopg[binary]>=3.1.0'",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--instance", required=True, help="full endpoint resource name")
    p.add_argument("--database", required=True)
    p.add_argument("--app-sp-client-id", required=True)
    p.add_argument("--sql", required=True, type=Path)
    args = p.parse_args()

    os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
    ws = WorkspaceClient()

    # 1. Resolve endpoint DNS via Postgres-Autoscale API.
    endpoint = ws.api_client.do("GET", f"/api/2.0/postgres/{args.instance}")
    dns = endpoint["status"]["hosts"]["host"]
    print(f">> Endpoint: {args.instance}")
    print(f">> DNS:      {dns}")

    # 2. Mint OAuth token for this endpoint.
    cred = ws.api_client.do(
        "POST",
        "/api/2.0/postgres/credentials",
        body={"endpoint": args.instance},
    )
    token = cred["token"]
    print(f">> Token minted, expires {cred.get('expire_time')}")

    # 3. Connect as the current user. The user's identity is the apply-time
    #    superuser; Lakebase auto-created their role on first access.
    me = ws.current_user.me()
    user = me.user_name
    print(f">> Connecting to {args.database} as {user}")

    conn = psycopg.connect(
        host=dns,
        port=5432,
        dbname=args.database,
        user=user,
        password=token,
        sslmode="require",
        autocommit=True,
    )

    sql = args.sql.read_text()

    # Grant access to the App SP role. We GRANT EXECUTE on each function we
    # own individually (NOT `ALL FUNCTIONS IN SCHEMA public`) because Lakebase
    # exposes internal system functions in `public` that we don't own and
    # can't re-grant.
    sp = args.app_sp_client_id
    grant_block = f"""
    GRANT CONNECT ON DATABASE {args.database} TO "{sp}";

    GRANT USAGE  ON SCHEMA public     TO "{sp}";
    GRANT USAGE  ON SCHEMA lumen_gold TO "{sp}";

    GRANT SELECT ON ALL TABLES IN SCHEMA lumen_gold TO "{sp}";
    ALTER DEFAULT PRIVILEGES IN SCHEMA lumen_gold GRANT SELECT ON TABLES TO "{sp}";

    GRANT EXECUTE ON FUNCTION search_products_semantic(vector, text, int)                       TO "{sp}";
    GRANT EXECUTE ON FUNCTION search_products_hybrid(text, vector, text, int, float, float)     TO "{sp}";
    GRANT EXECUTE ON FUNCTION recommend_similar_products(int, int, boolean)                     TO "{sp}";
    GRANT EXECUTE ON FUNCTION list_product_classes(int)                                         TO "{sp}";
    GRANT EXECUTE ON FUNCTION get_product(int)                                                  TO "{sp}";
    """

    print(f">> Applying {args.sql} ({len(sql):,} bytes)")
    with conn.cursor() as cur:
        cur.execute(sql)
        print(f">> GRANTing on schema public to App SP role {sp}")
        cur.execute(grant_block)

    conn.close()
    print(">> Lakebase bootstrap done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
