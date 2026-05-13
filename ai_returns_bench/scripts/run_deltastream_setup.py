#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DELTASTREAM_DIR = ROOT / "deltastream"


def _normalize_statement_url(server: str) -> str:
    base = server.rstrip("/")
    if base.endswith("/v2"):
        return f"{base}/statements"
    return f"{base}/v2/statements"


def _split_sql_statements(text: str) -> list[str]:
    statements: list[str] = []
    buff: list[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    while i < len(text):
        c = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if in_line_comment:
            if c == "\n":
                in_line_comment = False
                buff.append(c)
            i += 1
            continue

        if in_block_comment:
            if c == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if not in_single and not in_double:
            if c == "-" and nxt == "-":
                in_line_comment = True
                i += 2
                continue
            if c == "/" and nxt == "*":
                in_block_comment = True
                i += 2
                continue

        if c == "'" and not in_double:
            in_single = not in_single
            buff.append(c)
            i += 1
            continue
        if c == '"' and not in_single:
            in_double = not in_double
            buff.append(c)
            i += 1
            continue

        if c == ";" and not in_single and not in_double:
            stmt = "".join(buff).strip()
            if stmt:
                statements.append(stmt)
            buff = []
            i += 1
            continue

        buff.append(c)
        i += 1

    tail = "".join(buff).strip()
    if tail:
        statements.append(tail)
    return statements


def _exec_statement(
    *,
    statement_url: str,
    token: str,
    statement: str,
    role: str | None,
    database: str | None,
    schema: str | None,
    store: str | None,
    insecure: bool,
) -> dict:
    stmt = statement.strip()
    if not stmt.endswith(";"):
        stmt = f"{stmt};"

    payload = {"statement": statement}
    payload["statement"] = stmt
    if role:
        payload["role"] = role
    if database:
        payload["database"] = database
    if schema:
        payload["schema"] = schema
    if store:
        payload["store"] = store
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


def _run_sql_file(
    *,
    path: Path,
    statement_url: str,
    token: str,
    role: str | None,
    database: str | None,
    schema: str | None,
    store: str | None,
    insecure: bool,
) -> None:
    if not path.exists():
        raise SystemExit(f"missing sql file: {path}")

    raw = path.read_text()
    replaced = raw.replace("aws_returns_kafka_store", store) if store else raw
    statements = _split_sql_statements(replaced)
    if not statements:
        print(f"[skip] {path.name}: no executable statements")
        return

    print(f"[run] {path.name}: {len(statements)} statements")
    for idx, stmt in enumerate(statements, start=1):
        preview = " ".join(stmt.split())[:110]
        print(f"  [{idx}/{len(statements)}] {preview}")
        try:
            res = _exec_statement(
                statement_url=statement_url,
                token=token,
                statement=stmt,
                role=role,
                database=database,
                schema=schema,
                store=store,
                insecure=insecure,
            )
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            raise SystemExit(
                f"failed at {path.name} statement {idx}: HTTP {e.code}\n"
                f"statement: {preview}\n"
                f"response: {err}"
            )
        except Exception as e:  # noqa: BLE001
            raise SystemExit(
                f"failed at {path.name} statement {idx}: {type(e).__name__}: {e}\n"
                f"statement: {preview}"
            )

        sql_state = (res.get("sqlState") or "").upper()
        if sql_state and sql_state not in {"00000", "SUCCESS", "OK"}:
            msg = (res.get("message") or "unknown error").strip()
            stmt_u = stmt.upper()
            # Idempotent tolerance: CREATE ... IF NOT EXISTS can still return
            # already-exists errors (e.g., query.name collisions on reruns).
            if "IF NOT EXISTS" in stmt_u and "already exists" in msg.lower():
                print(
                    f"  [skip-existing] {path.name} statement {idx}: {msg}",
                    flush=True,
                )
                continue
            raise SystemExit(
                f"failed at {path.name} statement {idx}: sqlState={sql_state} message={msg}\n"
                f"statement: {preview}"
            )
    print(f"[done] {path.name}")


def _regenerate_load_sql(store: str) -> None:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "build_insert_entity_sql.py"),
        "--store",
        store,
        "--out",
        str(DELTASTREAM_DIR / "02_load_seed_data.sql"),
    ]
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Run DeltaStream benchmark setup in one command. "
            "Default executes steps 01, 02, 03; 04 and 05 are optional flags."
        )
    )
    ap.add_argument("--token", default=None, help="DeltaStream API token (defaults to DELTASTREAM_API_TOKEN env)")
    ap.add_argument("--server", required=True, help="DeltaStream API server base URL, e.g. https://api.deltastream.io")
    ap.add_argument("--store-name", required=True, help="Existing DeltaStream Kafka store name")
    ap.add_argument("--role", default="sysadmin")
    ap.add_argument("--database", default="aws_returns_bench")
    ap.add_argument("--schema", default="public")
    ap.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for DeltaStream API calls",
    )
    ap.add_argument("--run-verify", action="store_true", help="Also execute 04_verify_setup.sql")
    ap.add_argument("--run-rbac", action="store_true", help="Also execute 05_rbac_and_tokens.sql")
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

    _run_sql_file(
        path=DELTASTREAM_DIR / "01_setup.sql",
        statement_url=statement_url,
        token=token,
        role=args.role,
        database=None,
        schema=None,
        store=args.store_name,
        insecure=insecure,
    )

    _run_sql_file(
        path=DELTASTREAM_DIR / "03_create_surfaces.sql",
        statement_url=statement_url,
        token=token,
        role=args.role,
        database=args.database,
        schema=args.schema,
        store=args.store_name,
        insecure=insecure,
    )

    _regenerate_load_sql(args.store_name)

    _run_sql_file(
        path=DELTASTREAM_DIR / "02_load_seed_data.sql",
        statement_url=statement_url,
        token=token,
        role=args.role,
        database=args.database,
        schema=args.schema,
        store=args.store_name,
        insecure=insecure,
    )

    if args.run_verify:
        _run_sql_file(
            path=DELTASTREAM_DIR / "04_verify_setup.sql",
            statement_url=statement_url,
            token=token,
            role=args.role,
            database=args.database,
            schema=args.schema,
            store=args.store_name,
            insecure=insecure,
        )
    else:
        print("[skip] 04_verify_setup.sql (pass --run-verify to execute)")

    if args.run_rbac:
        _run_sql_file(
            path=DELTASTREAM_DIR / "05_rbac_and_tokens.sql",
            statement_url=statement_url,
            token=token,
            role=args.role,
            database=args.database,
            schema=args.schema,
            store=args.store_name,
            insecure=insecure,
        )
    else:
        print("[skip] 05_rbac_and_tokens.sql (manual by default; pass --run-rbac to execute)")

    print("Setup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
