# Gamma Sync Lambda Package

This package contains an AWS Lambda function (`lambda_function.py`) that syncs
raw Polymarket Gamma market objects into Kafka. Two deployments of the same
code run side-by-side, each in an isolated AWS stack, writing to the same
Kafka topic as a changelog keyed by `conditionId`.

## Deployments

### `gamma-sync` — full-view sync (currently live, `demo_pm_gamma`)

Reconciles the entire open-market set into `demo_pm_gamma` and
propagates all metadata/state changes (market closing, resolution, outcome
edits, `acceptingOrders` toggles, etc.).

- **`FULL_SWEEP=true`** + `order=createdAt` (immutable): walks all ~486 pages
  to `next_cursor=null` on every cycle; resets cursor to epoch on complete so
  the next cycle re-sweeps. Guarantees complete coverage of all ~49K markets.
- ~10s cadence (sub-minute Step Functions stack)
- **Content-hash dedup** (`DEDUP_MODE=content_hash`): publishes only when
  metadata fingerprint changes; skips pure price/volume churn.
- SSM cursor: `/gamma/cursor`
- Kafka topic: `demo_pm_gamma`
- CloudWatch namespace: `GammaSync`

### `gamma-sync-recent` — fast new-market path (currently live, `demo_pm_gamma`)

Tails the newest end of the `createdAt` feed every ~3 seconds and publishes
each market **once** (first-seen dedup). New markets land in Kafka within
~400ms of becoming visible in the Gamma API.

- `order=createdAt DESC`, open markets only
- `LOOKBACK_SECONDS=180` — covers Gamma's ~55–120s market visibility delay
  (new markets become queryable up to ~2 min after their `createdAt`)
- ~3s cadence (sub-minute Step Functions stack, `WAIT_SECONDS=3`)
- First-seen dedup (`DEDUP=true`): publishes each `conditionId` once, skips
  thereafter; in-memory cache across warm invocations, pruned by TTL
- Page cap (`MAX_PAGES_PER_RUN=10`): bounds HTTP per run; new markets are
  always at the top of the `createdAt DESC` feed
- SSM cursor: `/gamma/recent/cursor`
- Kafka topic: `demo_pm_gamma` (same as full-view)
- CloudWatch namespace: `GammaSyncRecent`

---

### V2 Pipeline (parallel, `demo_pm_gamma_v2`) — `createdAt` full-sweep design

The v2 pipeline runs **beside** the existing `demo_pm_gamma` pipeline and
corrects the completeness gap. It uses `order=createdAt` (immutable) which
guarantees stable, complete pagination across the full ~49K open-market catalog.

#### `gamma-sync-v2` — createdAt full-sweep backbone

- **`FULL_SWEEP=true`**: ignores the timestamp watermark; walks ALL pages until
  `next_cursor=null`, then resets to epoch so the next cycle re-sweeps from the
  beginning. Guarantees every open market is covered on every cycle (~4 min
  full refresh at continuous sub-minute cadence).
- `order=createdAt` (immutable) — stable pagination, no mid-scan row skipping.
- `content_hash` dedup — each sweep publishes only markets whose metadata has
  changed (or was never published), keeping Kafka volume low despite a full
  catalog scan every cycle.
- SSM cursor: `/gamma/v2/cursor`
- Kafka topic: `demo_pm_gamma_v2`
- CloudWatch namespace: `GammaSyncV2`

#### `gamma-sync-v2-recent` — createdAt fast new-market path

- `order=createdAt DESC`, `LOOKBACK_SECONDS=180` — covers Gamma's ~55–120s
  market visibility delay (new markets become queryable up to ~120s after their
  `createdAt`; a 180s lookback ensures they land within the scan window).
- First-seen dedup, `MAX_PAGES_PER_RUN=10`, ~3s cadence.
- SSM cursor: `/gamma/v2/recent/cursor`
- Kafka topic: `demo_pm_gamma_v2`
- CloudWatch namespace: `GammaSyncV2Recent`

### `gamma-sync-recent` — fast new-market path (currently live)

