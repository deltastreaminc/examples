-- Historical baseline order-only pipeline.
-- This file is intentionally numbered after the Gamma pipeline files because it
-- does not participate in the Gamma-first enrichment workflow.
--
-- MV1 activity pipeline over demo_ topics with all query sources starting at earliest.
-- Relation names do not include demo_; warpstream sink topics do.
-- Protected upstream source topic: demo_pm_orders_filled must never be deleted,
-- truncated, or repurposed from this project.

USE DATABASE polymarket;
USE SCHEMA public;

-- Source stream on current Goldsky order_filled topic in warpstream store.
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

-- Enriched fills stream. All query inputs start from earliest.
CREATE STREAM polymarket.public.pm_orders_filled_enriched_activity_s
WITH (
  'store' = 'warpstream',
  'topic' = 'demo_pm_orders_filled_enriched_activity_s'
)
AS
SELECT
  o.id,
  CAST(o.block_number AS BIGINT) AS block_number,
  CAST(o.block_timestamp AS BIGINT) AS block_timestamp,
  (CAST(o.block_timestamp AS BIGINT) * 1000) AS event_time_ms,
  o.transaction_hash,
  o.address,
  o.user_id,
  o.asset,
  CONCAT(o.user_id, ':', o.asset) AS user_asset_key,
  CAST(o.amount_usdc AS DOUBLE) AS amount_usdc,
  CAST(o.amount_shares AS DOUBLE) AS amount_shares,
  CAST(o.price AS DOUBLE) AS price,
  o.tx_type,
  o.side,
  o.order_hash,
  o.counterparty_id,
  o.order_type,
  CAST(o.fee AS DOUBLE) AS fee,
  o.builder
FROM polymarket.public.pm_orders_filled_s o WITH ('starting.position' = 'earliest');

-- Agent-facing activity MV. Source starts from earliest.
CREATE MATERIALIZED VIEW polymarket.public.polymarket_trader_activity_mv
WITH (
  'retention.millis' = 31536000000,
  'timestamp' = 'event_time_ms'
)
AS
SELECT
  event_time_ms,
  user_asset_key,
  user_id,
  asset,
  block_timestamp,
  order_hash,
  side,
  amount_usdc,
  amount_shares,
  price,
  fee,
  COUNT(*) OVER (
    PARTITION BY user_asset_key
    ORDER BY record_timestamp()
    RANGE BETWEEN 1 HOUR PRECEDING AND CURRENT ROW
  ) AS fills_count_1h,
  SUM(amount_usdc) OVER (
    PARTITION BY user_asset_key
    ORDER BY record_timestamp()
    RANGE BETWEEN 1 HOUR PRECEDING AND CURRENT ROW
  ) AS filled_usdc_1h,
  SUM(amount_shares) OVER (
    PARTITION BY user_asset_key
    ORDER BY record_timestamp()
    RANGE BETWEEN 1 HOUR PRECEDING AND CURRENT ROW
  ) AS filled_shares_1h,
  SUM(CASE WHEN side = 'BUY' THEN amount_shares ELSE 0 END) OVER (
    PARTITION BY user_asset_key
    ORDER BY record_timestamp()
    RANGE BETWEEN 1 HOUR PRECEDING AND CURRENT ROW
  ) AS buy_shares_1h,
  SUM(CASE WHEN side = 'SELL' THEN amount_shares ELSE 0 END) OVER (
    PARTITION BY user_asset_key
    ORDER BY record_timestamp()
    RANGE BETWEEN 1 HOUR PRECEDING AND CURRENT ROW
  ) AS sell_shares_1h,
  SUM(
    CASE
      WHEN side = 'BUY' THEN amount_shares
      WHEN side = 'SELL' THEN -1 * amount_shares
      ELSE 0
    END
  ) OVER (
    PARTITION BY user_asset_key
    ORDER BY record_timestamp()
    RANGE BETWEEN 1 HOUR PRECEDING AND CURRENT ROW
  ) AS net_shares_1h,
  SUM(fee) OVER (
    PARTITION BY user_asset_key
    ORDER BY record_timestamp()
    RANGE BETWEEN 1 HOUR PRECEDING AND CURRENT ROW
  ) AS fee_total_1h,
  MAX(block_timestamp) OVER (
    PARTITION BY user_asset_key
    ORDER BY record_timestamp()
    RANGE BETWEEN 1 HOUR PRECEDING AND CURRENT ROW
  ) AS last_fill_time_s,
  CASE
    WHEN COUNT(*) OVER (
      PARTITION BY user_asset_key
      ORDER BY record_timestamp()
      RANGE BETWEEN 1 HOUR PRECEDING AND CURRENT ROW
    ) >= 10 THEN 'high_activity'
    WHEN COUNT(*) OVER (
      PARTITION BY user_asset_key
      ORDER BY record_timestamp()
      RANGE BETWEEN 1 HOUR PRECEDING AND CURRENT ROW
    ) >= 3 THEN 'moderate_activity'
    ELSE 'low_activity'
  END AS activity_flag
FROM polymarket.public.pm_orders_filled_enriched_activity_s WITH ('starting.position' = 'earliest');

ALTER RELATION polymarket_trader_activity_mv SET description =
'Trader activity context over Polymarket order_filled topic. Source reads and query inputs start from earliest offsets. Warpstream sink topics use demo_ prefix.';
