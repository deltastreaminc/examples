#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import ssl
import urllib.error
import urllib.request


QUERY_NAMES = [
    "aws_returns_orders_raw_mv_q",
    "aws_returns_shipments_raw_mv_q",
    "aws_returns_returns_raw_mv_q",
    "aws_returns_refunds_raw_mv_q",
    "aws_returns_customer_returns_context_mv_q",
]

RELATIONS = [
    "aws_returns_bench.public.customer_returns_context_mv",
    "aws_returns_bench.public.orders_raw_mv",
    "aws_returns_bench.public.shipments_raw_mv",
    "aws_returns_bench.public.returns_raw_mv",
    "aws_returns_bench.public.refunds_raw_mv",
    "aws_returns_bench.public.orders_stream",
    "aws_returns_bench.public.shipments_stream",
    "aws_returns_bench.public.returns_stream",
    "aws_returns_bench.public.refunds_stream",
    "aws_returns_bench.public.orders_cl",
    "aws_returns_bench.public.shipments_cl",
    "aws_returns_bench.public.returns_cl",
    "aws_returns_bench.public.refunds_cl",
    "aws_returns_bench.public.refunds_by_return_cl",
]

TOPICS = [
    "aws_returns_orders",
    "aws_returns_shipments",
    "aws_returns_returns",
    "aws_returns_refunds",
]


def _normalize_statement_url(server: str) -> str:
    base = server.rstrip("/")
    if base.endswith("/v2"):
        return f"{base}/statements"
    return f"{base}/v2/statements"


def _execute_statement(
    *,
    statement_url: str,
    token: str,
    statement: str,
    role: str,
    database: str,
    schema: str,
    store: str,
    insecure: bool,
) -> dict:
    stmt = statement.strip()
    if not stmt.endswith(";"):
        stmt = f"{stmt};"
    payload = {
        "statement": stmt,
        "role": role,
        "database": database,
        "schema": schema,
        "store": store,
    }
    req = urllib.request.Request(
        statement_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    context = None
    if insecure:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=120, context=context) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def _run_best_effort(
    *,
    statement_url: str,
    token: str,
    statement: str,
    role: str,
    database: str,
    schema: str,
    store: str,
    insecure: bool,
) -> bool:
    preview = " ".join(statement.split())
    try:
        res = _execute_statement(
            statement_url=statement_url,
            token=token,
            statement=statement,
            role=role,
            database=database,
            schema=schema,
            store=store,
            insecure=insecure,
        )
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")
        print(f"[warn] HTTP {e.code}: {preview}\n       {msg}")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {type(e).__name__}: {preview}\n       {e}")
        return False

    sql_state = (res.get("sqlState") or "").upper()
    if sql_state and sql_state not in {"00000", "SUCCESS", "OK"}:
        msg = res.get("message") or "unknown error"
        print(f"[warn] sqlState={sql_state}: {preview}\n       {msg}")
        return False
    print(f"[ok] {preview}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Cleanup DeltaStream benchmark artifacts. By default performs all actions: "
            "terminate queries, drop relations, drop topics."
        )
    )
    ap.add_argument("--token", default=None, help="DeltaStream API token (or DELTASTREAM_API_TOKEN env)")
    ap.add_argument("--server", required=True, help="DeltaStream API server base URL")
    ap.add_argument("--store-name", required=True, help="DeltaStream Kafka store name")
    ap.add_argument("--role", default="sysadmin")
    ap.add_argument("--database", default="aws_returns_bench")
    ap.add_argument("--schema", default="public")
    ap.add_argument("--insecure", action="store_true", help="Disable TLS cert verification")

    ap.add_argument("--no-stop-queries", action="store_true")
    ap.add_argument("--no-drop-relations", action="store_true")
    ap.add_argument("--no-drop-topics", action="store_true")
    args = ap.parse_args()

    token = args.token or os.environ.get("DELTASTREAM_API_TOKEN")
    if not token:
        raise SystemExit("missing token: pass --token or set DELTASTREAM_API_TOKEN")

    insecure = args.insecure or os.environ.get("DELTASTREAM_INSECURE", "").lower() in {
        "1",
        "true",
        "yes",
        "y",
    }

    statement_url = _normalize_statement_url(args.server)
    print(f"DeltaStream statements endpoint: {statement_url}")
    print(f"Using store: {args.store_name}")
    print(f"TLS verify: {'disabled' if insecure else 'enabled'}")

    stop_queries = not args.no_stop_queries
    drop_relations = not args.no_drop_relations
    drop_topics = not args.no_drop_topics

    if stop_queries:
        print("[phase] terminate named queries")
        for name in QUERY_NAMES:
            _run_best_effort(
                statement_url=statement_url,
                token=token,
                statement=f"TERMINATE QUERY {name}",
                role=args.role,
                database=args.database,
                schema=args.schema,
                store=args.store_name,
                insecure=insecure,
            )
    else:
        print("[skip] terminate queries")

    if drop_relations:
        print("[phase] drop relations")
        for relation in RELATIONS:
            _run_best_effort(
                statement_url=statement_url,
                token=token,
                statement=f"DROP RELATION {relation}",
                role=args.role,
                database=args.database,
                schema=args.schema,
                store=args.store_name,
                insecure=insecure,
            )
    else:
        print("[skip] drop relations")

    if drop_topics:
        print("[phase] drop store entities/topics")
        for topic in TOPICS:
            _run_best_effort(
                statement_url=statement_url,
                token=token,
                statement=f'DROP ENTITY "{topic}" IN STORE "{args.store_name}"',
                role=args.role,
                database=args.database,
                schema=args.schema,
                store=args.store_name,
                insecure=insecure,
            )
    else:
        print("[skip] drop topics")

    print("Cleanup completed (best effort).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
