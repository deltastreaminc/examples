-- ============================================================
-- Add human-readable metadata
-- ============================================================
-- This turns asset IDs into useful agent context:
-- question, outcome, URL, market state, category.
-- ============================================================

CREATE STREAM pm_named_asset_signal_1h_s
WITH (
  'topic' = 'hojjat_pm_named_asset_signal_1h',
  'value.format' = 'json',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  s.asset,
  md.market_id,
  md.condition_id,
  md.market_title,
  md.outcome_label,
  md.outcome_index,
  md.slug,
  md.category,
  md.market_url,
  md.market_state,
  md.active,
  md.closed,
  md.accepting_orders,
  md.end_date,
  md.start_date,
  md.updated_at,
  md.last_trade_price,
  md.best_ask,
  md.best_bid,
  md.gamma_volume,
  md.gamma_volume_24h,
  md.gamma_spread,

  s.window_start,
  s.window_end,
  s.ctx_time_ms,
  s.latest_block_number,

  s.fills_count_1h,
  s.filled_usdc_1h,
  s.filled_shares_1h,
  s.buy_usdc_1h,
  s.sell_usdc_1h,
  s.buy_shares_1h,
  s.sell_shares_1h,
  s.net_shares_1h,
  s.avg_fill_price_1h,
  s.min_fill_price_1h,
  s.max_fill_price_1h,
  s.fee_total_1h,
  s.large_fill_count_1h,
  s.large_fill_usdc_1h,

  s.matches_count_1h,
  s.matched_usdc_1h,
  s.matched_shares_1h,
  s.matched_buy_usdc_1h,
  s.matched_sell_usdc_1h,
  s.avg_match_price_1h,
  s.min_match_price_1h,
  s.max_match_price_1h,
  s.large_match_count_1h
FROM pm_asset_signal_1h_s s WITH ( 'starting.position' = 'earliest')
JOIN pm_market_asset_metadata_c md
  ON s.asset = md.asset;


-- Build final live signal radar context


-- ============================================================
-- Final live signal radar context
-- ============================================================
-- This is the main agent-ready context.
--
-- It computes:
--   signal_score
--   buy_sell_imbalance_1h
--   price_range_1h
--   large_fill_volume_share_1h
--   activity_band
--   signal_type
--   signal_reason
--
-- The agent should explain these fields, not recompute them.
-- ============================================================

CREATE STREAM pm_live_signal_radar_context_s
WITH (
  'topic' = 'hojjat_pm_live_signal_radar_context',
  'value.format' = 'json',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  asset,
  market_id,
  condition_id,
  market_title,
  outcome_label,
  outcome_index,
  slug,
  category,
  market_url,
  market_state,
  active,
  closed,
  accepting_orders,
  end_date,
  start_date,
  updated_at,

  window_start,
  window_end,
  ctx_time_ms,
  latest_block_number,

  last_trade_price,
  best_ask,
  best_bid,
  gamma_volume,
  gamma_volume_24h,
  gamma_spread,

  fills_count_1h,
  filled_usdc_1h,
  filled_shares_1h,
  buy_usdc_1h,
  sell_usdc_1h,
  buy_shares_1h,
  sell_shares_1h,
  net_shares_1h,
  avg_fill_price_1h,
  min_fill_price_1h,
  max_fill_price_1h,
  fee_total_1h,
  large_fill_count_1h,
  large_fill_usdc_1h,

  matches_count_1h,
  matched_usdc_1h,
  matched_shares_1h,
  matched_buy_usdc_1h,
  matched_sell_usdc_1h,
  avg_match_price_1h,
  min_match_price_1h,
  max_match_price_1h,
  large_match_count_1h,

  CASE
    WHEN filled_usdc_1h IS NULL THEN 0.0
    ELSE filled_usdc_1h
  END
  +
  CASE
    WHEN matched_usdc_1h IS NULL THEN 0.0
    ELSE matched_usdc_1h * 0.25
  END
  +
  CASE
    WHEN large_fill_count_1h IS NULL THEN 0.0
    ELSE large_fill_count_1h * 1000.0
  END
  +
  CASE
    WHEN max_fill_price_1h IS NULL OR min_fill_price_1h IS NULL THEN 0.0
    ELSE (max_fill_price_1h - min_fill_price_1h) * 10000.0
  END AS signal_score,

  CASE
    WHEN buy_usdc_1h + sell_usdc_1h = 0.0 THEN 0.0
    ELSE (buy_usdc_1h - sell_usdc_1h) / (buy_usdc_1h + sell_usdc_1h)
  END AS buy_sell_imbalance_1h,

  CASE
    WHEN max_fill_price_1h IS NULL OR min_fill_price_1h IS NULL THEN 0.0
    ELSE max_fill_price_1h - min_fill_price_1h
  END AS price_range_1h,

  CASE
    WHEN filled_usdc_1h = 0.0 THEN 0.0
    ELSE large_fill_usdc_1h / filled_usdc_1h
  END AS large_fill_volume_share_1h,

  CASE
    WHEN filled_usdc_1h >= 250000.0 THEN 'VERY_HIGH_ACTIVITY'
    WHEN filled_usdc_1h >= 75000.0 THEN 'HIGH_ACTIVITY'
    WHEN filled_usdc_1h >= 15000.0 THEN 'MODERATE_ACTIVITY'
    ELSE 'LOW_ACTIVITY'
  END AS activity_band,

  CASE
    WHEN large_fill_usdc_1h / filled_usdc_1h >= 0.70 THEN 'LARGE_FILL_DRIVEN'
    WHEN buy_usdc_1h > sell_usdc_1h * 2.5 THEN 'STRONG_BUY_PRESSURE'
    WHEN sell_usdc_1h > buy_usdc_1h * 2.5 THEN 'STRONG_SELL_PRESSURE'
    WHEN max_fill_price_1h - min_fill_price_1h >= 0.20 THEN 'WIDE_PRICE_RANGE'
    WHEN filled_usdc_1h >= 75000.0 THEN 'BROAD_HIGH_ACTIVITY'
    ELSE 'NORMAL_ACTIVITY'
  END AS signal_type,

  CASE
    WHEN large_fill_usdc_1h / filled_usdc_1h >= 0.70
      THEN 'Activity is heavily driven by large fills; treat this as a concentrated signal.'
    WHEN buy_usdc_1h > sell_usdc_1h * 2.5
      THEN 'Buy-side flow is much stronger than sell-side flow in the last hour.'
    WHEN sell_usdc_1h > buy_usdc_1h * 2.5
      THEN 'Sell-side flow is much stronger than buy-side flow in the last hour.'
    WHEN max_fill_price_1h - min_fill_price_1h >= 0.20
      THEN 'The outcome traded across a wide price range in the last hour.'
    WHEN filled_usdc_1h >= 75000.0
      THEN 'This market has meaningful recent filled volume.'
    ELSE 'This market has recent activity, but the signal may be thin.'
  END AS signal_reason
FROM pm_named_asset_signal_1h_s WITH ( 'starting.position' = 'earliest');




CREATE CHANGELOG pm_live_signal_radar_context_c (
    asset VARCHAR,
    market_id VARCHAR,
    condition_id VARCHAR,
    market_title VARCHAR,
    outcome_label VARCHAR,
    outcome_index INTEGER,
    slug VARCHAR,
    category VARCHAR,
    market_url VARCHAR,
    market_state VARCHAR,
    active BOOLEAN,
    closed BOOLEAN,
    accepting_orders BOOLEAN,
    end_date VARCHAR,
    start_date VARCHAR,
    updated_at BIGINT,

    window_start TIMESTAMP(3),
    window_end TIMESTAMP(3),
    ctx_time_ms BIGINT,
    latest_block_number BIGINT,

    last_trade_price DOUBLE,
    best_ask DOUBLE,
    best_bid DOUBLE,
    gamma_volume DOUBLE,
    gamma_volume_24h DOUBLE,
    gamma_spread DOUBLE,

    fills_count_1h BIGINT,
    filled_usdc_1h DOUBLE,
    filled_shares_1h DOUBLE,
    buy_usdc_1h DOUBLE,
    sell_usdc_1h DOUBLE,
    buy_shares_1h DOUBLE,
    sell_shares_1h DOUBLE,
    net_shares_1h DOUBLE,
    avg_fill_price_1h DOUBLE,
    min_fill_price_1h DOUBLE,
    max_fill_price_1h DOUBLE,
    fee_total_1h DOUBLE,
    large_fill_count_1h BIGINT,
    large_fill_usdc_1h DOUBLE,

    matches_count_1h BIGINT,
    matched_usdc_1h DOUBLE,
    matched_shares_1h DOUBLE,
    matched_buy_usdc_1h DOUBLE,
    matched_sell_usdc_1h DOUBLE,
    avg_match_price_1h DOUBLE,
    min_match_price_1h DOUBLE,
    max_match_price_1h DOUBLE,
    large_match_count_1h BIGINT,

    signal_score DOUBLE,
    buy_sell_imbalance_1h DOUBLE,
    price_range_1h DOUBLE,
    large_fill_volume_share_1h DOUBLE,
    activity_band VARCHAR,
    signal_type VARCHAR,
    signal_reason VARCHAR,

    PRIMARY KEY (asset, window_start)
) WITH (
    'topic' = 'hojjat_pm_live_signal_radar_context',
    'timestamp' = 'updated_at',
    'value.format' = 'json'
);



-- ============================================================
-- Wallet + asset flow in the last hour
-- ============================================================
-- This answers:
--   "Who is driving activity in this market?"
--   "Is this market broad or whale-like?"
-- ============================================================

CREATE CHANGELOG pm_wallet_asset_flow_1h_c
WITH (
  'topic' = 'hojjat_pm_wallet_asset_flow_1h',
  'value.format' = 'json',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  asset,
  user_id,
  asset || ':' || user_id AS user_asset_key,
  window_start,
  window_end,

  MAX(event_time_ms) AS ctx_time_ms,
  COUNT(fill_event_id) AS fills_count_1h,
  SUM(amount_usdc) AS filled_usdc_1h,
  SUM(amount_shares) AS filled_shares_1h,

  SUM(CASE WHEN trade_side = 'BUY' THEN amount_usdc ELSE 0.0 END) AS buy_usdc_1h,
  SUM(CASE WHEN trade_side = 'SELL' THEN amount_usdc ELSE 0.0 END) AS sell_usdc_1h,

  SUM(CASE WHEN trade_side = 'BUY' THEN amount_shares ELSE 0.0 END) AS buy_shares_1h,
  SUM(CASE WHEN trade_side = 'SELL' THEN amount_shares ELSE 0.0 END) AS sell_shares_1h,

  SUM(CASE WHEN trade_side = 'BUY' THEN amount_shares ELSE -1.0 * amount_shares END) AS net_shares_1h,

  SUM(fee) AS fee_total_1h,

  CASE
    WHEN SUM(amount_usdc) >= 50000.0 THEN 'HIGH_WALLET_ACTIVITY'
    WHEN SUM(amount_usdc) >= 10000.0 THEN 'MODERATE_WALLET_ACTIVITY'
    ELSE 'LOW_WALLET_ACTIVITY'
  END AS wallet_activity_flag
FROM HOP(pm_orders_filled_norm_s, SIZE 1 hour, ADVANCE BY 1 minute)
WITH (
  'timestamp' = 'event_time_ms',
  'starting.position' = 'earliest',
  'source.allow.latency.millis' = 30000
)
GROUP BY asset, user_id, window_start, window_end;




CREATE STREAM pm_wallet_asset_flow_1h_s (
    asset VARCHAR,
    user_id VARCHAR,
    user_asset_key VARCHAR,
    window_start TIMESTAMP(3),
    window_end TIMESTAMP(3),
    ctx_time_ms BIGINT,
    fills_count_1h BIGINT,
    filled_usdc_1h DOUBLE,
    filled_shares_1h DOUBLE,
    buy_usdc_1h DOUBLE,
    sell_usdc_1h DOUBLE,
    buy_shares_1h DOUBLE,
    sell_shares_1h DOUBLE,
    net_shares_1h DOUBLE,
    fee_total_1h DOUBLE,
    wallet_activity_flag VARCHAR
) WITH (
    'topic' = 'hojjat_pm_wallet_asset_flow_1h',
    'value.format' = 'json'
);



-- ============================================================
-- Add market metadata to wallet-asset flow
-- ============================================================

CREATE STREAM pm_named_wallet_asset_flow_1h_s
WITH (
  'topic' = 'hojjat_pm_named_wallet_asset_flow_1h',
  'value.format' = 'json',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  w.asset,
  md.market_id,
  md.market_title,
  md.outcome_label,
  md.outcome_index,
  md.category,
  md.market_url,

  w.user_id,
  w.user_asset_key,
  w.window_start,
  w.window_end,
  w.ctx_time_ms,

  w.fills_count_1h,
  w.filled_usdc_1h,
  w.filled_shares_1h,
  w.buy_usdc_1h,
  w.sell_usdc_1h,
  w.buy_shares_1h,
  w.sell_shares_1h,
  w.net_shares_1h,
  w.fee_total_1h,
  w.wallet_activity_flag
FROM pm_wallet_asset_flow_1h_s w WITH ('starting.position' = 'earliest')
JOIN pm_market_asset_metadata_c md
  ON w.asset = md.asset;



-- ============================================================
-- Wallet activity across all markets
-- ============================================================

CREATE CHANGELOG pm_wallet_activity_1h_c
WITH (
  'topic' = 'hojjat_pm_wallet_activity_1h',
  'value.format' = 'json',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  user_id,
  window_start,
  window_end,

  MAX(event_time_ms) AS ctx_time_ms,
  COUNT(fill_event_id) AS fills_count_1h,
  SUM(amount_usdc) AS filled_usdc_1h,
  SUM(amount_shares) AS filled_shares_1h,

  SUM(CASE WHEN trade_side = 'BUY' THEN amount_usdc ELSE 0.0 END) AS buy_usdc_1h,
  SUM(CASE WHEN trade_side = 'SELL' THEN amount_usdc ELSE 0.0 END) AS sell_usdc_1h,

  SUM(CASE WHEN trade_side = 'BUY' THEN amount_shares ELSE -1.0 * amount_shares END) AS net_shares_1h,

  SUM(fee) AS fee_total_1h,

  COUNT(CASE WHEN amount_usdc >= 1000.0 THEN fill_event_id ELSE NULL END) AS large_fill_count_1h,

  CASE
    WHEN SUM(amount_usdc) >= 100000.0 THEN 'VERY_ACTIVE_WALLET'
    WHEN SUM(amount_usdc) >= 25000.0 THEN 'ACTIVE_WALLET'
    WHEN SUM(amount_usdc) >= 5000.0 THEN 'MODERATE_WALLET'
    ELSE 'LOW_ACTIVITY_WALLET'
  END AS wallet_activity_band
FROM HOP(pm_orders_filled_norm_s, SIZE 1 hour, ADVANCE BY 1 minute)
WITH (
  'timestamp' = 'event_time_ms',
  'starting.position' = 'earliest',
  'source.allow.latency.millis' = 30000
)
GROUP BY user_id, window_start, window_end;





-- Recent fills context


-- ============================================================
-- Recent fills context
-- ============================================================
-- This gives the agent raw evidence behind a signal.
-- The agent should use this only for drill-down, not broad ranking.
-- ============================================================

CREATE STREAM pm_recent_fills_context_s
WITH (
  'topic' = 'hojjat_pm_recent_fills_context',
  'value.format' = 'json',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  event_time_ms AS ctx_time_ms,
  fill_event_id,
  block_number,
  transaction_hash,
  contract_address,
  user_id,
  asset,
  amount_usdc,
  amount_shares,
  price,
  tx_type,
  trade_side,
  order_hash,
  counterparty_id,
  order_type,
  fee,
  builder
FROM pm_orders_filled_norm_s WITH ('starting.position' = 'earliest');
