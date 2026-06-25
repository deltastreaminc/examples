-- Phase 2 of the Gamma enrichment pipeline.
-- Run this file after sql/01_gamma_markets_changelog.sql and before any
-- order-enrichment pipeline files. Its job is to normalize raw Gamma markets
-- into a DeltaStream-native token_id -> market_question helper relation for
-- downstream changelog joins.
--
-- Primary enrichment should come from DeltaStream-managed Gamma relations.
-- In the current scope, the only required Gamma field is market_question.
--
-- Live validation notes from DeltaStream:
-- 1. The protected raw Gamma topic is modeled as a changelog keyed by
--    conditionId; downstream dedupe should read from pm_gamma_markets_cl.
-- 2. Direct CREATE STREAM ... AS SELECT from pm_gamma_markets_cl with UNNEST
--    was rejected by DeltaStream because the query was inferred as CHANGELOG
--    output. The safe fallback is to declare a parallel raw stream over the
--    same protected topic and use that stream for flattening.
-- 3. A replayable helper stream plus an explicit token-keyed upsert changelog
--    did produce matched DeltaStream-native order enrichment via changelog join.
-- 4. CREATE FUNCTION_SOURCE may require a client path that can upload local
--    files. Keep the SQL here as reference, but treat UDF registration as a
--    manual prereq until the file-upload path is resolved.
--
-- Protected upstream source topics: demo_pm_orders_filled,
-- demo_pm_orders_matched, and demo_pm_gamma_markets must never be
-- deleted, truncated, or repurposed from this project.

USE DATABASE polymarket;
USE SCHEMA public;

-- ============================================================================
-- Phase 2A: Gamma Fallback UDF Registration
-- ============================================================================
-- Register the Java UDF fallback once per environment before creating the
-- order-enrichment stream. Update the jar path to your local checkout.
--
-- Note: tested DeltaStream CLI path currently rejected CREATE FUNCTION_SOURCE
-- with "function_source file not provided". Keep these statements as the
-- intended registration SQL, but execute them only via a client path that
-- successfully uploads the local jar.
--
-- CREATE FUNCTION_SOURCE gamma_udf_src
-- WITH (
--   'file' = '/absolute/path/to/gamma-udf/target/gamma-udf-0.1.0-SNAPSHOT-all.jar',
--   'description' = 'Polymarket Gamma question lookup UDF fallback'
-- );
--
-- CREATE FUNCTION gamma_question(asset VARCHAR)
-- RETURNS VARCHAR
-- LANGUAGE JAVA
-- WITH (
--   'source.name' = 'gamma_udf_src',
--   'class.name' = 'polymarket.udf.GammaQuestionLookup',
--   'egress.allow.uris' = 'gamma-api.polymarket.com:443'
-- );

-- ============================================================================
-- Phase 2B: Gamma Token Normalization
-- ============================================================================
-- Keep pm_gamma_markets_cl as the canonical latest-by-conditionId relation, but
-- declare a parallel raw stream over the same protected topic for flattening.
-- This avoids the unsupported changelog-to-stream-with-UNNEST path and lets us
-- build a token-keyed helper topic for a clean upsert changelog.

CREATE STREAM polymarket.public.pm_gamma_markets_s (
  "conditionId" STRING,
  question STRING,
  slug STRING,
  outcomes STRING,
  "clobTokenIds" STRING,
  "sportsMarketType" STRING,
  line DOUBLE,
  active BOOLEAN,
  closed BOOLEAN,
  "updatedAt" STRING,
  events ARRAY<STRUCT<
    title STRING,
    "eventMetadata" STRUCT<
      league STRING
    >
  >>
) WITH (
  'store' = 'warpstream',
  'topic' = 'demo_pm_gamma_markets',
  'value.format' = 'json'
);

ALTER RELATION pm_gamma_markets_s SET description =
'Parallel raw Gamma stream over the protected source topic. Used only for token flattening and replayable expansion via UNNEST.';

CREATE STREAM polymarket.public.pm_gamma_token_question_flat_s
WITH (
  'store' = 'warpstream',
  'topic' = 'demo_pm_gamma_token_question_flat',
  'value.format' = 'json',
  'key.columns' = 'token_id',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
)
AS
SELECT
  token_id,
  g.question AS market_question,
  JSON_QUERY(g.outcomes, '$' RETURNING ARRAY<VARCHAR>)[pos] AS outcome_label,
  g."updatedAt" AS market_updated_at
FROM polymarket.public.pm_gamma_markets_s g WITH (
  'starting.position' = 'earliest',
  'source.allow.latency.millis' = 30000
)
CROSS JOIN UNNEST(
  JSON_QUERY(g."clobTokenIds", '$' RETURNING ARRAY<VARCHAR>)
) WITH ORDINALITY AS t(token_id, pos);

ALTER RELATION pm_gamma_token_question_flat_s SET description =
'Intermediate stream with one row per token_id carrying the Gamma market question and outcome label. Written to a token-keyed helper topic for downstream upsert changelog declaration.';

CREATE CHANGELOG polymarket.public.pm_gamma_token_question_cl
WITH (
  'store' = 'warpstream',
  'topic' = 'demo_pm_gamma_token_question',
  'value.format' = 'json',
  'enable.upsert.mode' = true,
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
)
AS
SELECT
  token_id,
  MAX(market_question) AS market_question,
  MAX(outcome_label) AS outcome_label,
  MAX(market_updated_at) AS market_updated_at
FROM polymarket.public.pm_gamma_token_question_flat_s WITH (
  'starting.position' = 'earliest',
  'source.allow.latency.millis' = 30000
)
GROUP BY token_id;

ALTER RELATION pm_gamma_token_question_cl SET description =
'Canonical token_id -> market_question and outcome_label changelog for DeltaStream-native order enrichment.';

-- ============================================================================
-- Phase 2C: Gamma Validation Gate
-- ============================================================================
-- Do not create any order-enrichment relations until all of the following are
-- true in DeltaStream:
-- 1. pm_gamma_markets_cl exists and has current raw Gamma data.
-- 2. pm_gamma_markets_s exists and can replay the protected raw Gamma topic.
-- 3. pm_gamma_token_question_flat_s emits one row per token_id.
-- 4. pm_gamma_token_question_cl resolves token_id -> market_question.
-- 5. market_question is populated from DeltaStream for the common path.
