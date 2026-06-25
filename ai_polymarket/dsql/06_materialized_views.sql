-- ============================================================
-- MAIN AGENT CONTEXT
-- ============================================================

CREATE MATERIALIZED VIEW pm_live_signal_radar_mv
WITH ('retention.millis' = 2592000000)
AS
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

  signal_score,
  buy_sell_imbalance_1h,
  price_range_1h,
  large_fill_volume_share_1h,
  activity_band,
  signal_type,
  signal_reason
FROM pm_live_signal_radar_context_c WITH ( 'starting.position' = 'earliest');





-- ============================================================
-- WALLET-ASSET DRILL-DOWN CONTEXT
-- ============================================================

CREATE MATERIALIZED VIEW pm_wallet_asset_flow_mv
WITH ('retention.millis' = 2592000000)
AS
SELECT
  asset,
  market_id,
  market_title,
  outcome_label,
  outcome_index,
  category,
  market_url,

  user_id,
  user_asset_key,
  window_start,
  window_end,
  ctx_time_ms,

  fills_count_1h,
  filled_usdc_1h,
  filled_shares_1h,
  buy_usdc_1h,
  sell_usdc_1h,
  buy_shares_1h,
  sell_shares_1h,
  net_shares_1h,
  fee_total_1h,
  wallet_activity_flag
FROM pm_named_wallet_asset_flow_1h_s WITH ('starting.position' = 'earliest');


-- ============================================================
-- WALLET ACTIVITY CONTEXT
-- ============================================================

CREATE MATERIALIZED VIEW pm_wallet_activity_mv
WITH ('retention.millis' = 2592000000)
AS
SELECT
  user_id,
  window_start,
  window_end,
  ctx_time_ms,
  fills_count_1h,
  filled_usdc_1h,
  filled_shares_1h,
  buy_usdc_1h,
  sell_usdc_1h,
  net_shares_1h,
  fee_total_1h,
  large_fill_count_1h,
  wallet_activity_band
FROM pm_wallet_activity_1h_c WITH ('starting.position' = 'earliest');



-- ============================================================
-- RECENT FILLS EVIDENCE CONTEXT
-- ============================================================

CREATE MATERIALIZED VIEW pm_recent_fills_mv
WITH ('retention.millis' = 2592000000)
AS
SELECT
  ctx_time_ms,
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
FROM pm_recent_fills_context_s  WITH ('starting.position' = 'earliest');



-- ============================================================
-- MARKET METADATA CONTEXT
-- ============================================================

CREATE MATERIALIZED VIEW pm_market_asset_metadata_mv
WITH ('retention.millis' = 2592000000)
AS
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
  last_trade_price,
  best_ask,
  best_bid,
  gamma_volume,
  gamma_volume_24h,
  gamma_spread
FROM pm_market_asset_metadata_c WITH ('starting.position' = 'earliest');



-- ============================================================
-- USER BALANCES CONTEXT
-- ============================================================

CREATE MATERIALIZED VIEW pm_user_balances_mv
AS
SELECT
  id,
  event_time_ms AS ctx_time_ms,
  owner_address,
  contract_address,
  token_id,
  token_type,
  block_number,
  balance_amount
FROM pm_user_balances_norm_c WITH ('starting.position' = 'earliest');
