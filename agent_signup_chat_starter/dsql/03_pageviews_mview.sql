CREATE MATERIALIZED VIEW starter.public.pageviews_mview
WITH (
  'retention.millis' = 3600000,
  'timestamp' = 'viewtime'
)
AS
SELECT
  viewtime,
  userid,
  pageid
FROM starter.public.pageviews;
