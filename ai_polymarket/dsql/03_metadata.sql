-- Expand Gamma metadata to asset-level metadata

-- ============================================================
-- Physical asset metadata changelog
-- ============================================================
-- One row per asset/token/outcome.
-- The two INSERT statements below populate this from Gamma markets.
-- ============================================================



-- ============================================================
-- Insert outcome 0 metadata
-- ============================================================

CREATE STREAM pm_market_asset_metadata_s WITH (
  'topic' = 'hojjat_pm_market_asset_metadata',
  'value.format' = 'json',
  'timestamp' = 'updated_at',
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
) AS
SELECT
  REGEXP_EXTRACT(
      "clobTokenIds",
      '([0-9]+).*?([0-9]+)',
      1
  ) AS asset,
  id AS market_id,
  "conditionId" AS condition_id,
  question AS market_title,
  TRIM(
    SPLIT_INDEX(
      REPLACE(
        REPLACE(
          REPLACE(
            REPLACE(outcomes, '\\', ''),
            '[',
            ''
          ),
          ']',
          ''
        ),
        '"',
        ''
      ),
      ',',
      0
    )
  ) AS outcome_label,
  CAST(0 AS INTEGER) AS outcome_index,
  slug,
  "sportsMarketType" AS category,
  'https://polymarket.com/event/' || slug AS market_url,
  CASE
    WHEN closed = true THEN 'CLOSED'
    WHEN active = true AND "acceptingOrders" = true THEN 'ACTIVE_ACCEPTING_ORDERS'
    WHEN active = true THEN 'ACTIVE_NOT_ACCEPTING_ORDERS'
    ELSE 'INACTIVE'
  END AS market_state,
  active,
  closed,
  "acceptingOrders" AS accepting_orders,
  "endDate" AS end_date,
  "startDate" AS start_date,
  (UNIX_TIMESTAMP(REPLACE(SUBSTRING("updatedAt", 1, 19), 'T', ' ')) * 1000) + EXTRACT(MILLISECOND FROM CAST(REPLACE(REPLACE("updatedAt", 'T', ' '), 'Z', '') AS TIMESTAMP(3))) AS updated_at,
  "lastTradePrice" AS last_trade_price,
  "bestAsk" AS best_ask,
  "bestBid" AS best_bid,
  "volumeNum" AS gamma_volume,
  volume24hr AS gamma_volume_24h,
  spread AS gamma_spread
FROM pm_gamma_markets_s WITH ( 'starting.position' = 'earliest' )
WHERE "clobTokenIds" IS NOT NULL
  AND outcomes IS NOT NULL;


-- ============================================================
-- Insert outcome 1 metadata
-- ============================================================

INSERT INTO pm_market_asset_metadata_s 
WITH (
  'kafka.producer.request.timeout.ms' = '60000',
  'kafka.producer.delivery.timeout.ms' = '120000',
  'kafka.producer.linger.ms' = '100',
  'kafka.producer.batch.size' = '1048576'
)
SELECT
  REGEXP_EXTRACT(
      "clobTokenIds",
      '([0-9]+).*?([0-9]+)',
      2
  ) AS asset,
  id AS market_id,
  "conditionId" AS condition_id,
  question AS market_title,
  TRIM(
    SPLIT_INDEX(
      REPLACE(
        REPLACE(
          REPLACE(
            REPLACE(outcomes, '\\', ''),
            '[',
            ''
          ),
          ']',
          ''
        ),
        '"',
        ''
      ),
      ',',
      1
    )
  ) AS outcome_label,
  CAST(1 AS INTEGER) AS outcome_index,
  slug,
  "sportsMarketType" AS category,
  'https://polymarket.com/event/' || slug AS market_url,
  CASE
    WHEN closed = true THEN 'CLOSED'
    WHEN active = true AND "acceptingOrders" = true THEN 'ACTIVE_ACCEPTING_ORDERS'
    WHEN active = true THEN 'ACTIVE_NOT_ACCEPTING_ORDERS'
    ELSE 'INACTIVE'
  END AS market_state,
  active,
  closed,
  "acceptingOrders" AS accepting_orders,
  "endDate" AS end_date,
  "startDate" AS start_date,
  (UNIX_TIMESTAMP(REPLACE(SUBSTRING("updatedAt", 1, 19), 'T', ' ')) * 1000) + EXTRACT(MILLISECOND FROM CAST(REPLACE(REPLACE("updatedAt", 'T', ' '), 'Z', '') AS TIMESTAMP(3))) AS updated_at,
  "lastTradePrice" AS last_trade_price,
  "bestAsk" AS best_ask,
  "bestBid" AS best_bid,
  "volumeNum" AS gamma_volume,
  volume24hr AS gamma_volume_24h,
  spread AS gamma_spread
FROM pm_gamma_markets_s WITH ( 'starting.position' = 'earliest' )
WHERE "clobTokenIds" IS NOT NULL
  AND outcomes IS NOT NULL;



CREATE CHANGELOG pm_market_asset_metadata_c (
    asset VARCHAR,
    market_id VARCHAR,
    condition_id VARCHAR,
    market_title VARCHAR,
    outcome_label VARCHAR,
    outcome_index INTEGER,
    slug VARCHAR,
    category VARCHAR,
    market_url VARCHAR,
    market_state VARCHAR,
    active BOOLEAN,
    closed BOOLEAN,
    accepting_orders BOOLEAN,
    end_date VARCHAR,
    start_date VARCHAR,
    updated_at BIGINT,
    last_trade_price DOUBLE,
    best_ask DOUBLE,
    best_bid DOUBLE,
    gamma_volume DOUBLE,
    gamma_volume_24h DOUBLE,
    gamma_spread DOUBLE,
    -- Define the Primary Key for versioning the state by asset
    PRIMARY KEY (asset)
) WITH (
    'topic' = 'hojjat_pm_market_asset_metadata',
    'value.format' = 'json'
);
