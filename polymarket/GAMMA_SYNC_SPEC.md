# Gamma Sync Feature Spec

## Purpose

Gamma Sync ingests Polymarket Gamma market metadata into Kafka so downstream consumers can treat the topic as a keyed changelog by `conditionId`.

## Components

- `gamma-sync`: full catalog reconciliation worker. It uses stable `createdAt` ordering, full sweeps, and content-hash deduplication so metadata/state changes are published while price and volume churn is suppressed.
- `gamma-sync-recent`: low-latency new-market worker. It scans the newest `createdAt` feed with a lookback window and first-seen deduplication so new markets arrive quickly.
- Dispatcher Lambda and Step Functions: provide sub-minute cadence while a DynamoDB lock guarantees only one worker run is active per stack.

## Data Contract

- Source: `https://gamma-api.polymarket.com/markets/keyset`.
- Kafka key: `conditionId`.
- Kafka value: raw Gamma market object.
- Topic behavior: changelog/upsert stream. Duplicate keys are expected; consumers should take the latest value for each key.

## Reliability Requirements

- Do not advance the SSM cursor until buffered Kafka sends have been flushed and send errors have been checked.
- On partial runs near Lambda timeout, flush and verify Kafka sends before saving the resume cursor.
- Use cache-busting Gamma API requests by default to avoid stale Cloudflare responses.
- Use DynamoDB dispatcher locks for sub-minute deployments to skip overlapping runs instead of queueing them.

## Configuration And Secrets

- Kafka credentials are read from AWS Secrets Manager via `KAFKA_SECRET_ARN` or deployment-time `SECRET_ARN`.
- Raw Kafka credentials must not be committed.
- Local credential files such as `client.txt`, Lambda zip files, and packaged dependencies are generated/local artifacts and should stay out of source control.

## Operations

- Build with `make package` from `polymarket/gamma-sync`.
- Deploy full reconciliation with `make deploy-full SECRET_ARN=<secret-arn>`.
- Deploy recent new-market sync with `make deploy-recent SECRET_ARN=<secret-arn>`.
- See `polymarket/gamma-sync/README.md` for detailed deployment, metrics, and troubleshooting instructions.
