import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import boto3
import requests
from kafka import KafkaProducer


SSM_CURSOR_KEY = os.environ["SSM_CURSOR_KEY"]
KAFKA_SECRET_ARN = os.environ["KAFKA_SECRET_ARN"]
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "demo_pm_gamma")
KAFKA_SASL_MECHANISM = os.environ.get("KAFKA_SASL_MECHANISM", "SCRAM-SHA-512")
METRIC_NAMESPACE = os.environ.get("METRIC_NAMESPACE", "GammaSync")
# Optional DynamoDB lock table. When set (sub-minute deployment), each run
# releases the lock that the dispatcher acquired on its behalf.
LOCK_TABLE = os.environ.get("LOCK_TABLE")

GAMMA_URL = "https://gamma-api.polymarket.com/markets/keyset"
POLYMARKET_EPOCH = "2020-01-01T00:00:00Z"

# Incremental sync tuning. Defaults preserve the original v1 behavior
# (updatedAt ordering, both open and closed passes). The v2 net-new feed sets
# SYNC_ORDER_FIELD=createdAt and OPEN_ONLY=true so it only publishes newly
# created open markets once, instead of chasing the high-volume update stream.
SYNC_ORDER_FIELD = os.environ.get("SYNC_ORDER_FIELD", "updatedAt")
# Field on each market record used as the incremental cutoff. Defaults to the
# order field so cutoff and ordering stay consistent.
SYNC_TIMESTAMP_FIELD = os.environ.get("SYNC_TIMESTAMP_FIELD", SYNC_ORDER_FIELD)
OPEN_ONLY = os.environ.get("OPEN_ONLY", "false").lower() == "true"

# Safety lookback (seconds). Gamma makes newly created markets queryable only
# after their createdAt timestamp (observed ~10s+ of visibility lag). With a
# strict "createdAt >= watermark" cutoff, a market that becomes visible after
# the watermark has advanced past its createdAt is dropped forever. To avoid
# that, each run re-scans a trailing window: it publishes any record whose
# cutoff timestamp is >= (watermark - LOOKBACK_SECONDS). Re-published records
# are harmless because the topic is keyed by conditionId (upsert downstream).
# Default 0 preserves the original v1 updatedAt behavior; the v2 net-new feed
# sets a positive lookback that must exceed the API visibility lag.
LOOKBACK_SECONDS = int(os.environ.get("LOOKBACK_SECONDS", "0"))

# WarpStream producer tuning (overridable via env). Defaults mirror settings
# that improved throughput on WarpStream elsewhere:
#   kafka.producer.request.timeout.ms = 60000
#   kafka.producer.delivery.timeout.ms = 120000  (no kafka-python equivalent)
#   kafka.producer.linger.ms = 100
#   kafka.producer.batch.size = 1048576
PRODUCER_LINGER_MS = int(os.environ.get("PRODUCER_LINGER_MS", "100"))
PRODUCER_BATCH_SIZE = int(os.environ.get("PRODUCER_BATCH_SIZE", "1048576"))
PRODUCER_REQUEST_TIMEOUT_MS = int(os.environ.get("PRODUCER_REQUEST_TIMEOUT_MS", "60000"))
PRODUCER_ACKS = os.environ.get("PRODUCER_ACKS", "1")
if PRODUCER_ACKS not in ("all",):
    PRODUCER_ACKS = int(PRODUCER_ACKS)
# Compression cuts bytes sent to WarpStream (which commits batches to object
# storage), improving throughput. gzip is stdlib (no native wheel needed, so it
# is safe to build on any OS and run on Lambda's Linux runtime). lz4/snappy/zstd
# would need a Linux-built native lib bundled in the package.
PRODUCER_COMPRESSION = os.environ.get("PRODUCER_COMPRESSION", "gzip") or None
# Flush cadence in pages. 0 = only flush at end-of-run / checkpoint. A small
# positive value bounds producer buffer memory during long catch-up runs
# without the old per-page ack barrier.
FLUSH_EVERY_PAGES = int(os.environ.get("FLUSH_EVERY_PAGES", "25"))

