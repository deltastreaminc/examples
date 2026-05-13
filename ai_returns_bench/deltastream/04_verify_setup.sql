-- Returns benchmark DeltaStream setup
-- Optional: post-setup verification queries

SELECT *
FROM deltastream.sys."relations"
WHERE database_name = 'aws_returns_bench'
LIMIT 100;

SELECT *
FROM deltastream.sys."relation_columns"
WHERE database_name = 'aws_returns_bench'
  AND schema_name = 'public'
  AND relation_name = 'customer_returns_context_mv'
LIMIT 100;

SELECT count(*) AS orders_cnt FROM aws_returns_bench.public.orders_raw_mv;
SELECT count(*) AS shipments_cnt FROM aws_returns_bench.public.shipments_raw_mv;
SELECT count(*) AS returns_cnt FROM aws_returns_bench.public.returns_raw_mv;
SELECT count(*) AS refunds_cnt FROM aws_returns_bench.public.refunds_raw_mv;

SELECT
  COUNT(*) AS joined_rows,
  SUM(return_amount_usd) AS total_return_amount_usd,
  SUM(refunded_amount_usd) AS total_refunded_amount_usd,
  SUM(refund_gap_usd) AS total_refund_gap_usd
FROM aws_returns_bench.public.customer_returns_context_mv;