Tails only the freshest top of the `updatedAt` feed every ~3 seconds and
publishes each market **once** (first-seen dedup). In steady state runs are
1–2 pages (published=0–few), so new markets land in Kafka within ~400ms of
becoming visible in the Gamma API.

- Scans `updatedAt DESC`, open markets only
- ~3s cadence (sub-minute Step Functions stack, `WAIT_SECONDS=3`)
- First-seen dedup (`DEDUP=true`): publishes each `conditionId` once, skips it
  thereafter; in-memory cache across warm invocations, pruned by `DEDUP_TTL_SECONDS`
- No-backfill cutoff (`DEDUP=true` mode): scan floor is always `now - LOOKBACK_SECONDS`
  regardless of cursor age, preventing catch-up spirals
- Page cap (`MAX_PAGES_PER_RUN=10`): bounds HTTP per run to the freshest top-N
  pages; new markets are at the top so this is always sufficient
- SSM cursor: `/gamma/recent/cursor`
- Kafka topic: `demo_pm_gamma` (same as full-view)
- CloudWatch namespace: `GammaSyncRecent`

### Why the same topic

Both workers publish the same canonical Gamma market object keyed by
`conditionId`. The topic is treated as a changelog/upsert stream:

- `gamma-sync-recent` writes the first early copy of a new market
- `gamma-sync` later writes the same market again as part of broad reconciliation
- Duplicates are harmless; consumers take latest-by-key

### Measured latency (2026-07-06)

| Metric | Value |
|---|---|
| Gamma API visible → Kafka (`gamma-sync-recent`) | **~400ms** |
| `createdAt` → Kafka | ~58s (Gamma-side visibility delay, not pipeline) |
| `produce` → consumer receive | ~1–2s |

## Architecture

```
EventBridge rate(1 minute)
  -> Step Functions state machine (ITERATIONS dispatches, WAIT_SECONDS apart)
       -> Dispatcher Lambda: DynamoDB conditional lock acquire
            -> acquired: async-invoke worker {lock_id, owner}
            -> held:     return "skipped_busy"
  Worker Lambda: runs, releases lock in finally block
```

Semantics: **attempt every N seconds, skip if busy, never queue.**

The dispatcher acquires a DynamoDB conditional lock before each invoke. If a
prior run is still active the slot is skipped. Lock `expires_at` is crash
recovery only (default 960s); the lock is released by the worker's `finally`
block on normal exit (success or error).

## Files

- `lambda_function.py` — Lambda handler and sync logic (both deployments)
- `dispatch_function.py` — sub-minute dispatcher Lambda
- `statemachine.asl.json` — Step Functions definition template
- `requirements.txt` — Python dependencies
- `Makefile` — build helpers
- `deploy_aws.sh` — AWS CLI deployment automation
- `destroy_aws.sh` — AWS CLI teardown
- `smoke_test_kafka.py` — local producer smoke test
- `latency_probe.py` — general Gamma→Kafka latency probe
- `new_market_latency_probe.py` — new-market creation latency probe

## Environment Variables

All variables listed below are set on the Lambda function. The deploy script
passes all of them; defaults are shown.

### Required

| Variable | Description |
|---|---|
| `SSM_CURSOR_KEY` | SSM parameter for the incremental cursor |
| `KAFKA_SECRET_ARN` | Secrets Manager ARN with Kafka credentials |

### Kafka

| Variable | Default | Description |
|---|---|---|
| `KAFKA_TOPIC` | `demo_pm_gamma_markets` | Destination topic (live deployments use `demo_pm_gamma`) |
| `KAFKA_SASL_MECHANISM` | `SCRAM-SHA-512` | SASL mechanism |

### Sync mode

| Variable | Default | Description |
|---|---|---|
| `SYNC_ORDER_FIELD` | `updatedAt` | Gamma keyset `order` param (`updatedAt` or `createdAt`) |
| `SYNC_TIMESTAMP_FIELD` | `updatedAt` | Market field used as the incremental cutoff (defaults to `SYNC_ORDER_FIELD`) |
| `OPEN_ONLY` | `false` | When `true` skips the `closed=true` pass entirely |
| `LOOKBACK_SECONDS` | `0` | Trailing overlap re-scanned each run to catch late-visible records |