# The Gamma keyset endpoint sits behind Cloudflare with
# `Cache-Control: public, max-age=300`, so plain requests can be served a
# response up to 5 MINUTES stale (cf-cache-status: HIT). That CDN staleness,
# not the pipeline, was the dominant source of latency and of the "feed frozen
# then dumps a huge batch" behavior. A unique query param per request forces a
# cache MISS so we always read fresh data (observed top-of-feed lag ~0-4s).
# `no-cache` request headers are ignored by the Cloudflare edge. Disable only if
# you intentionally want cached reads.
CACHE_BUST = os.environ.get("CACHE_BUST", "true").lower() == "true"
# Origin can be slower than the CDN, so allow a bit more time and a few retries.
GAMMA_TIMEOUT_S = int(os.environ.get("GAMMA_TIMEOUT_S", "20"))
GAMMA_MAX_RETRIES = int(os.environ.get("GAMMA_MAX_RETRIES", "3"))

# DEDUP mode (fast "recent updates" worker). When true, the worker publishes
# each conditionId only the FIRST time it is seen and skips it thereafter, using
# an in-memory cache across warm invocations. This is what makes the fast tail
# poller viable: the open updatedAt feed is mostly genuine re-price churn (every
# tick is a new updatedAt), so deduping on exact (conditionId, updatedAt) would
# not reduce volume. Skipping already-seen conditionIds collapses the fast feed
# to essentially new-markets-only, so it stays small enough for a 3s cadence.
# The full-view worker (DEDUP=false) still republishes all churn / reconciles.
# On a cold start the cache resets and the active set is re-published once over
# a few minutes (harmless: the topic is keyed by conditionId / upsert).
DEDUP = os.environ.get("DEDUP", "false").lower() == "true"
# Drop cached conditionIds not seen within this many seconds so the cache stays
# bounded; a market that goes quiet then reappears is re-published once.
DEDUP_TTL_SECONDS = int(os.environ.get("DEDUP_TTL_SECONDS", "3600"))
# Cap pages scanned per run (0 = unlimited). The fast recent worker only needs
# the freshest updates at the TOP of the updatedAt feed to catch new markets, so
# it scans a bounded number of pages regardless of how dense the churn is. This
# keeps each run fast (bounded HTTP) so it holds a ~3s cadence. Must cover the
# per-run gap: pages*limit should exceed updates-between-runs so a new market is
# not pushed below the scanned window before we see it.
MAX_PAGES_PER_RUN = int(os.environ.get("MAX_PAGES_PER_RUN", "0"))

# FULL_SWEEP mode: when true, the worker ignores the timestamp watermark cutoff
# and instead walks ALL pages until next_cursor is null, then resets the cursor
# to epoch so the next invocation re-sweeps from the beginning.
#
# Purpose: guarantees complete coverage of the full open-market catalog on every
# cycle. Requires a stable, immutable sort key (SYNC_ORDER_FIELD=createdAt or id)
# — mutable keys like updatedAt truncate non-deterministically and omit markets.
#
# With DEDUP_MODE=content_hash each sweep publishes only markets whose metadata
# has changed since the last publish (or that were never published), keeping
# steady-state Kafka volume low despite scanning the full catalog every cycle.
#
# On timeout mid-sweep the partial after_cursor is saved and the next invocation
# resumes from where it stopped (stable because createdAt/id never mutate).
# On a cold start the content_hash cache resets; the next full sweep re-publishes
# the entire catalog once (harmless on a keyed-upsert topic).
FULL_SWEEP = os.environ.get("FULL_SWEEP", "false").lower() == "true"

