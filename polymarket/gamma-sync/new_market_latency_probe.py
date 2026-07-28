#!/usr/bin/env python3
"""Measure how long a newly *created* Polymarket market takes to appear on Kafka.

Flow:
  1. Start a Kafka consumer on the target topic (default demo_pm_gamma),
     manually assigned and seeked to end so only arrivals AFTER probe start count.
  2. Poll the Gamma keyset API for the newest *open* markets, cache-busting every
     request (a unique `_cb` param) so Cloudflare cannot serve a response up to 5
     minutes stale. Detection is ordered by --detect-order (default updatedAt,
     because the createdAt-ordered feed is batch-delayed by minutes); a market is
     "new" the first time its conditionId is seen AND its createdAt is after the
     probe start.
  3. The first time a conditionId is seen in Gamma after startup, record
     `api_first_seen_ts` plus the market's `createdAt`.
  4. When that same conditionId first arrives on Kafka, record `kafka_arrival_ts`
     and compute two latencies:
        - PRIMARY   latency_from_api_detect_ms = kafka_arrival - api_first_seen
                    ("once visible in Gamma, how long to reach Kafka")
        - SECONDARY latency_from_createdAt_ms  = kafka_arrival - createdAt
                    (upper bound; includes Gamma's own visibility delay, NOT pure
                     pipeline latency)

Join key is `conditionId`; the Lambda keys Kafka messages by conditionId.
Open markets only (closed=false), matching the demo_pm_gamma Lambda.
"""
import argparse
import json
import os
import statistics
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
import requests
from kafka import KafkaConsumer, TopicPartition


GAMMA_URL = "https://gamma-api.polymarket.com/markets/keyset"
DEFAULT_SECRET_ARN = os.getenv("SECRET_ARN", "")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Measure latency from new-market creation (Gamma) to Kafka arrival",
    )
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--secret-arn", default=DEFAULT_SECRET_ARN, required=not DEFAULT_SECRET_ARN)
    p.add_argument("--topic", default="demo_pm_gamma")
    p.add_argument("--sasl-mechanism", default="SCRAM-SHA-512")
    p.add_argument("--samples", type=int, default=5,
                   help="Stop after this many matched new markets")
    p.add_argument("--gamma-poll-seconds", type=float, default=2.0)
    p.add_argument("--timeout-minutes", type=float, default=30.0)
    p.add_argument("--limit", type=int, default=100,
                   help="Gamma keyset page size")
    p.add_argument("--pages-per-poll", type=int, default=3,
                   help="How many keyset pages to scan per poll cycle")
    p.add_argument(
        "--detect-order",
        default="updatedAt",
        choices=["updatedAt", "createdAt"],
        help="Gamma keyset sort used to DETECT a new market (first-seen "
             "conditionId). Default updatedAt: the createdAt-ordered feed is "
             "heavily CDN/batch-delayed (observed 10+ min stale), so it detects "
             "new markets far too late; the updatedAt feed surfaces newly created "
             "markets within seconds. The market's createdAt is still recorded "
             "for the secondary metric regardless of this setting.",
    )
    p.add_argument("--no-cache-bust", action="store_true",
                   help="Disable the _cb cache-busting param (NOT recommended: "
                        "Gamma is CDN-cached up to 5 minutes)")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Suppress per-poll status lines; only print matches and summary")
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
    return {"bootstrap_servers": bootstrap, "username": username, "password": password}


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
    # Manual assign + seek_to_end: avoid consumer-group auth and only observe
    # arrivals after the probe starts.
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
    if not args.quiet:
        print(f"consumer assigned to {args.topic} partitions {sorted(partitions)} (seek_to_end)")
    return consumer