### Dedup

Three modes are available via `DEDUP_MODE`. The legacy `DEDUP=true` env var
is a back-compat alias for `DEDUP_MODE=first_seen`.

| Variable | Default | Description |
|---|---|---|
| `DEDUP_MODE` | `off` | `off` \| `first_seen` \| `content_hash` |
| `HASH_FIELDS` | `metadata` | Field preset for `content_hash` mode. `metadata` uses a built-in set of metadata/state fields and excludes all price/volume fields. |
| `DEDUP_TTL_SECONDS` | `3600` | Drop cached entries not seen for this long |
| `MAX_PAGES_PER_RUN` | `0` (unlimited) | Cap pages per run; `10` for the fast path bounds warm-up bursts |
| `DEDUP` | `false` | Legacy alias: `true` maps to `DEDUP_MODE=first_seen` |
| `FULL_SWEEP` | `false` | When `true`: ignore watermark cutoff, paginate all pages to `next_cursor=null`, reset to epoch on complete. Use with `SYNC_ORDER_FIELD=createdAt` and `DEDUP_MODE=content_hash`. |

### Producer tuning (WarpStream-optimised)

| Variable | Default | Description |
|---|---|---|
| `PRODUCER_LINGER_MS` | `100` | Batch accumulation window |
| `PRODUCER_BATCH_SIZE` | `1048576` | Max batch bytes (1 MiB) |
| `PRODUCER_REQUEST_TIMEOUT_MS` | `60000` | Kafka request timeout |
| `PRODUCER_ACKS` | `1` | Required acks |
| `PRODUCER_COMPRESSION` | `gzip` | Compression codec (`gzip` is stdlib-safe on Lambda) |
| `FLUSH_EVERY_PAGES` | `25` | Periodic flush cadence; `0` = only at end-of-run |

### Gamma API

| Variable | Default | Description |
|---|---|---|
| `CACHE_BUST` | `true` | Append `_cb=<uuid>` to every Gamma request to force a CDN cache MISS. **Leave enabled.** The keyset endpoint has `Cache-Control: public, max-age=300` and without this Gamma responses can be up to 5 minutes stale |
| `GAMMA_TIMEOUT_S` | `20` | Per-request HTTP timeout |
| `GAMMA_MAX_RETRIES` | `3` | Retry attempts on transient Gamma errors |

### Observability

| Variable | Default | Description |
|---|---|---|
| `METRIC_NAMESPACE` | `GammaSync` | CloudWatch namespace for per-run metrics |

### Sub-minute cadence (deploy-time only)

| Variable | Default | Description |
|---|---|---|
| `SUBMINUTE` | `false` | Provision the Step Functions + dispatcher stack |
| `ITERATIONS` | `6` | Dispatches per EventBridge minute |
| `WAIT_SECONDS` | `10` | Seconds between dispatches |
| `LOCK_TTL_SECONDS` | `960` | DynamoDB lock lease duration (crash recovery) |
| `LOCK_TABLE_NAME` | `gamma-sync-lock` | DynamoDB lock table |
| `LOCK_ID` | `gamma-sync` | Lock item key |
| `DISPATCH_FUNCTION_NAME` | `gamma-sync-dispatch` | Dispatcher Lambda name |
| `STATE_MACHINE_NAME` | `gamma-sync-subminute` | Step Functions state machine name |

## Secret Format

Kafka credentials in Secrets Manager must be JSON:

```json
{
  "bootstrap_servers": "your-broker:9092",
  "username": "your-username",
  "password": "your-password"
}
```

## Deploy: full-view stack (`gamma-sync`)