# DEDUP_MODE: controls dedup strategy.
#   off          - no dedup; publish every qualifying record (original behaviour)
#   first_seen   - publish each conditionId once; skip on repeat (legacy DEDUP=true)
#   content_hash - publish only when the metadata fingerprint changes (full-view)
# Legacy DEDUP=true is a back-compat alias for DEDUP_MODE=first_seen.
_DEDUP_MODE_RAW = os.environ.get("DEDUP_MODE", "first_seen" if DEDUP else "off")
DEDUP_MODE = _DEDUP_MODE_RAW.lower()
if DEDUP_MODE not in ("off", "first_seen", "content_hash"):
    raise ValueError(f"DEDUP_MODE must be off|first_seen|content_hash, got: {DEDUP_MODE!r}")

# HASH_FIELDS: field set used by content_hash mode.
# "metadata" uses the built-in preset of stable metadata/state fields that
# excludes all price and volume fields.  A comma-separated list of field names
# can also be provided to override the preset.
_HASH_FIELDS_RAW = os.environ.get("HASH_FIELDS", "metadata").strip()

# Built-in metadata preset: stable identity + state fields.
# Explicitly excludes: outcomePrices, lastTradePrice, bestBid, bestAsk, spread,
# volume*, liquidityNum/Clob, updatedAt, oneDayPriceChange — all high-frequency
# price/volume fields whose churn we want to suppress.
_METADATA_HASH_FIELDS = frozenset([
    "conditionId",
    "question",
    "slug",
    "outcomes",
    "clobTokenIds",
    "active",
    "closed",
    "archived",
    "restricted",
    "acceptingOrders",
    "enableOrderBook",
    "endDate",
    "startDate",
    "umaResolutionStatus",
    "negRisk",
    "groupItemTitle",
    "groupItemThreshold",
    "sportsMarketType",
    "line",
])

if _HASH_FIELDS_RAW.lower() == "metadata":
    HASH_FIELDS: frozenset[str] = _METADATA_HASH_FIELDS
else:
    HASH_FIELDS = frozenset(f.strip() for f in _HASH_FIELDS_RAW.split(",") if f.strip())

ssm = boto3.client("ssm")
secrets = boto3.client("secretsmanager")
cloudwatch = boto3.client("cloudwatch")
dynamodb = boto3.client("dynamodb") if LOCK_TABLE else None

# Reused across warm invocations so the permanent ~10s cadence does not pay a
# fresh SASL_SSL handshake on every run. Rebuilt on demand after any failure.
_PRODUCER: "KafkaProducer | None" = None

# DEDUP mode cache: conditionId -> last-seen monotonic time. Module scope so it
# persists across warm invocations; pruned by DEDUP_TTL_SECONDS to stay bounded.
_DEDUP_CACHE: dict[str, float] = {}

# content_hash mode cache: conditionId -> last published sha1 hex string.
# Module scope so it persists across warm invocations; pruned by DEDUP_TTL_SECONDS.
_HASH_CACHE: dict[str, str] = {}

_ALL_PASSES = (
    ("open", "false"),
    ("closed", "true"),
)
# In OPEN_ONLY mode we scan only newly created open markets, so we skip the
# closed pass entirely to keep runs short and near real time.
MARKET_PASSES = (_ALL_PASSES[0],) if OPEN_ONLY else _ALL_PASSES


def _raise_send_errors(send_errors: list[Exception]) -> None:
    if send_errors:
        _DEDUP_CACHE.clear()
        _HASH_CACHE.clear()
        raise RuntimeError(
            f"Kafka send failed for {len(send_errors)} record(s); example: {send_errors[0]!r}"
        )


def _flush_and_check(producer: KafkaProducer, send_errors: list[Exception]) -> None:
    try:
        producer.flush()
    except Exception:
        _DEDUP_CACHE.clear()
        _HASH_CACHE.clear()
        raise
    _raise_send_errors(send_errors)


