#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime, timedelta
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
BENCH_DIR = ROOT / "benchmark"


@dataclass
class Order:
    order_id: str
    customer_id: str
    customer_segment: str
    order_ts: str
    order_amount_usd: float
    region: str


@dataclass
class Shipment:
    shipment_id: str
    order_id: str
    carrier: str
    promised_days: int
    delivered_days: int
    delivered_on_time: bool
    shipment_ts: str


@dataclass
class Return:
    return_id: str
    order_id: str
    return_reason: str
    return_ts: str
    return_amount_usd: float


@dataclass
class Refund:
    refund_id: str
    return_id: str
    order_id: str
    refunded_amount_usd: float
    refund_ts: str
    refund_status: str


SEGMENTS = ["enterprise", "mid_market", "smb"]
REGIONS = ["na", "emea", "apac"]
REASONS = [
    "damaged",
    "wrong_item",
    "not_as_described",
    "late_delivery",
    "no_longer_needed",
]
CARRIERS = ["ups", "fedex", "dhl", "usps"]


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _f2(v: float) -> float:
    return float(f"{v:.2f}")


def _rows_for_window(
    rows: list[dict[str, Any]], ts_key: str, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        ts = _parse_iso(str(row[ts_key]))
        if start <= ts < end:
            out.append(row)
    return out


def _safe_ratio(num: float, den: float) -> float:
    if den == 0:
        return 0.0
    return num / den


def _ranked_rows(
    data: dict[str, dict[str, float]],
    key_name: str,
    metric_name: str,
    k: int,
    *,
    reverse: bool = True,
    extra: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for key, vals in data.items():
        row = {key_name: key, metric_name: _f2(float(vals[metric_name]))}
        if extra:
            for out_key, src_key in extra.items():
                row[out_key] = _f2(float(vals[src_key]))
        rows.append(row)
    rows.sort(key=lambda r: r[metric_name], reverse=reverse)
    ranked = []
    for i, row in enumerate(rows[:k], start=1):
        ranked.append({"rank": i, **row})
    return ranked


def _compute_answer_key(
    orders: list[dict[str, Any]],
    shipments: list[dict[str, Any]],
    returns: list[dict[str, Any]],
    refunds: list[dict[str, Any]],
    anchor_ts: datetime,
) -> dict[str, Any]:
    order_by_id = {o["order_id"]: o for o in orders}
    shipment_by_order = {s["order_id"]: s for s in shipments}
    refunds_by_return: dict[str, list[dict[str, Any]]] = {}
    for refund in refunds:
        refunds_by_return.setdefault(refund["return_id"], []).append(refund)

    ctx_rows: list[dict[str, Any]] = []
    for r in returns:
        o = order_by_id.get(r["order_id"])
        if not o:
            continue
        sh = shipment_by_order.get(o["order_id"], {})
        refund_rows = refunds_by_return.get(r["return_id"], [])
        refunded = sum(x["refunded_amount_usd"] for x in refund_rows)
        refund_ts = None
        if refund_rows:
            refund_ts = max(_parse_iso(x["refund_ts"]) for x in refund_rows)
        return_ts = _parse_iso(r["return_ts"])
        lag_hours = (refund_ts - return_ts).total_seconds() / 3600.0 if refund_ts else 0.0
        delivered_days = int(sh.get("delivered_days", 0))
        promised_days = int(sh.get("promised_days", 0))
        ctx_rows.append(
            {
                "customer_id": o["customer_id"],
                "customer_segment": o["customer_segment"],
                "region": o["region"],
                "carrier": sh.get("carrier", "unknown"),
                "order_amount_usd": float(o["order_amount_usd"]),
                "return_amount_usd": float(r["return_amount_usd"]),
                "refunded_amount_usd": float(refunded),
                "refund_gap_usd": float(r["return_amount_usd"] - refunded),
                "return_reason": r["return_reason"],
                "delivered_on_time": bool(sh.get("delivered_on_time", True)),
                "return_ts": r["return_ts"],
                "refund_ts": _iso(refund_ts) if refund_ts else None,
                "refund_lag_hours": float(lag_hours),
                "is_unpaid": float(r["return_amount_usd"] - refunded) > 0.01,
                "delivery_slip_days": max(delivered_days - promised_days, 0),
            }
        )

    return _compute_answer_key_from_ctx(ctx_rows, anchor_ts)


def _compute_answer_key_from_ctx(
    ctx_rows: list[dict[str, Any]],
    anchor_ts: datetime,
) -> dict[str, Any]:
    last_24h_start = anchor_ts - timedelta(hours=24)
    last_7d_start = anchor_ts - timedelta(days=7)
    prev_7d_start = anchor_ts - timedelta(days=14)
    prev_7d_end = anchor_ts - timedelta(days=7)

    rows_24h = _rows_for_window(ctx_rows, "return_ts", last_24h_start, anchor_ts)
    rows_7d = _rows_for_window(ctx_rows, "return_ts", last_7d_start, anchor_ts)
    rows_prev_7d = _rows_for_window(ctx_rows, "return_ts", prev_7d_start, prev_7d_end)

    def agg(rows: list[dict[str, Any]], dim: str) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for row in rows:
            key = str(row[dim])
            s = out.setdefault(
                key,
                {
                    "refund_gap_usd": 0.0,
                    "return_amount_usd": 0.0,
                    "refunded_amount_usd": 0.0,
                    "returns_count": 0.0,
                    "refund_lag_hours": 0.0,
                    "unpaid_returns": 0.0,
                    "late_returns": 0.0,
                    "delivery_slip_days": 0.0,
                },
            )
            s["refund_gap_usd"] += float(row["refund_gap_usd"])
            s["return_amount_usd"] += float(row["return_amount_usd"])
            s["refunded_amount_usd"] += float(row["refunded_amount_usd"])
            s["returns_count"] += 1.0
            s["refund_lag_hours"] += float(row["refund_lag_hours"])
            s["unpaid_returns"] += 1.0 if row["is_unpaid"] else 0.0
            s["late_returns"] += 0.0 if row["delivered_on_time"] else 1.0
            s["delivery_slip_days"] += float(row["delivery_slip_days"])
        for vals in out.values():
            count = max(vals["returns_count"], 1.0)
            vals["avg_refund_lag_hours"] = vals["refund_lag_hours"] / count
            vals["refund_coverage_ratio"] = _safe_ratio(
                vals["refunded_amount_usd"], vals["return_amount_usd"]
            )
            vals["late_delivery_return_rate"] = _safe_ratio(vals["late_returns"], vals["returns_count"])
            vals["unpaid_rate"] = _safe_ratio(vals["unpaid_returns"], vals["returns_count"])
            vals["avg_delivery_slip_days"] = vals["delivery_slip_days"] / count
        return out

    seg_7d = agg(rows_7d, "customer_segment")
    seg_prev_7d = agg(rows_prev_7d, "customer_segment")
    region_7d = agg(rows_7d, "region")
    reason_7d = agg(rows_7d, "return_reason")
    reason_prev_7d = agg(rows_prev_7d, "return_reason")
    customer_24h = agg(rows_24h, "customer_id")

    prompts: list[dict[str, Any]] = []

    def add_rank_prompt(
        prompt_id: int,
        title: str,
        text: str,
        expected_rows: list[dict[str, Any]],
        exact_fields: list[str],
        numeric_fields: list[str],
        *,
        abs_tol: float = 1.0,
        rel_tol: float = 0.01,
        raw_vs_combined_note: str = "",
        raw_outcome: str = "fails",
        why_raw: str = "",
        why_combined: str = "",
    ) -> None:
        prompts.append(
            {
                "prompt_id": prompt_id,
                "title": title,
                "text": text,
                "kind": "ranked",
                "top_k": len(expected_rows),
                "expected_rows": expected_rows,
                "exact_fields": exact_fields,
                "numeric_fields": numeric_fields,
                "abs_tol": abs_tol,
                "rel_tol": rel_tol,
                "raw_vs_combined_note": raw_vs_combined_note,
                "raw_outcome": raw_outcome,
                "why_raw": why_raw,
                "why_combined": why_combined,
            }
        )

    def add_scalar_prompt(
        prompt_id: int,
        title: str,
        text: str,
        expected_rows: list[dict[str, Any]],
        exact_fields: list[str],
        numeric_fields: list[str],
        *,
        abs_tol: float = 1.0,
        rel_tol: float = 0.01,
        raw_vs_combined_note: str = "",
        raw_outcome: str = "fails",
        why_raw: str = "",
        why_combined: str = "",
    ) -> None:
        prompts.append(
            {
                "prompt_id": prompt_id,
                "title": title,
                "text": text,
                "kind": "scalar",
                "top_k": 1,
                "expected_rows": expected_rows,
                "exact_fields": exact_fields,
                "numeric_fields": numeric_fields,
                "abs_tol": abs_tol,
                "rel_tol": rel_tol,
                "raw_vs_combined_note": raw_vs_combined_note,
                "raw_outcome": raw_outcome,
                "why_raw": why_raw,
                "why_combined": why_combined,
            }
        )

    for seg, vals in seg_7d.items():
        vals["refund_gap_delta_7d"] = vals["refund_gap_usd"] - seg_prev_7d.get(seg, {}).get(
            "refund_gap_usd", 0.0
        )
    for reason, vals in reason_7d.items():
        vals["returns_count_delta_7d"] = vals["returns_count"] - reason_prev_7d.get(reason, {}).get(
            "returns_count", 0.0
        )

    # s1 — single-table filter baseline (raw passes).
    add_rank_prompt(
        1,
        "Top customers by 24h refund gap",
        "Return JSON only as {\"decisions\":[...]}. Rank top 5 customers by refund_gap_usd in last_24h. Include rank, customer_id, refund_gap_usd.",
        _ranked_rows(customer_24h, "customer_id", "refund_gap_usd", 5),
        ["rank", "customer_id"],
        ["refund_gap_usd"],
        raw_vs_combined_note="Single-table slice; both surfaces pass.",
        raw_outcome="passes",
        why_raw="refund_gap_usd is already a per-row column on refunds_raw_mv, so the agent only needs a refund_ts window filter plus ORDER BY ... LIMIT 5. No joins or derived metrics.",
        why_combined="Same operation against the pre-joined context view; faster and cheaper because the join and window are already materialized.",
    )

    # s2 — derived window-delta with segment join (raw fails).
    add_rank_prompt(
        2,
        "Top segments by 7d refund gap delta",
        "Return JSON only as {\"decisions\":[...]}. Rank top 3 customer segments by refund_gap_delta_7d (last_7d minus prev_7d). Include rank, customer_segment, refund_gap_delta_7d.",
        _ranked_rows(seg_7d, "customer_segment", "refund_gap_delta_7d", 3),
        ["rank", "customer_segment"],
        ["refund_gap_delta_7d"],
        raw_vs_combined_note="Window-delta + segment join; raw fails.",
        why_raw="Must join refunds<->returns<->orders to attach customer_segment, bucket each row into last_7d vs prev_7d, sum per segment, then subtract — multi-step arithmetic that raw agents routinely get wrong.",
        why_combined="refund_gap_usd and customer_segment are pre-joined per record; the agent only sums and subtracts.",
    )

    # s3 — derived per-group average with region join (raw fails).
    add_rank_prompt(
        3,
        "Top regions by 7d avg refund lag",
        "Return JSON only as {\"decisions\":[...]}. Rank top 3 regions by avg_refund_lag_hours in last_7d. Include rank, region, avg_refund_lag_hours.",
        _ranked_rows(region_7d, "region", "avg_refund_lag_hours", 3),
        ["rank", "region"],
        ["avg_refund_lag_hours"],
        abs_tol=0.25,
        raw_vs_combined_note="Per-region average requiring sum/count discipline under a join; raw fails.",
        why_raw="region lives on orders, forcing a join; computing avg = sum(refund_lag_hours) / count(returns) under a join routinely produces off-by-row denominators.",
        why_combined="region and refund_lag_hours are joined per record; the agent computes one ratio per group.",
    )

    # s4 — scalar two-window boolean (raw fails; Haiku occasionally flips boolean on combined).
    add_scalar_prompt(
        4,
        "Systemic gap worsened flag",
        "Return JSON only as {\"decisions\":[...]}. Provide one object with fields has_systemic_refund_gap_worsened, refund_gap_usd_7d, refund_gap_usd_prev_7d, refund_gap_delta_7d. Use return_ts (NOT refund_ts or order_ts) to assign each record to last_7d vs prev_7d. Set has_systemic_refund_gap_worsened=true when refund_gap_usd_7d > refund_gap_usd_prev_7d.",
        [
            {
                "has_systemic_refund_gap_worsened": sum(v["refund_gap_usd"] for v in seg_7d.values())
                > sum(v["refund_gap_usd"] for v in seg_prev_7d.values()),
                "refund_gap_usd_7d": _f2(sum(v["refund_gap_usd"] for v in seg_7d.values())),
                "refund_gap_usd_prev_7d": _f2(
                    sum(v["refund_gap_usd"] for v in seg_prev_7d.values())
                ),
                "refund_gap_delta_7d": _f2(
                    sum(v["refund_gap_usd"] for v in seg_7d.values())
                    - sum(v["refund_gap_usd"] for v in seg_prev_7d.values())
                ),
            }
        ],
        ["has_systemic_refund_gap_worsened"],
        ["refund_gap_usd_7d", "refund_gap_usd_prev_7d", "refund_gap_delta_7d"],
        raw_vs_combined_note="Scalar derived boolean; raw fails, small models occasionally flip the boolean on combined.",
        why_raw="Requires summing across two windows joined from refunds<->returns<->orders, then producing a single boolean — two failure surfaces (wrong sums or inverted writeback).",
        why_combined="Pre-joined sums; only the boolean-writeback failure mode remains, which Haiku hits roughly 1 in 4 runs.",
    )

    # s5 — per-group ratio with multi-join and 0-1 fraction formatting (raw fails).
    add_rank_prompt(
        5,
        "Top segments by 7d late-delivery return rate",
        "Return JSON only as {\"decisions\":[...]}. Rank top 3 customer segments by late_delivery_return_rate in last_7d. Include rank, customer_segment, late_delivery_return_rate. Express late_delivery_return_rate as a decimal fraction between 0 and 1 (e.g. 0.52, NOT 52 or 52%).",
        _ranked_rows(seg_7d, "customer_segment", "late_delivery_return_rate", 3),
        ["rank", "customer_segment"],
        ["late_delivery_return_rate"],
        abs_tol=0.005,
        raw_vs_combined_note="Three-way join + ratio + 0-1 fraction formatting; raw fails.",
        why_raw="Must derive is_late_delivery from shipments vs SLA, attach customer_segment via orders, compute late/total ratio per segment, then emit as a decimal fraction — raw agents typically nail at most two of the three.",
        why_combined="is_late_delivery and customer_segment are precomputed per record; only the fraction-formatting discipline remains.",
    )

    # s6 — discrete window-delta with zero tolerance (raw fails on rank tiebreaks).
    add_rank_prompt(
        6,
        "Top reasons by 7d return-count delta",
        "Return JSON only as {\"decisions\":[...]}. Rank top 3 return reasons by returns_count_delta_7d (last_7d - prev_7d). Include rank, return_reason, returns_count_delta_7d.",
        _ranked_rows(reason_7d, "return_reason", "returns_count_delta_7d", 3),
        ["rank", "return_reason"],
        ["returns_count_delta_7d"],
        abs_tol=0.0,
        rel_tol=0.0,
        raw_vs_combined_note="Discrete window-delta with zero numeric tolerance; raw fails on rank tiebreaks.",
        why_raw="Strict-integer count delta (abs_tol=0) per return_reason; raw agents commonly mis-sort negative deltas (e.g. placing -4 above 0).",
        why_combined="Pre-joined counts; ranking error mostly disappears, though small models can still mis-order negatives.",
    )

    return {
        "schema_version": "1.0.0",
        "dataset": {
            "anchor_ts_utc": _iso(anchor_ts),
            "windows": {
                "last_24h_start": _iso(last_24h_start),
                "last_7d_start": _iso(last_7d_start),
                "prev_7d_start": _iso(prev_7d_start),
                "prev_7d_end": _iso(prev_7d_end),
            },
        },
        "prompts": prompts,
        "scenario_count": len(prompts),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders", type=int, default=1000)
    ap.add_argument("--customers", type=int, default=220)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--anchor-ts", default="2026-03-01T00:00:00Z")
    ap.add_argument("--out-of-order-rate", type=float, default=0.05)
    args = ap.parse_args()

    random.seed(args.seed)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BENCH_DIR.mkdir(parents=True, exist_ok=True)

    customer_ids = [f"cust_{i:04d}" for i in range(args.customers)]

    orders: list[dict[str, Any]] = []
    shipments: list[dict[str, Any]] = []
    returns: list[dict[str, Any]] = []
    refunds: list[dict[str, Any]] = []
    anchor_ts = _parse_iso(args.anchor_ts)
    start_ts = anchor_ts - timedelta(days=30)

    def jitter(ts: datetime) -> datetime:
        if random.random() < args.out_of_order_rate:
            return ts - timedelta(hours=random.randint(1, 36))
        return ts

    for i in range(args.orders):
        order_id = f"ord_{i:06d}"
        customer_id = random.choice(customer_ids)
        segment = random.choices(SEGMENTS, weights=[0.2, 0.35, 0.45], k=1)[0]
        region = random.choices(REGIONS, weights=[0.45, 0.3, 0.25], k=1)[0]
        order_amount = _f2(random.uniform(25, 1500))
        order_ts_dt = start_ts + timedelta(hours=random.randint(0, 30 * 24 - 1))
        orders.append(
            asdict(
                Order(
                    order_id=order_id,
                    customer_id=customer_id,
                    customer_segment=segment,
                    order_ts=_iso(jitter(order_ts_dt)),
                    order_amount_usd=order_amount,
                    region=region,
                )
            )
        )

        promised = random.choice([2, 3, 4, 5, 6])
        delivered = max(1, promised + random.choice([-1, 0, 0, 1, 2, 3]))
        on_time = delivered <= promised
        shipment_ts_dt = order_ts_dt + timedelta(days=delivered)
        shipments.append(
            asdict(
                Shipment(
                    shipment_id=f"shp_{i:06d}",
                    order_id=order_id,
                    carrier=random.choice(CARRIERS),
                    promised_days=promised,
                    delivered_days=delivered,
                    delivered_on_time=on_time,
                    shipment_ts=_iso(jitter(shipment_ts_dt)),
                )
            )
        )

        if random.random() < 0.34:
            ret_amount = _f2(order_amount * random.uniform(0.3, 1.0))
            ret_id = f"ret_{i:06d}"
            return_ts_dt = shipment_ts_dt + timedelta(days=random.randint(0, 10))
            returns.append(
                asdict(
                    Return(
                        return_id=ret_id,
                        order_id=order_id,
                        return_reason=random.choice(REASONS),
                        return_ts=_iso(jitter(return_ts_dt)),
                        return_amount_usd=ret_amount,
                    )
                )
            )

            status = random.choices(
                ["complete", "partial", "pending"], weights=[0.75, 0.2, 0.05], k=1
            )[0]
            if status == "complete":
                refunded = ret_amount
            elif status == "partial":
                refunded = _f2(ret_amount * random.uniform(0.4, 0.95))
            else:
                refunded = _f2(ret_amount * random.uniform(0.0, 0.2))

            refund_ts_dt = return_ts_dt + timedelta(hours=random.randint(4, 96))

            refunds.append(
                asdict(
                    Refund(
                        refund_id=f"rfd_{i:06d}",
                        return_id=ret_id,
                        order_id=order_id,
                        refunded_amount_usd=refunded,
                        refund_ts=_iso(jitter(refund_ts_dt)),
                        refund_status=status,
                    )
                )
            )

    _write_jsonl(DATA_DIR / "orders.jsonl", orders)
    _write_jsonl(DATA_DIR / "shipments.jsonl", shipments)
    _write_jsonl(DATA_DIR / "returns.jsonl", returns)
    _write_jsonl(DATA_DIR / "refunds.jsonl", refunds)

    answer_key = _compute_answer_key(orders, shipments, returns, refunds, anchor_ts)
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

    print(f"wrote {len(orders)} orders")
    print(f"wrote {len(shipments)} shipments")
    print(f"wrote {len(returns)} returns")
    print(f"wrote {len(refunds)} refunds")
    print(f"wrote {BENCH_DIR / 'prompts_candidates.json'}")
    print(f"wrote {BENCH_DIR / 'answer_key_candidates.json'}")
    print(f"scenarios: {answer_key['scenario_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
