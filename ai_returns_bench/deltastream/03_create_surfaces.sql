-- Returns benchmark DeltaStream setup
-- Step 3: create raw and combined agent surfaces.
-- Run after deltastream/02_load_seed_data.sql.

-- Raw MVs exposed to the raw agent
CREATE MATERIALIZED VIEW IF NOT EXISTS aws_returns_bench.public.orders_raw_mv AS
SELECT
  order_id,
  customer_id,
  customer_segment,
  order_ts,
  order_amount_usd,
  region
FROM aws_returns_bench.public.orders_cl WITH ('starting.position' = 'earliest')
QUERY WITH ('query.name' = aws_returns_orders_raw_mv_q);

CREATE MATERIALIZED VIEW IF NOT EXISTS aws_returns_bench.public.shipments_raw_mv AS
SELECT
  shipment_id,
  order_id,
  carrier,
  promised_days,
  delivered_days,
  delivered_on_time,
  shipment_ts
FROM aws_returns_bench.public.shipments_cl WITH ('starting.position' = 'earliest')
QUERY WITH ('query.name' = aws_returns_shipments_raw_mv_q);

CREATE MATERIALIZED VIEW IF NOT EXISTS aws_returns_bench.public.returns_raw_mv AS
SELECT
  return_id,
  order_id,
  return_reason,
  return_ts,
  return_amount_usd
FROM aws_returns_bench.public.returns_cl WITH ('starting.position' = 'earliest')
QUERY WITH ('query.name' = aws_returns_returns_raw_mv_q);

CREATE MATERIALIZED VIEW IF NOT EXISTS aws_returns_bench.public.refunds_raw_mv AS
SELECT
  refund_id,
  return_id,
  order_id,
  refunded_amount_usd,
  refund_ts,
  refund_status
FROM aws_returns_bench.public.refunds_cl WITH ('starting.position' = 'earliest')
QUERY WITH ('query.name' = aws_returns_refunds_raw_mv_q);

-- Combined precomputed context MV
-- Grain: one joined return/refund fact row with dimensions from all 4 topics.
-- Drive from the refunds stream because refund_ts is the latest event-time per
-- joined record; this ensures the orders/shipments/returns changelog state is
-- materialized in the join state by the time each refund event arrives.
CREATE MATERIALIZED VIEW IF NOT EXISTS aws_returns_bench.public.customer_returns_context_mv AS
SELECT
  f.refund_id AS refund_id,
  rt.return_id AS return_id,
  rt.order_id AS order_id,
  o.customer_id AS customer_id,
  o.customer_segment AS customer_segment,
  o.region AS region,
  rt.return_reason AS return_reason,
  s.carrier AS carrier,
  s.delivered_on_time AS delivered_on_time,
  o.order_ts AS order_ts,
  s.shipment_ts AS shipment_ts,
  rt.return_ts AS return_ts,
  f.refund_ts AS refund_ts,
  rt.return_amount_usd AS return_amount_usd,
  f.refunded_amount_usd AS refunded_amount_usd,
  rt.return_amount_usd - f.refunded_amount_usd AS refund_gap_usd,
  (
    UNIX_TIMESTAMP(DATE_FORMAT(f.refund_ts, 'yyyy-MM-dd HH:mm:ss'))
    - UNIX_TIMESTAMP(DATE_FORMAT(rt.return_ts, 'yyyy-MM-dd HH:mm:ss'))
  ) / 3600.0 AS refund_lag_hours

FROM aws_returns_bench.public.refunds_stream f WITH ('starting.position' = 'earliest', 'timestamp' = 'refund_ts', 'source.idle.timeout.millis' = 30000)
JOIN aws_returns_bench.public.returns_cl rt WITH ('starting.position' = 'earliest', 'timestamp' = 'return_ts', 'source.idle.timeout.millis' = 30000)
ON f.return_id = rt.return_id
JOIN aws_returns_bench.public.orders_cl o WITH ('starting.position' = 'earliest', 'timestamp' = 'order_ts', 'source.idle.timeout.millis' = 30000)
ON o.order_id = f.order_id
JOIN aws_returns_bench.public.shipments_cl s WITH ('starting.position' = 'earliest', 'timestamp' = 'shipment_ts', 'source.idle.timeout.millis' = 30000)
ON s.order_id = f.order_id
QUERY WITH ('query.name' = aws_returns_customer_returns_context_mv_q)
;