```bash
cd gamma-sync
make package

SECRET_ARN='arn:aws:...' \
FUNCTION_NAME='gamma-sync' \
ROLE_NAME='gamma-sync-lambda-role' \
RULE_NAME='gamma-sync-schedule' \
POLICY_NAME='gamma-sync-inline-policy' \
SSM_CURSOR_KEY='/gamma/cursor' \
KAFKA_TOPIC='demo_pm_gamma' \
SYNC_ORDER_FIELD='updatedAt' \
OPEN_ONLY='true' \
LOOKBACK_SECONDS='15' \
DEDUP_MODE='content_hash' \
HASH_FIELDS='metadata' \
SUBMINUTE='true' \
ITERATIONS='6' \
WAIT_SECONDS='10' \
LOCK_TABLE_NAME='gamma-sync-lock' \
LOCK_ID='gamma-sync' \
DISPATCH_FUNCTION_NAME='gamma-sync-dispatch' \
STATE_MACHINE_NAME='gamma-sync-subminute' \
METRIC_NAMESPACE='GammaSync' \
RESET_CURSOR='false' \
AWS_REGION='us-east-1' \
./deploy_aws.sh
```

Set `RESET_CURSOR=true` and `CURSOR_INITIAL_VALUE=2020-01-01T00:00:00Z` for a
full epoch backfill. Leave `RESET_CURSOR=false` to preserve an existing cursor.

## Deploy: fast new-market stack (`gamma-sync-recent`)

```bash
cd gamma-sync
make package

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

SECRET_ARN='arn:aws:...' \
FUNCTION_NAME='gamma-sync-recent' \
ROLE_NAME='gamma-sync-recent-lambda-role' \
RULE_NAME='gamma-sync-recent-schedule' \
POLICY_NAME='gamma-sync-recent-inline-policy' \
SSM_CURSOR_KEY='/gamma/recent/cursor' \
KAFKA_TOPIC='demo_pm_gamma' \
SYNC_ORDER_FIELD='updatedAt' \
OPEN_ONLY='true' \
LOOKBACK_SECONDS='30' \
DEDUP='true' \
MAX_PAGES_PER_RUN='10' \
SUBMINUTE='true' \
ITERATIONS='20' \
WAIT_SECONDS='3' \
LOCK_TABLE_NAME='gamma-sync-recent-lock' \
LOCK_ID='gamma-sync-recent' \
DISPATCH_FUNCTION_NAME='gamma-sync-recent-dispatch' \
DISPATCH_ROLE_NAME='gamma-sync-recent-dispatch-role' \
DISPATCH_POLICY_NAME='gamma-sync-recent-dispatch-policy' \
STATE_MACHINE_NAME='gamma-sync-recent-subminute' \
SFN_ROLE_NAME='gamma-sync-recent-sfn-role' \
SFN_POLICY_NAME='gamma-sync-recent-sfn-policy' \
EVENTS_ROLE_NAME='gamma-sync-recent-events-role' \
EVENTS_POLICY_NAME='gamma-sync-recent-events-policy' \
METRIC_NAMESPACE='GammaSyncRecent' \
RESET_CURSOR='true' \
CURSOR_INITIAL_VALUE="$NOW" \
AWS_REGION='us-east-1' \
./deploy_aws.sh
```

Always use `RESET_CURSOR=true` with `CURSOR_INITIAL_VALUE` set to "now" for
the fast path — it must never chase an epoch backfill.

## Deploy: v2 pipeline (`demo_pm_gamma_v2`)

The v2 pipeline uses `order=createdAt` + `FULL_SWEEP` to guarantee complete
coverage. Use `make deploy-v2-full` and `make deploy-v2-recent` (see Makefile).
Alternatively, run directly:

```bash
# V2 backbone (createdAt full-sweep)
make deploy-v2-full

# V2 recent (createdAt DESC, LOOKBACK=180s for visibility delay)
make deploy-v2-recent

# Tear down v2 (leaves shared Kafka secret intact)
make destroy-v2-full
make destroy-v2-recent
```

## Destroy

