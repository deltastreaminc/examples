-- Build rolling one-hour market activity

-- ============================================================
-- One-hour filled-order flow by asset
-- ============================================================
-- This produces rolling one-hour windows refreshed every minute.
-- This is the main signal for:
--   - buy pressure
--   - sell pressure
--   - volume
--   - large fills
--   - price range
--   - net shares
-- ============================================================

CREATE CHANGELOG pm_asset_filled_flow_1h_c
WITH (
  'topic' = 'hojjat_pm_asset_filled_flow_1h',
  'value.format' = 'json',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  asset || '_' || CAST((1000 * UNIX_TIMESTAMP(CAST(window_start AS STRING)) + EXTRACT(MILLISECOND FROM window_start)) AS STRING)  AS asset_window_start,
  asset,
  window_start,
  window_end,

  MAX(event_time_ms) AS ctx_time_ms,
  MAX(block_number) AS latest_block_number,

  COUNT(fill_event_id) AS fills_count_1h,
  SUM(amount_usdc) AS filled_usdc_1h,
  SUM(amount_shares) AS filled_shares_1h,

  SUM(CASE WHEN trade_side = 'BUY' THEN amount_usdc ELSE 0.0 END) AS buy_usdc_1h,
  SUM(CASE WHEN trade_side = 'SELL' THEN amount_usdc ELSE 0.0 END) AS sell_usdc_1h,

  SUM(CASE WHEN trade_side = 'BUY' THEN amount_shares ELSE 0.0 END) AS buy_shares_1h,
  SUM(CASE WHEN trade_side = 'SELL' THEN amount_shares ELSE 0.0 END) AS sell_shares_1h,

  SUM(CASE WHEN trade_side = 'BUY' THEN amount_shares ELSE -1.0 * amount_shares END) AS net_shares_1h,

  AVG(price) AS avg_fill_price_1h,
  MIN(price) AS min_fill_price_1h,
  MAX(price) AS max_fill_price_1h,

  SUM(fee) AS fee_total_1h,

  COUNT(CASE WHEN amount_usdc >= 1000.0 THEN fill_event_id ELSE NULL END) AS large_fill_count_1h,
  SUM(CASE WHEN amount_usdc >= 1000.0 THEN amount_usdc ELSE 0.0 END) AS large_fill_usdc_1h
FROM HOP(pm_orders_filled_norm_s, SIZE 1 hour, ADVANCE BY 1 minute)
WITH (
  'timestamp' = 'event_time_ms',
  'starting.position' = 'earliest',
  'source.allow.latency.millis' = 30000
)
GROUP BY asset, window_start, window_end;


-- ============================================================
-- One-hour matched-order flow by asset
-- ============================================================
-- Secondary signal. Useful to confirm matched activity and
-- compare against filled flow.
-- ============================================================

CREATE CHANGELOG pm_asset_matched_flow_1h_c
WITH (
  'topic' = 'hojjat_pm_asset_matched_flow_1h',
  'value.format' = 'json',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  asset || '_' || CAST((1000 * UNIX_TIMESTAMP(CAST(window_start AS STRING)) + EXTRACT(MILLISECOND FROM window_start)) AS STRING)  AS asset_window_start,
  asset,
  window_start,
  window_end,

  MAX(event_time_ms) AS ctx_time_ms,
  MAX(block_number) AS latest_block_number,

  COUNT(match_event_id) AS matches_count_1h,
  SUM(amount_usdc) AS matched_usdc_1h,
  SUM(amount_shares) AS matched_shares_1h,

  SUM(CASE WHEN trade_side = 'BUY' THEN amount_usdc ELSE 0.0 END) AS matched_buy_usdc_1h,
  SUM(CASE WHEN trade_side = 'SELL' THEN amount_usdc ELSE 0.0 END) AS matched_sell_usdc_1h,

  AVG(price) AS avg_match_price_1h,
  MIN(price) AS min_match_price_1h,
  MAX(price) AS max_match_price_1h,

  COUNT(CASE WHEN amount_usdc >= 1000.0 THEN match_event_id ELSE NULL END) AS large_match_count_1h
FROM HOP(pm_orders_matched_norm_s, SIZE 1 hour, ADVANCE BY 1 minute)
WITH (
  'timestamp' = 'event_time_ms',
  'starting.position' = 'earliest',
  'source.allow.latency.millis' = 30000
)
GROUP BY asset, window_start, window_end;






CREATE STREAM pm_asset_filled_flow_1h_stream (
    asset_window_start VARCHAR,
    asset VARCHAR,
    window_start TIMESTAMP(3),
    window_end TIMESTAMP(3),
    ctx_time_ms BIGINT,
    latest_block_number BIGINT,
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
    large_fill_usdc_1h DOUBLE
) WITH (
    'topic' = 'hojjat_pm_asset_filled_flow_1h',
    'timestamp' = 'window_start',
    'value.format' = 'json'
);





CREATE STREAM pm_asset_matched_flow_1h_stream (
    asset_window_start VARCHAR,
    asset VARCHAR,
    window_start TIMESTAMP(3),
    window_end TIMESTAMP(3),
    ctx_time_ms BIGINT,
    latest_block_number BIGINT,
    matches_count_1h BIGINT,
    matched_usdc_1h DOUBLE,
    matched_shares_1h DOUBLE,
    matched_buy_usdc_1h DOUBLE,
    matched_sell_usdc_1h DOUBLE,
    avg_match_price_1h DOUBLE,
    min_match_price_1h DOUBLE,
    max_match_price_1h DOUBLE,
    large_match_count_1h BIGINT
) WITH (
    'topic' = 'hojjat_pm_asset_matched_flow_1h',
    'timestamp' = 'window_start',
    'value.format' = 'json'
);






-- Combine filled and matched flow

-- ============================================================
-- Combined asset signal context
-- ============================================================
-- Two-way changelog/changelog join:
--   pm_asset_filled_flow_1h_c
--   pm_asset_matched_flow_1h_c
--
-- This creates one enriched rolling context row per asset/window.
-- ============================================================

CREATE STREAM pm_asset_signal_1h_s
WITH (
  'topic' = 'hojjat_pm_asset_signal_1h',
  'value.format' = 'json',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  f.asset,
  f.window_start,
  f.window_end,

  CASE
    WHEN f.ctx_time_ms >= m.ctx_time_ms THEN f.ctx_time_ms
    ELSE m.ctx_time_ms
  END AS ctx_time_ms,

  CASE
    WHEN f.latest_block_number >= m.latest_block_number THEN f.latest_block_number
    ELSE m.latest_block_number
  END AS latest_block_number,

  f.fills_count_1h,
  f.filled_usdc_1h,
  f.filled_shares_1h,
  f.buy_usdc_1h,
  f.sell_usdc_1h,
  f.buy_shares_1h,
  f.sell_shares_1h,
  f.net_shares_1h,
  f.avg_fill_price_1h,
  f.min_fill_price_1h,
  f.max_fill_price_1h,
  f.fee_total_1h,
  f.large_fill_count_1h,
  f.large_fill_usdc_1h,

  m.matches_count_1h,
  m.matched_usdc_1h,
  m.matched_shares_1h,
  m.matched_buy_usdc_1h,
  m.matched_sell_usdc_1h,
  m.avg_match_price_1h,
  m.min_match_price_1h,
  m.max_match_price_1h,
  m.large_match_count_1h,
  m.asset AS m_asset,
  m.window_start AS m_window_start,
  m.window_end AS m_window_end
FROM pm_asset_filled_flow_1h_stream f WITH ( 'starting.position' = 'earliest' , 'flink.sql.state.ttl' = '24h')
JOIN pm_asset_matched_flow_1h_stream m WITH ( 'starting.position' = 'earliest' , 'flink.sql.state.ttl' = '24h')
  ON f.asset_window_start = m.asset_window_start
QUERY WITH ('state.ttl.millis' = 86400000);


-- Add market metadata