def fetch_new_markets(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Fetch the newest open markets, cache-busting each page.

    Ordered by --detect-order (default updatedAt) so newly created markets are
    surfaced promptly; the createdAt-ordered feed is batch-delayed by minutes.
    """
    all_markets: list[dict[str, Any]] = []
    after_cursor: str | None = None
    for _ in range(args.pages_per_poll):
        params: dict[str, Any] = {
            "limit": args.limit,
            "order": args.detect_order,
            "ascending": "false",
            "closed": "false",
        }
        if after_cursor:
            params["after_cursor"] = after_cursor
        if not args.no_cache_bust:
            params["_cb"] = uuid.uuid4().hex
        resp = requests.get(GAMMA_URL, params=params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        markets = payload.get("markets", [])
        if not isinstance(markets, list):
            raise ValueError("Gamma payload field 'markets' must be a list")
        all_markets.extend(markets)
        after_cursor = payload.get("next_cursor")
        if not after_cursor or not markets:
            break
    return all_markets


def print_match(sample: dict[str, Any]) -> None:
    print(json.dumps({
        "conditionId": sample["conditionId"],
        "slug": sample.get("slug"),
        "createdAt": sample["createdAt"],
        "api_first_seen_ts": sample["api_first_seen_ts"],
        "kafka_arrival_ts": sample["kafka_arrival_ts"],
        "latency_from_api_detect_ms": sample["latency_from_api_detect_ms"],
        "latency_from_createdAt_ms": sample["latency_from_createdAt_ms"],
    }))


def summarize(values: list[int]) -> dict[str, float]:
    return {
        "count": len(values),
        "min_ms": min(values),
        "median_ms": statistics.median(values),
        "avg_ms": statistics.mean(values),
        "max_ms": max(values),
    }


def print_summary(samples: list[dict[str, Any]]) -> None:
    print("\nsummary:")
    print(json.dumps({
        # PRIMARY: once visible in Gamma -> on Kafka (true pipeline latency)
        "from_api_first_seen": summarize(
            [s["latency_from_api_detect_ms"] for s in samples]
        ),
        # SECONDARY: from market createdAt (includes Gamma visibility delay)
        "from_createdAt": summarize(
            [s["latency_from_createdAt_ms"] for s in samples]
        ),
    }, indent=2))


def main() -> int:
    args = parse_args()
    secret = get_secret(args.region, args.secret_arn)
    consumer = build_consumer(args, secret)

    # conditionId -> {createdAt, api_first_seen_dt, slug, question}
    detected: dict[str, dict[str, Any]] = {}
    arrived: dict[str, datetime] = {}     # conditionId -> first kafka arrival
    completed: set[str] = set()
    matched: list[dict[str, Any]] = []

    start = now_utc()
    next_poll_at = 0.0

    print(
        f"Starting new-market probe topic={args.topic} samples={args.samples} "
        f"poll={args.gamma_poll_seconds}s detect_order={args.detect_order} "
        f"cache_bust={not args.no_cache_bust} quiet={args.quiet} "
        f"(only markets CREATED after {start.isoformat()} are measured)"
    )

    def try_match(condition_id: str) -> None:
        if condition_id in completed:
            return
        if condition_id not in detected or condition_id not in arrived:
            return
        d = detected[condition_id]
        kafka_dt = arrived[condition_id]
        created_dt = parse_iso8601(str(d["createdAt"]))
        sample = {
            "conditionId": condition_id,
            "slug": d.get("slug"),
            "question": d.get("question"),
            "createdAt": d["createdAt"],
            "api_first_seen_ts": d["api_first_seen_dt"].isoformat(),
            "kafka_arrival_ts": kafka_dt.isoformat(),
            "latency_from_api_detect_ms": dt_to_ms(kafka_dt) - dt_to_ms(d["api_first_seen_dt"]),
            "latency_from_createdAt_ms": dt_to_ms(kafka_dt) - dt_to_ms(created_dt),
        }
        matched.append(sample)
        completed.add(condition_id)
        print_match(sample)

    try:
        while len(matched) < args.samples:
            if (now_utc() - start).total_seconds() > args.timeout_minutes * 60:
                print("Timed out before collecting requested samples")
                break

            # --- Gamma poll ---
            if time.monotonic() >= next_poll_at:
                try:
                    markets = fetch_new_markets(args)
                except Exception as exc:  # noqa: BLE001
                    if not args.quiet:
                        print(f"gamma poll error: {exc!r}")
                    markets = []
                api_detect_dt = now_utc()
                new_this_poll = 0
                for market in markets:
                    condition_id = market.get("conditionId")
                    created_at = market.get("createdAt")
                    if not condition_id or not created_at:
                        continue
                    condition_id = str(condition_id)
                    if condition_id in detected:
                        continue  # already first-seen
                    # Only count markets created AFTER we started, so we truly
                    # witness their first appearance (not pre-existing history).
                    try:
                        if parse_iso8601(str(created_at)) < start:
                            # still mark as detected so we don't spam, but skip metric
                            detected[condition_id] = {
                                "createdAt": created_at,
                                "api_first_seen_dt": api_detect_dt,
                                "slug": market.get("slug"),
                                "question": market.get("question"),
                                "pre_existing": True,
                            }
                            continue
                    except ValueError:
                        continue
                    detected[condition_id] = {
                        "createdAt": created_at,
                        "api_first_seen_dt": api_detect_dt,
                        "slug": market.get("slug"),
                        "question": market.get("question"),
                        "pre_existing": False,
                    }
                    new_this_poll += 1
                    print(
                        f"NEW conditionId={condition_id} createdAt={created_at} "
                        f"detect={api_detect_dt.strftime('%H:%M:%S.%f')[:-3]}Z "
                        f"slug={market.get('slug')}"
                    )
                    try_match(condition_id)
                    if len(matched) >= args.samples:
                        break
                if new_this_poll == 0 and markets and not args.quiet:
                    top = markets[0]
                    elapsed = int((now_utc() - start).total_seconds())
                    print(
                        f"[+{elapsed:3d}s] waiting... "
                        f"top createdAt={top.get('createdAt')} "
                        f"tracking={len(detected)}"
                    )
                next_poll_at = time.monotonic() + args.gamma_poll_seconds

            # --- Kafka drain ---
            records = consumer.poll(timeout_ms=500)
            for batch in records.values():
                for record in batch:
                    value = record.value
                    condition_id = value.get("conditionId")
                    if not condition_id:
                        continue
                    condition_id = str(condition_id)
                    if condition_id in arrived:
                        continue
                    arrived[condition_id] = now_utc()
                    # Only interesting if it's a market we flagged as newly created.
                    d = detected.get(condition_id)
                    if d and not d.get("pre_existing"):
                        try_match(condition_id)
                        if len(matched) >= args.samples:
                            break
                if len(matched) >= args.samples:
                    break
    finally:
        consumer.close()

    if matched:
        print_summary(matched)
        return 0
    print("No new-market matches collected.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