```bash
# Full-view stack
SUBMINUTE=true \
FUNCTION_NAME=gamma-sync \
LOCK_TABLE_NAME=gamma-sync-lock \
DISPATCH_FUNCTION_NAME=gamma-sync-dispatch \
STATE_MACHINE_NAME=gamma-sync-subminute \
SSM_CURSOR_KEY=/gamma/cursor \
SECRET_ARN='arn:aws:...' \
./destroy_aws.sh

# Fast new-market stack (do NOT delete the shared Kafka secret)
SUBMINUTE=true \
FUNCTION_NAME=gamma-sync-recent \
ROLE_NAME=gamma-sync-recent-lambda-role \
RULE_NAME=gamma-sync-recent-schedule \
POLICY_NAME=gamma-sync-recent-inline-policy \
LOCK_TABLE_NAME=gamma-sync-recent-lock \
DISPATCH_FUNCTION_NAME=gamma-sync-recent-dispatch \
DISPATCH_ROLE_NAME=gamma-sync-recent-dispatch-role \
STATE_MACHINE_NAME=gamma-sync-recent-subminute \
SFN_ROLE_NAME=gamma-sync-recent-sfn-role \
EVENTS_ROLE_NAME=gamma-sync-recent-events-role \
SSM_CURSOR_KEY=/gamma/recent/cursor \
SECRET_ARN='' \
SECRET_NAME='' \
./destroy_aws.sh
```

Note: when destroying `gamma-sync-recent`, set `SECRET_ARN=''` and
`SECRET_NAME=''` so the destroy script does not delete the shared Kafka secret
that `gamma-sync` also uses.

## Runtime Behavior

### Normal run
- Fetches Gamma pages (newest first) until `updatedAt < cutoff_dt`
- Publishes each qualifying market to Kafka via async fire-and-forget sends
- Flushes every `FLUSH_EVERY_PAGES` pages (and once at end) for durability
- Advances the SSM watermark to `run_started_at` on success

### Timeout / error mid-run
- Saves current pass + `after_cursor` + `target_cursor` to SSM for resume
- Does NOT advance the watermark — next run replays the window
- Releases the DynamoDB lock in `finally` so the next dispatch can start

### Dedup mode (`first_seen`) — fast new-market path

- Module-level `_DEDUP_CACHE: dict[conditionId, monotonic_time]` survives warm invocations
- Each run: check cache → skip if present (refresh last-seen time), else publish and cache
- End of run: prune entries older than `DEDUP_TTL_SECONDS`
- Cold start: cache resets → the active top-window is re-published once over a few
  fast runs (bounded by `MAX_PAGES_PER_RUN`); harmless on an upsert topic

### Dedup mode (`content_hash`) — full-view path

- Module-level `_HASH_CACHE: dict[conditionId, sha1_hex]` survives warm invocations
- Each run: compute sha1 over the metadata field set for each scanned market →
  skip if `cache[conditionId] == hash`, else publish and update cache
- Metadata field set includes state/identity fields (`active`, `closed`,
  `acceptingOrders`, `outcomes`, `clobTokenIds`, `endDate`, `umaResolutionStatus`,
  etc.) but **excludes all price and volume fields** (`outcomePrices`,
  `lastTradePrice`, `bestBid`, `bestAsk`, `spread`, `volume*`).
- Effect: pure re-price ticks produce zero publishes; market lifecycle events
  (closing, resolution, outcome edits) publish exactly once per change.
- Cold start: cache resets → the current scan window (~`LOOKBACK_SECONDS` of
  updates, not the full active set) is re-published once; harmless on an upsert
  topic. Full active-set republish only occurs on epoch-cursor backfill.

### Cloudflare cache busting
The Gamma keyset endpoint returns `Cache-Control: public, max-age=300`.
Without cache-busting, responses can be up to 5 minutes stale. A unique
`_cb=<uuid>` param is appended to every request (`CACHE_BUST=true`) to force
a CDN cache MISS. `no-cache` request headers are ignored by Cloudflare.

## Cursor Behavior

- `deploy_aws.sh` preserves an existing SSM cursor by default (`RESET_CURSOR=false`)
- Set `RESET_CURSOR=true` to rewind to `CURSOR_INITIAL_VALUE`
- For the full-view stack: use `CURSOR_INITIAL_VALUE=2020-01-01T00:00:00Z` for
  a full epoch backfill, or a recent ISO-8601 timestamp to start from "now"
- For the fast new-market stack: always start from "now"; never use epoch

## Observe / Monitor

### CloudWatch metrics

Workers emit per-run metrics in their configured `METRIC_NAMESPACE`:

