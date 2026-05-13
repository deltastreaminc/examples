#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from generate_seed_data import _compute_answer_key, _parse_iso


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
BENCH_DIR = ROOT / "benchmark"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def main() -> int:
    anchor_ts = None
    existing = BENCH_DIR / "answer_key_candidates.json"
    if existing.exists():
        prev = json.loads(existing.read_text())
        anchor = prev.get("dataset", {}).get("anchor_ts_utc")
        if anchor:
            anchor_ts = _parse_iso(anchor)

    if anchor_ts is None:
        raise RuntimeError("missing anchor_ts_utc in benchmark/answer_key_candidates.json")

    orders = _read_jsonl(DATA_DIR / "orders.jsonl")
    shipments = _read_jsonl(DATA_DIR / "shipments.jsonl")
    returns = _read_jsonl(DATA_DIR / "returns.jsonl")
    refunds = _read_jsonl(DATA_DIR / "refunds.jsonl")

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

    print("recomputed benchmark answer key from data/*.jsonl")
    print(f"wrote {BENCH_DIR / 'prompts_candidates.json'}")
    print(f"wrote {BENCH_DIR / 'answer_key_candidates.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
