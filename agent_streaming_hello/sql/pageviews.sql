CREATE STREAM IF NOT EXISTS {stream_name} (
  event_ts BIGINT,
  user_id VARCHAR,
  session_id VARCHAR,
  page VARCHAR
)
WITH (
  'store' = '{store}',
  'topic' = '{topic_name}',
  'value.format' = 'json',
  'timestamp' = 'event_ts'
);

CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
WITH (
  'query.name' = '{query_name}'
)
AS
SELECT
  page,
  COUNT(*) AS pageview_count
FROM {stream_name}
GROUP BY page;
