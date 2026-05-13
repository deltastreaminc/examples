-- Returns benchmark DeltaStream setup (base objects)
-- Step 1/2: database, streams, and changelogs.
-- Step 2 (seed load via INSERT INTO ENTITY) is deltastream/02_load_seed_data.sql.
-- Step 3 (surfaces) is in deltastream/03_create_surfaces.sql.
-- Prerequisite: create the Kafka store manually first (see README).

CREATE DATABASE IF NOT EXISTS aws_returns_bench;


-- Source relations
CREATE STREAM IF NOT EXISTS aws_returns_bench.public.orders_stream (
  order_id VARCHAR,
  customer_id VARCHAR,
  customer_segment VARCHAR,
  order_ts TIMESTAMP_LTZ,
  order_amount_usd DOUBLE,
  region VARCHAR
)
WITH (
  'store' = 'aws_returns_kafka_store',
  'topic' = 'aws_returns_orders',
  'value.format' = 'json',
  'timestamp.format' = 'iso8601',
  'starting.position' = 'earliest',
  'topic.partitions' = 1,
  'topic.replicas' = 1
);

CREATE STREAM IF NOT EXISTS aws_returns_bench.public.shipments_stream (
  shipment_id VARCHAR,
  order_id VARCHAR,
  carrier VARCHAR,
  promised_days INTEGER,
  delivered_days INTEGER,
  delivered_on_time BOOLEAN,
  shipment_ts TIMESTAMP_LTZ
)
WITH (
  'store' = 'aws_returns_kafka_store',
  'topic' = 'aws_returns_shipments',
  'value.format' = 'json',
  'timestamp.format' = 'iso8601',
  'starting.position' = 'earliest',
  'topic.partitions' = 1,
  'topic.replicas' = 1
);

CREATE STREAM IF NOT EXISTS aws_returns_bench.public.returns_stream (
  return_id VARCHAR,
  order_id VARCHAR,
  return_reason VARCHAR,
  return_ts TIMESTAMP_LTZ,
  return_amount_usd DOUBLE
)
WITH (
  'store' = 'aws_returns_kafka_store',
  'topic' = 'aws_returns_returns',
  'value.format' = 'json',
  'timestamp.format' = 'iso8601',
  'starting.position' = 'earliest',
  'topic.partitions' = 1,
  'topic.replicas' = 1
);

CREATE STREAM IF NOT EXISTS aws_returns_bench.public.refunds_stream (
  refund_id VARCHAR,
  return_id VARCHAR,
  order_id VARCHAR,
  refunded_amount_usd DOUBLE,
  refund_ts TIMESTAMP_LTZ,
  refund_status VARCHAR
)
WITH (
  'store' = 'aws_returns_kafka_store',
  'topic' = 'aws_returns_refunds',
  'value.format' = 'json',
  'timestamp.format' = 'iso8601',
  'starting.position' = 'earliest',
  'topic.partitions' = 1,
  'topic.replicas' = 1
);

-- Changelogs on the same topics (zero-copy metadata pattern)
CREATE CHANGELOG IF NOT EXISTS aws_returns_bench.public.orders_cl (
  order_id VARCHAR,
  customer_id VARCHAR,
  customer_segment VARCHAR,
  order_ts TIMESTAMP_LTZ,
  order_amount_usd DOUBLE,
  region VARCHAR,
  PRIMARY KEY (order_id)
)
WITH (
  'store' = 'aws_returns_kafka_store',
  'topic' = 'aws_returns_orders',
  'value.format' = 'json',
  'timestamp.format' = 'iso8601',
  'starting.position' = 'earliest'
);

CREATE CHANGELOG IF NOT EXISTS aws_returns_bench.public.shipments_cl (
  shipment_id VARCHAR,
  order_id VARCHAR,
  carrier VARCHAR,
  promised_days INTEGER,
  delivered_days INTEGER,
  delivered_on_time BOOLEAN,
  shipment_ts TIMESTAMP_LTZ,
  PRIMARY KEY (order_id)
)
WITH (
  'store' = 'aws_returns_kafka_store',
  'topic' = 'aws_returns_shipments',
  'value.format' = 'json',
  'timestamp.format' = 'iso8601',
  'starting.position' = 'earliest'
);

CREATE CHANGELOG IF NOT EXISTS aws_returns_bench.public.returns_cl (
  return_id VARCHAR,
  order_id VARCHAR,
  return_reason VARCHAR,
  return_ts TIMESTAMP_LTZ,
  return_amount_usd DOUBLE,
  PRIMARY KEY (return_id)
)
WITH (
  'store' = 'aws_returns_kafka_store',
  'topic' = 'aws_returns_returns',
  'value.format' = 'json',
  'timestamp.format' = 'iso8601',
  'starting.position' = 'earliest'
);

CREATE CHANGELOG IF NOT EXISTS aws_returns_bench.public.refunds_cl (
  refund_id VARCHAR,
  return_id VARCHAR,
  order_id VARCHAR,
  refunded_amount_usd DOUBLE,
  refund_ts TIMESTAMP_LTZ,
  refund_status VARCHAR,
  PRIMARY KEY (refund_id)
)
WITH (
  'store' = 'aws_returns_kafka_store',
  'topic' = 'aws_returns_refunds',
  'value.format' = 'json',
  'timestamp.format' = 'iso8601',
  'starting.position' = 'earliest'
);

-- refunds_by_return_cl removed: unused by 03_create_surfaces.sql; the combined MV
-- joins refunds via refunds_stream/refunds_cl keyed on refund_id, not return_id.
