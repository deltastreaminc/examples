CREATE STREAM starter.public.pageviews (
  viewtime BIGINT,
  userid VARCHAR,
  pageid VARCHAR
)
WITH (
  'topic'='pageviews',
  'value.format'='json',
  'key.format'='json',
  'key.type'='STRUCT<userid VARCHAR>'
);
