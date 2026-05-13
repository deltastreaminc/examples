#!/usr/bin/env python3
"""Rebuild the benchmark answer key from the live customer_returns_context_mv.

This queries the materialized view via DeltaStream's /v2/statements REST endpoint
(using sysadmin token) and uses the resulting 317-row context (post-join) to
recompute expected outputs. This aligns the answer key with what the combined
agent actually sees, while raw agents (computing from full raw MVs) will
naturally diverge — producing the desired differential signal.

Requires env vars:
  DELTASTREAM_API_TOKEN   sysadmin (or any role with SELECT on the MV)
  DS_API_URL              defaults to https://api.local.deltastream.io/v2/statements
  DELTASTREAM_INSECURE=1  to disable TLS verification (local dev)
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
BENCH_DIR = ROOT / "benchmark"

sys.path.insert(0, str(ROOT / "scripts"))
from generate_seed_data import _compute_answer_key_from_ctx, _parse_iso  # noqa: E402


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if os.environ.get("DELTASTREAM_INSECURE") == "1":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("DELTASTREAM_API_TOKEN")
    if not token:
        raise RuntimeError("DELTASTREAM_API_TOKEN required")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _ds_select(sql: str) -> dict[str, Any]:
    url = os.environ.get("DS_API_URL", "https://api.local.deltastream.io/v2/statements")
    payload = {
        "statement": sql,
        "role": os.environ.get("DS_ROLE", "sysadmin"),
        "database": os.environ.get("DS_DB", "aws_returns_bench"),
        "schema": os.environ.get("DS_SCHEMA", "public"),
        "store": os.environ.get("DS_STORE", "docker_kafka"),
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=_auth_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120, context=_ssl_ctx()) as resp:
        return json.loads(resp.read().decode())


def _ds_fetch_partition(statement_id: str, partition: int) -> dict[str, Any]:
    base = os.environ.get("DS_API_URL", "https://api.local.deltastream.io/v2/statements")
    url = f"{base}/{statement_id}?partitionID={partition}"
    req = urllib.request.Request(url, headers=_auth_headers(), method="GET")
    with urllib.request.urlopen(req, timeout=120, context=_ssl_ctx()) as resp:
        return json.loads(resp.read().decode())


def _fetch_mv_rows() -> list[dict[str, Any]]:
    sql = (
        "SELECT refund_id, return_id, order_id, customer_id, customer_segment, "
        "region, return_reason, carrier, delivered_on_time, order_ts, shipment_ts, "
        "return_ts, refund_ts, return_amount_usd, refunded_amount_usd, "
        "refund_gap_usd, refund_lag_hours "
        "FROM aws_returns_bench.public.customer_returns_context_mv;"
    )
    resp = _ds_select(sql)
    cols = [c["name"] for c in resp["metadata"]["columns"]]
    partitions = resp["metadata"].get("partitionInfo", [])
    statement_id = resp["statementID"]
    out: list[dict[str, Any]] = []
    # Partition 0 is in the initial response payload.
    for row in resp.get("data", []):
        out.append(dict(zip(cols, row)))
    for idx in range(1, len(partitions)):
        part = _ds_fetch_partition(statement_id, idx)
        for row in part.get("data", []):
            out.append(dict(zip(cols, row)))
    return out


def _ts_to_iso(ts: str) -> str:
    """Convert 'YYYY-MM-DD HH:MM:SS.SSS' (UTC) into 'YYYY-MM-DDTHH:MM:SSZ'."""
    # Replace space with 'T', strip fractional seconds, append 'Z'.
    main = ts.split(".")[0].replace(" ", "T")
    return main + "Z"


def _build_ctx_rows(
    mv_rows: list[dict[str, Any]],
    shipments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ship_by_order = {s["order_id"]: s for s in shipments}
    ctx: list[dict[str, Any]] = []
    for r in mv_rows:
        sh = ship_by_order.get(r["order_id"], {})
        delivered_days = int(sh.get("delivered_days", 0))
        promised_days = int(sh.get("promised_days", 0))
        return_amount = float(r["return_amount_usd"])
        refunded_amount = float(r["refunded_amount_usd"])
        refund_gap = float(r["refund_gap_usd"])
        return_ts_iso = _ts_to_iso(str(r["return_ts"]))
        refund_ts_iso = _ts_to_iso(str(r["refund_ts"])) if r.get("refund_ts") else None
        delivered_on_time = str(r["delivered_on_time"]).lower() == "true"
        ctx.append(
            {
                "customer_id": r["customer_id"],
                "customer_segment": r["customer_segment"],
                "region": r["region"],
                "carrier": r["carrier"],
                "order_amount_usd": return_amount,  # not used by aggregator
                "return_amount_usd": return_amount,
                "refunded_amount_usd": refunded_amount,
                "refund_gap_usd": refund_gap,
                "return_reason": r["return_reason"],
                "delivered_on_time": delivered_on_time,
                "return_ts": return_ts_iso,
                "refund_ts": refund_ts_iso,
                "refund_lag_hours": float(r["refund_lag_hours"]),
                "is_unpaid": refund_gap > 0.01,
                "delivery_slip_days": max(delivered_days - promised_days, 0),
            }
        )
    return ctx


def main() -> int:
    existing = BENCH_DIR / "answer_key_candidates.json"
    if not existing.exists():
        raise RuntimeError(f"missing {existing} (need anchor_ts_utc)")
    prev = json.loads(existing.read_text())
    anchor_str = prev.get("dataset", {}).get("anchor_ts_utc")
    if not anchor_str:
        raise RuntimeError("missing anchor_ts_utc in answer_key_candidates.json")
    anchor_ts: datetime = _parse_iso(anchor_str)

    mv_rows = _fetch_mv_rows()
    print(f"fetched {len(mv_rows)} rows from customer_returns_context_mv")
    shipments = _read_jsonl(DATA_DIR / "shipments.jsonl")
    ctx_rows = _build_ctx_rows(mv_rows, shipments)
    print(f"built {len(ctx_rows)} ctx_rows (anchor={anchor_str})")

    answer_key = _compute_answer_key_from_ctx(ctx_rows, anchor_ts)

    prompts = [
        {
            "prompt_id": p["prompt_id"],
            "title": p["title"],
            "text": p["text"],
            "kind": p["kind"],
            "top_k": p["top_k"],
        }
        for p in answer_key["prompts"]
    ]

    (BENCH_DIR / "prompts_candidates.json").write_text(json.dumps(prompts, indent=2))
    (BENCH_DIR / "answer_key_candidates.json").write_text(json.dumps(answer_key, indent=2))

    print("wrote benchmark/prompts_candidates.json and benchmark/answer_key_candidates.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
