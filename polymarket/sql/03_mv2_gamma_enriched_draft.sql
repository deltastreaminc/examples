-- Order enrichment validation pipeline.
-- Phase 3 of the Gamma enrichment pipeline.
-- Run this file only after:
-- 1. sql/01_gamma_markets_changelog.sql has created pm_gamma_markets_cl
-- 2. sql/02_gamma_token_pipeline.sql has created pm_gamma_markets_s,
--    pm_gamma_token_question_flat_s, and pm_gamma_token_question_cl
--
-- This file intentionally stops after building and validating the enriched
-- order relation. Downstream activity calculations should only be added after
-- the join output is confirmed correct.
--
-- Live validation notes from DeltaStream:
-- 1. Stream-to-changelog temporal joins did not yield usable historical
--    enrichment for this use case during replay.
-- 2. A changelog-to-changelog join is the current working DeltaStream-native
--    pattern for general-case token_id -> market_question enrichment.
-- 3. The current scope only requires Gamma market_question, not the full market
--    metadata payload.
--
-- Protected upstream source topics: demo_pm_orders_filled,
-- demo_pm_orders_matched, and demo_pm_gamma_markets must never be
-- deleted, truncated, or repurposed from this project.

USE DATABASE polymarket;
USE SCHEMA public;

-- ============================================================================
-- Phase 3A: Order Source
-- ============================================================================
-- Keep the raw order_filled feed as a stream for replay and debugging.
CREATE STREAM polymarket.public.pm_orders_filled_s (
  id STRING,
  block_number STRING,
  block_timestamp STRING,
  transaction_hash STRING,
  address STRING,
  user_id STRING,
  asset STRING,
  amount_usdc STRING,
  amount_shares STRING,
  price STRING,
  tx_type STRING,
  side STRING,
  order_hash STRING,
  counterparty_id STRING,
  order_type STRING,
  fee STRING,
  builder STRING,
  _gs_op STRING
) WITH (
  'store' = 'warpstream',
  'topic' = 'demo_pm_orders_filled',
  'value.format' = 'json'
);

ALTER RELATION pm_orders_filled_s SET description =
'Replayable raw order_filled stream over the protected source topic demo_pm_orders_filled.';

-- Define a persisted upsert changelog directly on the raw order_filled topic.
-- The raw Goldsky topic is append-only stream data, not an upsert changelog.
-- Build the order-side upsert helper from the raw stream so DeltaStream writes
-- a proper token-keyed Kafka changelog topic for the downstream changelog join.
CREATE CHANGELOG polymarket.public.pm_orders_filled_by_id_cl
WITH (
  'store' = 'warpstream',
  'topic' = 'demo_pm_orders_filled_by_id',
  'value.format' = 'json',
  'enable.upsert.mode' = true,
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
)
AS
SELECT
  id,
  MAX(block_number) AS block_number,
  MAX(block_timestamp) AS block_timestamp,
  MAX(transaction_hash) AS transaction_hash,
  MAX(address) AS address,
  MAX(user_id) AS user_id,
  MAX(asset) AS asset,
  MAX(amount_usdc) AS amount_usdc,
  MAX(amount_shares) AS amount_shares,
  MAX(price) AS price,
  MAX(tx_type) AS tx_type,
  MAX(side) AS side,
  MAX(order_hash) AS order_hash,
  MAX(counterparty_id) AS counterparty_id,
  MAX(order_type) AS order_type,
  MAX(fee) AS fee,
  MAX(builder) AS builder,
  MAX(_gs_op) AS _gs_op
FROM polymarket.public.pm_orders_filled_s WITH (
  'starting.position' = 'earliest',
  'source.allow.latency.millis' = 30000
)
GROUP BY id;

ALTER RELATION pm_orders_filled_by_id_cl SET description =
'Persisted order_filled changelog keyed by fill id for DeltaStream-native changelog joins. Built from the raw order_filled stream so the sink topic has valid upsert semantics.';

-- ============================================================================
-- Phase 3B: DeltaStream-Native Enrichment Validation
-- ============================================================================
-- Changelog join is the working general-case path. It does not preserve
-- unmatched orders because DeltaStream changelog joins support INNER JOIN only.
-- That tradeoff is acceptable for validating whether DeltaStream can enrich the
-- common case without relying on the UDF. To avoid Kafka sink checkpoint
-- timeouts during validation, the validation MV reads directly from the
-- changelog join instead of first materializing a Kafka-backed enriched
-- changelog.

CREATE MATERIALIZED VIEW polymarket.public.pm_orders_filled_enriched_validation_mv
WITH (
  'retention.millis' = 2592000000,
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
)
AS
SELECT
  o.id,
  o.user_id,
  o.asset,
  CAST(o.block_timestamp AS BIGINT) AS block_timestamp,
  CAST(o.amount_usdc AS DOUBLE) AS amount_usdc,
  CAST(o.amount_shares AS DOUBLE) AS amount_shares,
  CAST(o.price AS DOUBLE) AS price,
  o.side,
  CAST(o.fee AS DOUBLE) AS fee,
  g.token_id AS gamma_token_id,
  g.market_question,
  g.market_updated_at
FROM polymarket.public.pm_orders_filled_by_id_cl o WITH (
  'source.allow.latency.millis' = 30000
)
JOIN polymarket.public.pm_gamma_token_question_cl g WITH (
  'source.allow.latency.millis' = 30000
)
ON o.asset = g.token_id;

ALTER RELATION pm_orders_filled_enriched_validation_mv SET description =
'Validation MV for the order_filled -> token_id -> market_question changelog join. Reads directly from the join to avoid an intermediate Kafka sink during validation.';
