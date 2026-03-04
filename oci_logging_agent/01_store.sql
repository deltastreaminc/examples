-- ============================================================
-- Step 1: Create the DeltaStream Stores
--
-- Two stores are required:
--
-- Store 1 (oci_streaming): connects to OCI Streaming (native)
--   This is where Connector Hub delivers raw events from OCI
--   Logging. Uses SASL/PLAIN with an OCI Auth Token.
--
-- Store 2 (oci_streaming_kafka): connects to OCI Streaming
--   for Apache Kafka. This is where DeltaStream writes the
--   enriched output streams. Uses SASL/SCRAM-SHA-512 with
--   a dedicated super-user.
--
-- Run both before proceeding to Step 2.
-- Replace all <PLACEHOLDER> values with your own values
-- from the OCI Console (see .env.example for guidance).
-- ============================================================


-- ------------------------------------------------------------
-- Store 1: OCI Streaming (native)
-- Source store — receives raw events from Connector Hub
--
-- Auth pattern: SASL/PLAIN + OCI Auth Token
-- Username format: <tenancy>/<oci_username>/<stream_pool_ocid>
-- ------------------------------------------------------------
CREATE STORE "oci_streaming"
WITH (
  'type'              = 'KAFKA',
  'access.region'     = 'AWS_US_EAST_1',

  -- Broker endpoint — OCI Console → Streaming → Stream Pools
  -- → your pool → Kafka Connection Settings
  'uris'              = '<OCI_STREAMING_BOOTSTRAP>',

  'security.protocol' = 'SASL_SSL',
  'sasl.mechanism'    = 'PLAIN',

  -- Format: <tenancy_name>/<oci_username>/<stream_pool_ocid>
  'sasl.username'     = '<OCI_SASL_USERNAME>',

  -- OCI Auth Token — NOT your console password
  -- Generate at: OCI Console → Profile → Auth Tokens
  'sasl.password'     = '<OCI_AUTH_TOKEN>'
);


-- ------------------------------------------------------------
-- Store 2: OCI Streaming for Apache Kafka
-- Output store — DeltaStream writes enriched streams here
--
-- Auth pattern: SASL/SCRAM-SHA-512 + super-user credentials
-- Bootstrap format: bootstrap-ext-<id>.kafka.<region>.oci.oraclecloud.com:10000
-- ------------------------------------------------------------
CREATE STORE "oci_streaming_kafka"
WITH (
  'type'              = 'KAFKA',
  'access.region'     = 'AWS_US_EAST_1',

  -- Broker endpoint — OCI Console → Streaming → your Kafka cluster
  -- → Bootstrap Servers
  'uris'              = '<OCI_KAFKA_BOOTSTRAP>',

  'security.protocol' = 'SASL_SSL',
  'sasl.mechanism'    = 'SCRAM-SHA-512',

  -- Super-user credentials provisioned with your Kafka cluster
  -- OCI Console → Streaming → your cluster → Users
  'sasl.username'     = '<OCI_KAFKA_USERNAME>',
  'sasl.password'     = '<OCI_KAFKA_PASSWORD>'
);
