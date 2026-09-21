#!/usr/bin/env python3
import argparse
import json
import os
import statistics
import time
import uuid
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import boto3
import requests
from kafka import KafkaConsumer, TopicPartition


GAMMA_URL = "https://gamma-api.polymarket.com/markets/keyset"
DEFAULT_SECRET_ARN = os.getenv("SECRET_ARN", "")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Measure latency from Gamma API updates to Kafka arrival"
    )
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--secret-arn", default=DEFAULT_SECRET_ARN, required=not DEFAULT_SECRET_ARN)
    p.add_argument("--topic", default="demo_pm_gamma")
    p.add_argument("--sasl-mechanism", default="SCRAM-SHA-512")
    p.add_argument("--samples", type=int, default=5)
    p.add_argument("--gamma-poll-seconds", type=float, default=2.0)
    p.add_argument("--timeout-minutes", type=float, default=30.0)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument(
        "--order-field",
        default="updatedAt",
        choices=["updatedAt", "createdAt"],
        help="Gamma keyset sort field used by the API poller",
    )
    p.add_argument(
        "--pages-per-poll",
        type=int,
        default=5,
        help="How many Gamma keyset pages to scan per poll cycle",
    )
    p.add_argument(
        "--mode",
        default="new-condition",
        choices=["new-condition", "updated-at-change"],
        help="new-condition: first time a conditionId appears in the poller after startup; updated-at-change: first time an observed conditionId gets a new updatedAt while the probe is running",
    )
    return p.parse_args()


