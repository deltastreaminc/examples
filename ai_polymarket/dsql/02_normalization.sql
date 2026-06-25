-- Normalize source streams

-- ============================================================
-- Normalize filled orders
-- ============================================================
-- Converts block_timestamp to event_time_ms in epoch milliseconds.
-- Renames fields that are awkward for SQL/agent use:
--   address -> contract_address
--   side    -> trade_side
-- ============================================================

CREATE STREAM pm_orders_filled_norm_s
WITH (
  'topic' = 'hojjat_pm_orders_filled_norm',
  'value.format' = 'json',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  CASE
    WHEN block_timestamp < 100000000000 THEN block_timestamp * 1000
    ELSE block_timestamp
  END AS event_time_ms,

  id AS fill_event_id,
  block_number,
  block_timestamp,
  transaction_hash,
  address AS contract_address,
  user_id,
  asset,
  amount_usdc,
  amount_shares,
  price,
  tx_type,
  side AS trade_side,
  order_hash,
  counterparty_id,
  order_type,
  fee,
  builder
FROM pm_orders_filled_s
WHERE _gs_op = 'i';


-- ============================================================
-- Normalize matched orders
-- ============================================================

CREATE STREAM pm_orders_matched_norm_s
WITH (
  'topic' = 'hojjat_pm_orders_matched_norm',
  'value.format' = 'json',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  CASE
    WHEN block_timestamp < 100000000000 THEN block_timestamp * 1000
    ELSE block_timestamp
  END AS event_time_ms,

  id AS match_event_id,
  block_number,
  block_timestamp,
  transaction_hash,
  address AS contract_address,
  user_id,
  asset,
  amount_usdc,
  amount_shares,
  price,
  tx_type,
  side AS trade_side,
  order_hash
FROM pm_orders_matched_s
WHERE _gs_op = 'i';


-- ============================================================
-- Normalize balances
-- ============================================================

CREATE CHANGELOG pm_user_balances_norm_c
WITH (
  'topic' = 'hojjat_pm_user_balances_norm',
  'value.format' = 'json',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  id,

  CASE
    WHEN block_timestamp < 100000000000 THEN block_timestamp * 1000
    ELSE block_timestamp
  END AS event_time_ms,

  owner_address,
  contract_address,
  token_id,
  token_type,
  block_number,
  CAST(balance AS DECIMAL(38, 18)) AS balance_amount
FROM pm_user_balances_c WITH ( 'starting.position' = 'earliest' )
WHERE _gs_op = 'i';
