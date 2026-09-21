#!/usr/bin/env python3
import argparse
import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone

from kafka import KafkaProducer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke test Python -> Kafka publish path")
    p.add_argument("--bootstrap-servers", default=os.getenv("KAFKA_BOOTSTRAP_SERVERS"))
    p.add_argument("--username", default=os.getenv("KAFKA_USERNAME"))
    p.add_argument("--password", default=os.getenv("KAFKA_PASSWORD"))
    p.add_argument(
        "--topic",
        default=os.getenv("KAFKA_TOPIC", "demo_pm_gamma"),
    )
    p.add_argument(
        "--sasl-mechanism",
        default=os.getenv("KAFKA_SASL_MECHANISM", "SCRAM-SHA-512"),
        choices=["SCRAM-SHA-256", "SCRAM-SHA-512", "PLAIN"],
    )
    p.add_argument("--key", default=f"smoke-{uuid.uuid4()}")
    p.add_argument("--timeout", type=int, default=20)
    return p.parse_args()


def require(name: str, value: str | None) -> str:
    if value:
        return value
    raise ValueError(f"Missing required value: {name}")


def build_payload(topic: str, key: str) -> dict:
    return {
        "type": "kafka_smoke_test",
        "topic": topic,
        "key": key,
        "host": socket.gethostname(),
        "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nonce": str(uuid.uuid4()),
    }


def main() -> int:
    args = parse_args()

    bootstrap = require("KAFKA_BOOTSTRAP_SERVERS", args.bootstrap_servers)
    username = require("KAFKA_USERNAME", args.username)
    password = require("KAFKA_PASSWORD", args.password)
    topic = require("KAFKA_TOPIC", args.topic)

    payload = build_payload(topic, args.key)

    producer = KafkaProducer(
        bootstrap_servers=bootstrap,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
        security_protocol="SASL_SSL",
        sasl_mechanism=args.sasl_mechanism,
        sasl_plain_username=username,
        sasl_plain_password=password,
        request_timeout_ms=args.timeout * 1000,
    )

    start = time.time()
    try:
        future = producer.send(topic, key=args.key, value=payload)
        metadata = future.get(timeout=args.timeout)
        producer.flush(timeout=args.timeout)
    finally:
        producer.close()

    elapsed_ms = int((time.time() - start) * 1000)

    print("Kafka smoke test succeeded")
    print(f"  topic: {topic}")
    print(f"  key: {args.key}")
    print(f"  partition: {metadata.partition}")
    print(f"  offset: {metadata.offset}")
    print(f"  elapsed_ms: {elapsed_ms}")
    print(f"  payload: {json.dumps(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