| Metric | Description |
|---|---|
| `records_fetched` | Raw Gamma records fetched (Status dimension: `complete`/`partial`) |
| `records_published` | Records sent to Kafka |
| `records_skipped` | Records skipped (no conditionId, or dedup hit) |
| `pages_scanned` | Gamma API pages fetched |
| `runs` | Run count |

Dispatcher emits (dimension `LockId=<LOCK_ID>`):

| Metric | Description |
|---|---|
| `invoked` | Worker was successfully dispatched |
| `skipped_busy` | Prior run still active; slot skipped |
| `acquire_error` | Lock acquired but worker invoke failed |

### Useful CloudWatch commands

```bash
# Full-view: invoked/skipped last 15 min
aws cloudwatch get-metric-statistics --namespace GammaSync \
  --metric-name invoked \
  --dimensions Name=LockId,Value=gamma-sync \
  --start-time "$(date -u -v-15M +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --period 60 --statistics Sum --region us-east-1

# Fast path: same
aws cloudwatch get-metric-statistics --namespace GammaSyncRecent \
  --metric-name invoked \
  --dimensions Name=LockId,Value=gamma-sync-recent \
  --start-time "$(date -u -v-15M +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --period 60 --statistics Sum --region us-east-1
```

### Check watermark / cursor lag

```bash
# Full-view
aws ssm get-parameter --region us-east-1 \
  --name /gamma/cursor --query 'Parameter.Value' --output text

# Fast path
aws ssm get-parameter --region us-east-1 \
  --name /gamma/recent/cursor --query 'Parameter.Value' --output text
```

### View worker logs

```bash
aws logs tail /aws/lambda/gamma-sync --region us-east-1 --follow --format short
aws logs tail /aws/lambda/gamma-sync-recent --region us-east-1 --follow --format short
```

## Measure New-Market Latency

Use the included probe to measure how long a newly created market takes to
appear in Kafka after first being visible in the Gamma API:

```bash
cd gamma-sync
PYTHONPATH=package python3 new_market_latency_probe.py \
  --topic demo_pm_gamma \
  --samples 10 \
  --timeout-minutes 15 \
  --quiet
```

The probe reports two metrics per match:

- `latency_from_api_detect_ms` — Gamma API visible → Kafka arrival (~400ms in
  steady state; this is the true pipeline latency)
- `latency_from_createdAt_ms` — market `createdAt` → Kafka (~55–120s; this is
  dominated by Gamma's own batch visibility delay and is not something the
  pipeline can improve)

## Local Smoke Test

Verify Kafka auth/connectivity before deploying:

```bash
cd gamma-sync
make smoke-kafka
```

Set `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_USERNAME`, `KAFKA_PASSWORD`, and
`KAFKA_TOPIC` before running.

## Build

```bash
cd gamma-sync
make package        # builds gamma-sync.zip
make clean          # removes package/ and gamma-sync.zip
make rebuild        # clean + package
```

## Notes

- Reserved concurrency is `1` on both workers. This guarantees no overlapping
  runs and means the DynamoDB lock is the sole coordination point.
- Both workers reuse the Kafka producer across warm invocations (module-level
  singleton) to avoid repeated SASL/SSL handshakes on the ~3–10s cadence.
- The `gamma-sync-recent` stack does not own the shared Kafka secret; destroy it
  with `SECRET_ARN=''` to avoid deleting credentials used by `gamma-sync`.
- `lz4` is in `requirements.txt` but its native wheel is macOS-only; do not use
  `PRODUCER_COMPRESSION=lz4` on Lambda. Use `gzip` (default) or `snappy`
  (requires a Linux-built wheel).
- Cold-start frequency: Lambda execution environments are recycled by AWS
  approximately every 1.5–2 hours (~12–16 cold starts/day per worker). On a
  routine cold start the in-memory dedup cache is empty, so the worker
  re-publishes the records within the current scan window only (~`LOOKBACK_SECONDS`
  of updates, cursor-bounded). **This is not a full active-set republish.** A
  full active-set republish only occurs when the cursor is reset to epoch (e.g.
  after topic recreation). Both are harmless on a keyed-upsert topic.
