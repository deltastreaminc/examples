#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from kafka import KafkaProducer


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


TOPIC_MAP = {
    "orders.jsonl": "aws_returns_orders",
    "shipments.jsonl": "aws_returns_shipments",
    "returns.jsonl": "aws_returns_returns",
    "refunds.jsonl": "aws_returns_refunds",
}


def _produce_file(producer: KafkaProducer, path: Path, topic: str) -> int:
    count = 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        producer.send(topic, value=payload)
        count += 1
    return count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", default="localhost:19092")
    args = ap.parse_args()

    producer = KafkaProducer(
        bootstrap_servers=args.bootstrap,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        linger_ms=10,
        acks="all",
    )

    for file_name, topic in TOPIC_MAP.items():
        path = DATA_DIR / file_name
        if not path.exists():
            raise SystemExit(f"missing {path}; run scripts/generate_seed_data.py first")
        rows = _produce_file(producer, path, topic)
        print(f"seeded {rows} rows to {topic}")

    producer.flush()
    producer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
