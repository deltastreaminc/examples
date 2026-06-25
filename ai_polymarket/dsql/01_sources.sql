-- ============================================================
-- Goldsky / Polymarket Orders Filled
-- ============================================================
-- Each row is an executed fill event.
-- This is the most important source for the agent.
-- block_timestamp is epoch seconds in your sample.
-- ============================================================

CREATE STREAM pm_orders_filled_s (
  id VARCHAR,
  block_number BIGINT,
  block_timestamp BIGINT,
  transaction_hash VARCHAR,
  address VARCHAR,
  user_id VARCHAR,
  asset VARCHAR,
  amount_usdc DOUBLE,
  amount_shares DOUBLE,
  price DOUBLE,
  tx_type VARCHAR,
  side VARCHAR,
  order_hash VARCHAR,
  counterparty_id VARCHAR,
  order_type VARCHAR,
  fee DOUBLE,
  builder VARCHAR,
  _gs_op VARCHAR
) WITH (
  'topic' = 'demo_pm_orders_filled',
  'value.format' = 'json'
);


-- ============================================================
-- Goldsky / Polymarket Orders Matched
-- ============================================================
-- Each row is a matched order event.
-- This is a secondary signal used to confirm activity.
-- ============================================================

CREATE STREAM pm_orders_matched_s (
  id VARCHAR,
  block_number BIGINT,
  block_timestamp BIGINT,
  transaction_hash VARCHAR,
  address VARCHAR,
  user_id VARCHAR,
  asset VARCHAR,
  amount_usdc DOUBLE,
  amount_shares DOUBLE,
  price DOUBLE,
  tx_type VARCHAR,
  side VARCHAR,
  order_hash VARCHAR,
  _gs_op VARCHAR
) WITH (
  'topic' = 'demo_pm_orders_matched',
  'value.format' = 'json'
);


-- ============================================================
-- Goldsky / Polymarket User Balances
-- ============================================================
-- Latest token balance per owner/contract/token.
-- This is a CHANGELOG because id is the current-state key.
--
-- balance is modeled as VARCHAR because your sample emits "0"
-- as a JSON string. We cast it later when needed.
-- ============================================================

CREATE CHANGELOG pm_user_balances_c (
  id VARCHAR,
  owner_address VARCHAR,
  contract_address VARCHAR,
  token_id VARCHAR,
  token_type VARCHAR,
  block_number BIGINT,
  block_timestamp BIGINT,
  balance VARCHAR,
  _gs_op VARCHAR,
  PRIMARY KEY (id)
) WITH (
  'topic' = 'demo_pm_user_balances',
  'value.format' = 'json'
);



-- ============================================================
-- Polymarket Gamma Markets
-- ============================================================
-- Market metadata from Gamma.
-- This makes the agent human-friendly:
-- market title, outcomes, category/series, market URL, etc.
--
-- The sample includes clobTokenIds and outcomes as JSON strings:
--   clobTokenIds = "[\"tokenA\", \"tokenB\"]"
--   outcomes     = "[\"Colorado Rockies\", \"Chicago Cubs\"]"
--
-- We expand those into one row per asset later.
-- ============================================================

CREATE STREAM pm_gamma_markets_s (
  id VARCHAR,
  question VARCHAR,
  "conditionId" VARCHAR,
  slug VARCHAR,
  "resolutionSource" VARCHAR,
  "endDate" VARCHAR,
  "startDate" VARCHAR,
  image VARCHAR,
  icon VARCHAR,
  "description" VARCHAR,
  outcomes VARCHAR,
  "outcomePrices" VARCHAR,
  volume VARCHAR,
  active BOOLEAN,
  closed BOOLEAN,
  "createdAt" VARCHAR,
  "updatedAt" VARCHAR,
  "closedTime" VARCHAR,
  "new" BOOLEAN,
  featured BOOLEAN,
  archived BOOLEAN,
  restricted BOOLEAN,
  "groupItemTitle" VARCHAR,
  "groupItemThreshold" VARCHAR,
  "questionID" VARCHAR,
  "umaEndDate" VARCHAR,
  "enableOrderBook" BOOLEAN,
  "orderPriceMinTickSize" DOUBLE,
  "orderMinSize" DOUBLE,
  "umaResolutionStatus" VARCHAR,
  "volumeNum" DOUBLE,
  "endDateIso" VARCHAR,
  "startDateIso" VARCHAR,
  volume24hr DOUBLE,
  volume1wk DOUBLE,
  volume1mo DOUBLE,
  volume1yr DOUBLE,
  "clobTokenIds" VARCHAR,
  "volume24hrClob" DOUBLE,
  "volume1wkClob" DOUBLE,
  "volume1moClob" DOUBLE,
  "volume1yrClob" DOUBLE,
  "volumeClob" DOUBLE,
  "acceptingOrders" BOOLEAN,
  "acceptingOrdersTimestamp" VARCHAR,
  approved BOOLEAN,
  spread DOUBLE,
  "lastTradePrice" DOUBLE,
  "bestAsk" DOUBLE,
  "bestBid" DOUBLE,
  "automaticallyActive" BOOLEAN,
  "negRisk" BOOLEAN,
  "sportsMarketType" VARCHAR,
  line DOUBLE,
  "rfqEnabled" BOOLEAN,
  "holdingRewardsEnabled" BOOLEAN,
  "feesEnabled" BOOLEAN,
  "feeType" VARCHAR
) WITH (
  'topic' = 'demo_polymarket_gamma_markets',
  'value.format' = 'json'
);