def parse_iso8601(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def now_utc() -> datetime:
    return datetime.now(UTC)


def dt_to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def get_secret(region: str, secret_arn: str) -> dict[str, str]:
    client = boto3.client("secretsmanager", region_name=region)
    resp = client.get_secret_value(SecretId=secret_arn)
    payload = json.loads(resp.get("SecretString", "{}"))
    bootstrap = payload.get("bootstrap_servers")
    username = payload.get("username")
    password = payload.get("password")
    if not bootstrap or not username or not password:
        raise ValueError(
            "Kafka secret must contain bootstrap_servers, username, and password"
        )
    return {
        "bootstrap_servers": bootstrap,
        "username": username,
        "password": password,
    }


def build_consumer(args: argparse.Namespace, secret: dict[str, str]) -> KafkaConsumer:
    consumer = KafkaConsumer(
        bootstrap_servers=secret["bootstrap_servers"],
        security_protocol="SASL_SSL",
        sasl_mechanism=args.sasl_mechanism,
        sasl_plain_username=secret["username"],
        sasl_plain_password=secret["password"],
        group_id=None,
        enable_auto_commit=False,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        consumer_timeout_ms=1000,
    )

    # Avoid consumer-group auth requirements by manually assigning partitions and
    # seeking to end. This way the probe only observes arrivals after it starts.
    deadline = time.monotonic() + 15
    partitions: set[int] | None = None
    while time.monotonic() < deadline:
        partitions = consumer.partitions_for_topic(args.topic)
        if partitions:
            break
        time.sleep(0.5)
    if not partitions:
        raise RuntimeError(f"Could not discover partitions for topic {args.topic}")

    topic_partitions = [TopicPartition(args.topic, p) for p in sorted(partitions)]
    consumer.assign(topic_partitions)
    consumer.seek_to_end(*topic_partitions)
    return consumer


def fetch_gamma(args: argparse.Namespace) -> tuple[list[dict[str, Any]], datetime | None]:
    params = {
        "limit": args.limit,
        "order": args.order_field,
        "ascending": "false",
        "closed": "false",
    }
    resp = requests.get(GAMMA_URL, params=params, timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        raise ValueError("Gamma payload field 'markets' must be a list")
    header_date = resp.headers.get("Date")
    header_dt = None
    if header_date:
        try:
            header_dt = parsedate_to_datetime(header_date).astimezone(UTC)
        except Exception:
            header_dt = None
    return markets, header_dt


def fetch_gamma_pages(args: argparse.Namespace) -> tuple[list[dict[str, Any]], datetime | None]:
    """Fetch a deeper rolling slice of the newest open Gamma markets.

    We page keyset results so the probe's notion of "first seen in Gamma" isn't
    limited to only the top-N records. This reduces false late-detection when a
    record is new but temporarily displaced from the very top of the feed.
    """
    all_markets: list[dict[str, Any]] = []
    header_dt: datetime | None = None
    after_cursor: str | None = None

    for _ in range(args.pages_per_poll):
        params = {
            "limit": args.limit,
            "order": args.order_field,
            "ascending": "false",
            "closed": "false",
        }
        if after_cursor:
            params["after_cursor"] = after_cursor
        resp = requests.get(GAMMA_URL, params=params, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        markets = payload.get("markets", [])
        if not isinstance(markets, list):
            raise ValueError("Gamma payload field 'markets' must be a list")
        if header_dt is None:
            header_date = resp.headers.get("Date")
            if header_date:
                try:
                    header_dt = parsedate_to_datetime(header_date).astimezone(UTC)
                except Exception:
                    header_dt = None
        all_markets.extend(markets)
        after_cursor = payload.get("next_cursor")
        if not after_cursor or not markets:
            break

    return all_markets, header_dt


def describe_latency(ms: int) -> str:
    return f"{ms} ms"


def print_match(sample: dict[str, Any]) -> None:
    print(
        json.dumps(
            {
                "conditionId": sample["conditionId"],
                "updatedAt": sample["updatedAt"],
                "question": sample["question"],
                "api_detect_ts": sample["api_detect_ts"],
                "kafka_arrival_ts": sample["kafka_arrival_ts"],
                "latency_from_api_detect_ms": sample["latency_from_api_detect_ms"],
                "latency_from_gamma_updatedAt_ms": sample[
                    "latency_from_gamma_updatedAt_ms"
                ],
            }
        )
    )


def print_summary(samples: list[dict[str, Any]]) -> None:
    detect_latencies = [s["latency_from_api_detect_ms"] for s in samples]
    gamma_latencies = [s["latency_from_gamma_updatedAt_ms"] for s in samples]

    def summarize(values: list[int]) -> dict[str, float]:
        return {
            "count": len(values),
            "min_ms": min(values),
            "median_ms": statistics.median(values),
            "avg_ms": statistics.mean(values),
            "max_ms": max(values),
        }

    print("summary:")
    print(json.dumps({
        "from_api_detect": summarize(detect_latencies),
        "from_gamma_updatedAt": summarize(gamma_latencies),
    }, indent=2))


def main() -> int:
    args = parse_args()
    secret = get_secret(args.region, args.secret_arn)
    consumer = build_consumer(args, secret)

    detected: dict[str, dict[str, Any]] = {}
    seen_condition_ids: set[str] = set()
    last_seen_updated_at: dict[str, str] = {}
    arrived: dict[str, datetime] = {}
    completed: set[str] = set()
    matched: list[dict[str, Any]] = []

    start = now_utc()
    next_poll_at = 0.0

    print(
        f"Starting probe mode={args.mode} order={args.order_field} topic={args.topic} samples={args.samples} poll={args.gamma_poll_seconds}s "
        f"(consumer starts from current end via seek_to_end)"
    )

    try:
        while len(matched) < args.samples:
            if (now_utc() - start).total_seconds() > args.timeout_minutes * 60:
                print("Timed out before collecting requested samples")
                break

            now_monotonic = time.monotonic()
            if now_monotonic >= next_poll_at:
                markets, header_dt = fetch_gamma_pages(args)
                if markets:
                    top = markets[0]
                    print(
                        f"gamma_top conditionId={top.get('conditionId')} updatedAt={top.get('updatedAt')}"
                    )
                api_detect_dt = now_utc()
                for market in markets:
                    condition_id = market.get("conditionId")
                    updated_at = market.get("updatedAt")
                    question = market.get("question")
                    if not condition_id or not updated_at:
                        continue
                    condition_id = str(condition_id)
                    updated_at = str(updated_at)
                    previous_updated_at = last_seen_updated_at.get(condition_id)
                    should_detect = False

                    if args.mode == "new-condition":
                        if condition_id not in seen_condition_ids:
                            should_detect = True
                            seen_condition_ids.add(condition_id)
                    else:
                        if previous_updated_at is None:
                            seen_condition_ids.add(condition_id)
                            last_seen_updated_at[condition_id] = updated_at
                            continue
                        if previous_updated_at != updated_at:
                            should_detect = True

                    last_seen_updated_at[condition_id] = updated_at
                    if not should_detect:
                        continue

                    gamma_dt = parse_iso8601(str(updated_at))
                    detected[condition_id] = {
                        "conditionId": condition_id,
                        "updatedAt": updated_at,
                        "question": question,
                        "api_detect_dt": api_detect_dt,
                        "api_detect_ts": api_detect_dt.isoformat(),
                        "http_date_ts": header_dt.isoformat() if header_dt else None,
                    }
                    if condition_id in arrived and condition_id not in completed:
                        kafka_dt = arrived[condition_id]
                        sample = {
                            **detected[condition_id],
                            "kafka_arrival_ts": kafka_dt.isoformat(),
                            "latency_from_api_detect_ms": dt_to_ms(kafka_dt)
                            - dt_to_ms(api_detect_dt),
                            "latency_from_gamma_updatedAt_ms": dt_to_ms(kafka_dt)
                            - dt_to_ms(gamma_dt),
                        }
                        matched.append(sample)
                        completed.add(condition_id)
                        print_match(sample)
                        if len(matched) >= args.samples:
                            break
                next_poll_at = now_monotonic + args.gamma_poll_seconds

            records = consumer.poll(timeout_ms=500)
            for batch in records.values():
                for record in batch:
                    value = record.value
                    condition_id = value.get("conditionId")
                    updated_at = value.get("updatedAt")
                    if not condition_id or not updated_at:
                        continue
                    condition_id = str(condition_id)
                    if condition_id in arrived:
                        continue
                    kafka_dt = now_utc()
                    arrived[condition_id] = kafka_dt
                    if condition_id in detected and condition_id not in completed:
                        api_detect_dt = detected[condition_id]["api_detect_dt"]
                        gamma_dt = parse_iso8601(str(updated_at))
                        sample = {
                            **detected[condition_id],
                            "kafka_arrival_ts": kafka_dt.isoformat(),
                            "latency_from_api_detect_ms": dt_to_ms(kafka_dt)
                            - dt_to_ms(api_detect_dt),
                            "latency_from_gamma_updatedAt_ms": dt_to_ms(kafka_dt)
                            - dt_to_ms(gamma_dt),
                        }
                        matched.append(sample)
                        completed.add(condition_id)
                        print_match(sample)
                        if len(matched) >= args.samples:
                            break
                if len(matched) >= args.samples:
                    break
    finally:
        consumer.close()

    if matched:
        print_summary(matched)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