def _content_hash(market: dict[str, Any]) -> str:
    """Return a stable sha1 fingerprint of the metadata fields in *market*.

    Only fields present in HASH_FIELDS are included; missing fields are treated
    as None.  Values are serialised with sort_keys=True so dict ordering never
    affects the hash.  The result is a 40-char hex string.
    """
    payload = {k: market.get(k) for k in sorted(HASH_FIELDS)}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def parse_iso8601(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _now_monotonic() -> float:
    return time.monotonic()


def fetch_gamma_page(params: dict[str, Any]) -> dict[str, Any]:
    """Fetch one keyset page, bypassing the Cloudflare cache and retrying.

    A unique `_cb` param per request forces a CDN cache MISS so we read the
    freshest data instead of a response up to 5 minutes stale. Transient origin
    errors/timeouts are retried with linear backoff.
    """
    last_exc: Exception | None = None
    for attempt in range(1, GAMMA_MAX_RETRIES + 1):
        req_params = dict(params)
        if CACHE_BUST:
            req_params["_cb"] = uuid.uuid4().hex
        try:
            resp = requests.get(GAMMA_URL, params=req_params, timeout=GAMMA_TIMEOUT_S)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - retry any transient fetch error
            last_exc = exc
            if attempt < GAMMA_MAX_RETRIES:
                time.sleep(0.5 * attempt)
    raise last_exc  # type: ignore[misc]


def default_sync_state() -> dict[str, str | None]:
    return {
        "watermark": POLYMARKET_EPOCH,
        "current_pass": MARKET_PASSES[0][0],
        "after_cursor": None,
        "target_cursor": None,
    }


def get_sync_state() -> dict[str, str | None]:
    try:
        resp = ssm.get_parameter(Name=SSM_CURSOR_KEY)
        value = resp["Parameter"].get("Value", "").strip()
        if not value:
            return default_sync_state()

        try:
            state = json.loads(value)
        except json.JSONDecodeError:
            return {
                "watermark": value,
                "current_pass": MARKET_PASSES[0][0],
                "after_cursor": None,
                "target_cursor": None,
            }

        if not isinstance(state, dict):
            raise ValueError("SSM cursor must be an ISO-8601 string or JSON object")

        watermark = state.get("watermark") or POLYMARKET_EPOCH
        current_pass = state.get("current_pass") or MARKET_PASSES[0][0]
        after_cursor = state.get("after_cursor")
        target_cursor = state.get("target_cursor")

        if not isinstance(watermark, str):
            raise ValueError("SSM cursor watermark must be a string")
        if not isinstance(current_pass, str):
            raise ValueError("SSM cursor current_pass must be a string")
        if current_pass not in {name for name, _ in MARKET_PASSES}:
            raise ValueError("SSM cursor current_pass must be one of the configured market passes")
        if after_cursor is not None and not isinstance(after_cursor, str):
            raise ValueError("SSM cursor after_cursor must be a string when present")
        if target_cursor is not None and not isinstance(target_cursor, str):
            raise ValueError("SSM cursor target_cursor must be a string when present")

        return {
            "watermark": watermark,
            "current_pass": current_pass,
            "after_cursor": after_cursor,
            "target_cursor": target_cursor,
        }
    except ssm.exceptions.ParameterNotFound:
        return default_sync_state()


def save_sync_state(
    watermark: str,
    current_pass: str | None = None,
    after_cursor: str | None = None,
    target_cursor: str | None = None,
) -> None:
    state = {
        "watermark": watermark,
        "current_pass": current_pass,
        "after_cursor": after_cursor,
        "target_cursor": target_cursor,
    }
    ssm.put_parameter(
        Name=SSM_CURSOR_KEY,
        Value=json.dumps(state),
        Type="String",
        Overwrite=True,
    )


def get_kafka_config() -> tuple[str, str, str]:
    secret = secrets.get_secret_value(SecretId=KAFKA_SECRET_ARN)
    secret_str = secret.get("SecretString", "{}")
    creds = json.loads(secret_str)

    bootstrap = creds.get("bootstrap_servers")
    username = creds.get("username")
    password = creds.get("password")

    missing = []
    if not bootstrap:
        missing.append("bootstrap_servers")
    if not username:
        missing.append("username")
    if not password:
        missing.append("password")
    if missing:
        raise ValueError(f"Kafka secret missing required keys: {', '.join(missing)}")

    return bootstrap, username, password


def make_producer() -> KafkaProducer:
    bootstrap, username, password = get_kafka_config()
    return KafkaProducer(
        bootstrap_servers=bootstrap,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
        security_protocol="SASL_SSL",
        sasl_mechanism=KAFKA_SASL_MECHANISM,
        sasl_plain_username=username,
        sasl_plain_password=password,
        # WarpStream-friendly producer tuning. WarpStream commits batches to
        # object storage, so larger batches + a short linger dramatically raise
        # throughput and cut per-record produce latency versus tiny defaults.
        # (kafka-python has no delivery.timeout.ms; request_timeout_ms is the
        # closest supported control.)
        linger_ms=PRODUCER_LINGER_MS,          # kafka.producer.linger.ms
        batch_size=PRODUCER_BATCH_SIZE,        # kafka.producer.batch.size
        request_timeout_ms=PRODUCER_REQUEST_TIMEOUT_MS,  # kafka.producer.request.timeout.ms
        acks=PRODUCER_ACKS,
        compression_type=PRODUCER_COMPRESSION,
    )


def get_producer() -> KafkaProducer:
    """Return a process-wide KafkaProducer, creating it on first use.

    Kept at module scope so warm Lambda invocations reuse the same authenticated
    connection instead of re-doing the SASL_SSL handshake every ~10 seconds.
    """
    global _PRODUCER
    if _PRODUCER is None:
        _PRODUCER = make_producer()
    return _PRODUCER


def flush_producer() -> None:
    if _PRODUCER is not None:
        try:
            _PRODUCER.flush()
        except Exception as exc:  # pragma: no cover - best effort flush
            print(f"Producer flush failed: {exc}")


def reset_producer() -> None:
    """Drop the cached producer so the next invocation rebuilds a fresh one.

    Called after a failed run so a stale/broken connection is not reused.
    """
    global _PRODUCER
    if _PRODUCER is not None:
        try:
            _PRODUCER.close(timeout=5)
        except Exception:
            pass
        _PRODUCER = None


def release_lock(event: Any) -> None:
    """Release the DynamoDB lock this run holds, if any.

    The dispatcher acquires the lock and passes {lock_id, owner} in the event.
    We delete the item only when we still own it, so an expired-lease takeover
    by a later run is never clobbered.
    """
    if not LOCK_TABLE or dynamodb is None:
        return
    if not isinstance(event, dict):
        return
    lock_id = event.get("lock_id")
    owner = event.get("owner")
    if not lock_id or not owner:
        return
    try:
        dynamodb.delete_item(
            TableName=LOCK_TABLE,
            Key={"lock_id": {"S": str(lock_id)}},
            ConditionExpression="#o = :owner",
            ExpressionAttributeNames={"#o": "owner"},
            ExpressionAttributeValues={":owner": {"S": str(owner)}},
        )
        print(f"Released lock lock_id={lock_id} owner={owner}")
    except dynamodb.exceptions.ConditionalCheckFailedException:
        print(f"Lock already released or taken over lock_id={lock_id} owner={owner}")
    except Exception as exc:  # pragma: no cover - best effort release
        print(f"Lock release failed lock_id={lock_id}: {exc}")


def put_run_metrics(status: str, fetched: int, published: int, skipped: int, pages: int) -> None:
    """Emit one set of per-run counters to CloudWatch.

    These metrics make it easy to answer questions like "how many records were
    fetched per run?" without scraping logs. Kept best-effort so metric issues
    never fail the sync itself.
    """
    try:
        cloudwatch.put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "records_fetched",
                    "Value": fetched,
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Status", "Value": status}],
                },
                {
                    "MetricName": "records_published",
                    "Value": published,
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Status", "Value": status}],
                },
                {
                    "MetricName": "records_skipped",
                    "Value": skipped,
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Status", "Value": status}],
                },
                {
                    "MetricName": "pages_scanned",
                    "Value": pages,
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Status", "Value": status}],
                },
                {
                    "MetricName": "runs",
                    "Value": 1,
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Status", "Value": status}],
                },
            ],
        )
    except Exception as exc:  # pragma: no cover - metrics are best effort
        print(f"Metric emit failed status={status}: {exc}")


def require_markets_payload(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(payload, dict):
        raise ValueError("Gamma API payload must be a JSON object")

    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        raise ValueError("Gamma API payload field 'markets' must be a list")

    next_cursor = payload.get("next_cursor")
    if next_cursor is not None and not isinstance(next_cursor, str):
        raise ValueError("Gamma API payload field 'next_cursor' must be a string when present")

    return markets, next_cursor


def pass_index(pass_name: str) -> int:
    for index, (name, _) in enumerate(MARKET_PASSES):
        if name == pass_name:
            return index

    raise ValueError(f"Unknown market pass: {pass_name}")


def handler(event, context):
    run_started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sync_state = get_sync_state()
    last_run = sync_state["watermark"] or POLYMARKET_EPOCH
    last_run_dt = parse_iso8601(last_run)
    # Effective publish cutoff includes the safety lookback so late-visible
    # records (createdAt already behind the advanced watermark) are still caught.
    cutoff_dt = last_run_dt - timedelta(seconds=LOOKBACK_SECONDS)
    if FULL_SWEEP:
        # In full-sweep mode, force cutoff to the epoch so the timestamp check
        # never terminates the scan early — every market on every page is
        # evaluated by the dedup layer, not the watermark.
        cutoff_dt = parse_iso8601(POLYMARKET_EPOCH)
    elif DEDUP:
        # Fast "recent only" mode must never chase a backlog: if a run drifts
        # behind, chasing it would scan minutes of churn and spiral. Always look
        # at just the last LOOKBACK seconds relative to now; dedup prevents
        # re-publishing, and the full-view worker owns history/reconciliation.
        run_started_dt = datetime.now(timezone.utc)
        floor_dt = run_started_dt - timedelta(seconds=LOOKBACK_SECONDS)
        if floor_dt > cutoff_dt:
            cutoff_dt = floor_dt
    current_pass = sync_state["current_pass"] or MARKET_PASSES[0][0]
    after_cursor = sync_state["after_cursor"]
    target_cursor = sync_state["target_cursor"] or run_started_at
    end_cursor = target_cursor

    print(
        f"Run starting: order={SYNC_ORDER_FIELD} ts_field={SYNC_TIMESTAMP_FIELD} "
        f"open_only={OPEN_ONLY} lookback_s={LOOKBACK_SECONDS} full_sweep={FULL_SWEEP} "
        f"cursor_start={last_run} cutoff={cutoff_dt.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"cursor_end={end_cursor} resume_pass={current_pass} "
        f"resume_after_cursor={after_cursor or 'none'} records_written=0"
    )

    params = {
        "limit": 100,
        "order": SYNC_ORDER_FIELD,
        "ascending": "false",
    }

    fetched_total = 0
    published_total = 0
    skipped_total = 0
    pages_scanned = 0
    pass_summaries: dict[str, dict[str, int]] = {
        name: {"fetched": 0, "published": 0, "skipped": 0, "pages": 0}
        for name, _ in MARKET_PASSES
    }

    try:
        # Build the producer inside the try so any producer/connection failure
        # still runs the finally block and releases the dispatcher's lock,
        # instead of leaking it until the DynamoDB TTL expires.
        producer = get_producer()
        # Collect async send failures without blocking the paging loop.
        send_errors: list[Exception] = []

        def _on_send_error(exc: Exception) -> None:
            send_errors.append(exc)

        start_index = pass_index(current_pass)
        for index in range(start_index, len(MARKET_PASSES)):
            current_pass, closed_value = MARKET_PASSES[index]
            params["closed"] = closed_value

            if index > start_index:
                after_cursor = None

            print(
                f"Starting pass={current_pass} cursor_start={last_run} "
                f"cursor_end={end_cursor} resume_after_cursor={after_cursor or 'none'}"
            )

            while True:
                if context.get_remaining_time_in_millis() < 15000:
                    _flush_and_check(producer, send_errors)
                    save_sync_state(
                        last_run,
                        current_pass=current_pass,
                        after_cursor=after_cursor,
                        target_cursor=target_cursor,
                    )
                    print(
                        f"Approaching timeout - stopping at pass={current_pass} page={pages_scanned}, "
                        f"cursor_start={last_run} cursor_end={end_cursor} "
                        f"resume_after_cursor={after_cursor or 'none'} "
                        f"records_written={published_total}"
                    )
                    put_run_metrics(
                        status="partial",
                        fetched=fetched_total,
                        published=published_total,
                        skipped=skipped_total,
                        pages=pages_scanned,
                    )
                    return {
                        "open": pass_summaries.get("open"),
                        "closed": pass_summaries.get("closed"),
                        "fetched": fetched_total,
                        "published": published_total,
                        "skipped": skipped_total,
                        "complete": False,
                    }

                if after_cursor:
                    params["after_cursor"] = after_cursor
                else:
                    params.pop("after_cursor", None)

                resp = fetch_gamma_page(params)

                payload = resp
                markets, next_cursor = require_markets_payload(payload)

                if not markets:
                    break

                pages_scanned += 1
                fetched_total += len(markets)
                pass_summaries[current_pass]["fetched"] += len(markets)
                pass_summaries[current_pass]["pages"] += 1
                page_has_new_or_equal = False
                page_reached_older_records = False

                for market in markets:
                    condition_id = market.get("conditionId")
                    if not condition_id:
                        skipped_total += 1
                        pass_summaries[current_pass]["skipped"] += 1
                        continue

                    updated_at = market.get(SYNC_TIMESTAMP_FIELD)
                    if updated_at:
                        try:
                            if parse_iso8601(updated_at) >= cutoff_dt:
                                page_has_new_or_equal = True
                            else:
                                # Results are ordered by SYNC_ORDER_FIELD DESC.
                                # Once we hit a record older than the lookback
                                # cutoff, the rest of this page and any following
                                # pages are older too, so stop publishing
                                # immediately instead of sending stale records.
                                page_reached_older_records = True
                                break
                        except ValueError:
                            page_has_new_or_equal = True
                    else:
                        # Keep current permissive behavior for malformed or
                        # missing timestamps: publish and let downstream dedupe.
                        page_has_new_or_equal = True

                    # Dedup check — three modes controlled by DEDUP_MODE.
                    #
                    # first_seen: publish each conditionId only the first time
                    # it is seen in this Lambda's warm lifetime; skip repeats.
                    # Keeps the fast tail feed to essentially new-markets-only.
                    # We refresh last-seen on every sighting so active markets
                    # are not pruned and then re-published unexpectedly.
                    #
                    # content_hash: compute a fingerprint of the metadata/state
                    # fields (HASH_FIELDS preset); publish only when the hash
                    # differs from the last published value for this conditionId.
                    # This collapses pure price/volume churn (updatedAt ticks on
                    # every re-price) to zero publishes while still propagating
                    # genuine state changes (closed, acceptingOrders, etc.).
                    #
                    # off: no dedup; publish every qualifying record.
                    if DEDUP_MODE == "first_seen":
                        if condition_id in _DEDUP_CACHE:
                            _DEDUP_CACHE[condition_id] = _now_monotonic()
                            skipped_total += 1
                            pass_summaries[current_pass]["skipped"] += 1
                            continue
                        _DEDUP_CACHE[condition_id] = _now_monotonic()
                    elif DEDUP_MODE == "content_hash":
                        h = _content_hash(market)
                        if _HASH_CACHE.get(condition_id) == h:
                            skipped_total += 1
                            pass_summaries[current_pass]["skipped"] += 1
                            continue
                        _HASH_CACHE[condition_id] = h
                        # Track last-seen time so the TTL pruner can evict
                        # inactive markets from both caches.
                        _DEDUP_CACHE[condition_id] = _now_monotonic()

                    # Fire-and-forget: hand the record to the producer's
                    # background sender and keep paging. We do NOT block on the
                    # ack here. The old code waited for all 100 acks and flushed
                    # every page, which serialized Gamma HTTP latency with Kafka
                    # ack latency and capped throughput. The producer batches
                    # (linger + batch.size) across pages; errors are captured via
                    # the errback and durability is guaranteed by the periodic /
                    # pre-checkpoint flushes below.
                    producer.send(KAFKA_TOPIC, key=condition_id, value=market).add_errback(_on_send_error)
                    published_total += 1
                    pass_summaries[current_pass]["published"] += 1

                # Flush periodically (not every page) to bound producer buffer
                # memory without reintroducing a per-page synchronization barrier.
                if FLUSH_EVERY_PAGES > 0 and pages_scanned % FLUSH_EVERY_PAGES == 0:
                    _flush_and_check(producer, send_errors)

                print(
                    f"Pass {current_pass} page {pass_summaries[current_pass]['pages']}: "
                    f"fetched={len(markets)} published_total={published_total} "
                    f"skipped_total={skipped_total} since={last_run}"
                )

                if page_reached_older_records or not page_has_new_or_equal:
                    print(f"Pass {current_pass}: reached records older than last_run watermark; stopping")
                    break

                if MAX_PAGES_PER_RUN > 0 and pass_summaries[current_pass]["pages"] >= MAX_PAGES_PER_RUN:
                    print(f"Pass {current_pass}: reached MAX_PAGES_PER_RUN={MAX_PAGES_PER_RUN}; stopping")
                    break

                if not next_cursor:
                    break

                after_cursor = next_cursor

            after_cursor = None

        # Bound the dedup caches: drop conditionIds not seen within the TTL so
        # they stay bounded across warm invocations.
        if DEDUP_MODE == "first_seen" and _DEDUP_CACHE:
            horizon = _now_monotonic() - DEDUP_TTL_SECONDS
            stale = [cid for cid, seen in _DEDUP_CACHE.items() if seen < horizon]
            for cid in stale:
                _DEDUP_CACHE.pop(cid, None)
        if DEDUP_MODE == "content_hash" and _HASH_CACHE:
            # For content_hash, prune by tracking last-publish time separately
            # via the _DEDUP_CACHE (we co-opt it as a last-seen tracker).
            horizon = _now_monotonic() - DEDUP_TTL_SECONDS
            stale = [cid for cid, seen in _DEDUP_CACHE.items() if seen < horizon]
            for cid in stale:
                _DEDUP_CACHE.pop(cid, None)
                _HASH_CACHE.pop(cid, None)

        # Ensure every buffered record is durably acked BEFORE advancing the
        # watermark, so a crash can never skip records that the cursor claims
        # were published.
        _flush_and_check(producer, send_errors)
        if FULL_SWEEP:
            # Reset cursor to epoch so the next invocation starts a fresh full
            # sweep from the beginning. This is safe: the content_hash cache
            # avoids re-publishing unchanged markets.
            save_sync_state(POLYMARKET_EPOCH)
            end_cursor = POLYMARKET_EPOCH
        else:
            end_cursor = target_cursor
            save_sync_state(end_cursor)
        print(
            f"Done. pages={pages_scanned} fetched={fetched_total} "
            f"published={published_total} skipped={skipped_total} "
            f"cursor_start={last_run} cursor_end={end_cursor} "
            f"records_written={published_total}"
        )
        put_run_metrics(
            status="complete",
            fetched=fetched_total,
            published=published_total,
            skipped=skipped_total,
            pages=pages_scanned,
        )
        return {
            "open": pass_summaries.get("open"),
            "closed": pass_summaries.get("closed"),
            "fetched": fetched_total,
            "published": published_total,
            "skipped": skipped_total,
            "complete": True,
        }
    except Exception:
        # Drop the cached producer so the next invocation rebuilds a fresh,
        # healthy connection instead of reusing a possibly broken one.
        reset_producer()
        raise
    finally:
        flush_producer()
        release_lock(event)
