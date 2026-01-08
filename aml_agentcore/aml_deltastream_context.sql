CREATE STREAM transactions_stream (
  transaction_id      STRING,
  account_id          STRING,
  customer_id         STRING,
  amount              DECIMAL(18,2),
  currency            STRING,
  direction           STRING,   -- 'DEBIT'/'CREDIT'
  counterparty_iban   STRING,
  counterparty_name   STRING,
  merchant_category   STRING,
  country_code        STRING,
  channel             STRING,   -- 'WEB','MOBILE','POS','ATM'
  tx_timestamp           BIGINT
)
WITH (
  'topic' = 'transactions',
  'value.format' = 'json',
  'timestamp'    = 'tx_timestamp'
);

CREATE CHANGELOG customers_cl (
  customer_id         STRING,
  full_name           STRING,
  date_of_birth       DATE,
  residency_country   STRING,
  risk_segment        STRING,   -- 'LOW','MEDIUM','HIGH'
  pep_flag            BOOLEAN,
  kyc_status          STRING,   -- 'PENDING','PASSED','FAILED'
  created_at          BIGINT,
  updated_at          BIGINT,
  PRIMARY KEY(customer_id)
)
WITH (
  'topic' = 'customers',
  'value.format' = 'json',
  'timestamp'    = 'updated_at'
);

CREATE CHANGELOG kyc_results_cl (
  event_id            STRING,
  customer_id         STRING,
  provider            STRING,
  check_type          STRING,    -- 'ONBOARDING','PERIODIC','TRIGGERED'
  status              STRING,    -- 'PENDING','PASSED','FAILED','REVIEW'
  risk_level          STRING,    -- 'LOW','MEDIUM','HIGH'
  reasons             STRING,    -- JSON blob
  completed_at        BIGINT,
  PRIMARY KEY(customer_id)
)
WITH (
  'topic' = 'kyc_results',
  'value.format' = 'json',
  'timestamp'    = 'completed_at'
);

CREATE CHANGELOG sanctions_matches_cl (
  match_id        STRING,
  customer_id     STRING,
  list_type       STRING,       -- 'OFAC','UN','LOCAL'
  entity_id       STRING,
  matched_name    STRING,
  match_score     DOUBLE,
  status          STRING,       -- 'POTENTIAL','CONFIRMED','DISMISSED'
  reviewed_by     STRING,
  reviewed_at     BIGINT,
  PRIMARY KEY(customer_id)
)
WITH (
  'topic' = 'sanctions_matches',
  'value.format' = 'json',
  'timestamp'    = 'reviewed_at'
);

--************************************************************

CREATE CHANGELOG recent_txn_stats_cl AS
SELECT
  window_start,
  window_end,
  UNIX_TIMESTAMP(CAST(window_end AS VARCHAR))*1000  AS day_bucket_end,
  customer_id,
  COUNT(*)                                 AS txn_count_1h,
  SUM(amount)                              AS total_amount_1h,
  COUNT(DISTINCT country_code)             AS distinct_countries_1h,
  SUM(CASE WHEN amount > 10000 THEN 1 ELSE 0 END) AS high_value_count_1h
FROM TUMBLE (transactions_stream, SIZE 1 HOUR) 
GROUP BY
  window_start, window_end, customer_id;


CREATE CHANGELOG recent_txn_stats_cl_rekeyed (
  day_bucket_end      BIGINT,
  customer_id         VARCHAR,
  txn_count_1h        BIGINT,
  total_amount_1h     DECIMAL(18,2),
  distinct_countries_1h   BIGINT,
  high_value_count_1h   BIGINT,
  PRIMARY KEY(customer_id) 
)
WITH (
  'topic' = 'recent_txn_stats_cl',
  'value.format' = 'json',
  'timestamp'    = 'day_bucket_end'
);


CREATE STREAM transactions_customers_stream AS
SELECT
  transaction_id,
  account_id,
  t.customer_id,
  amount,
  currency,
  direction, -- 'DEBIT'/'CREDIT'
  counterparty_iban,
  counterparty_name,
  merchant_category,
  country_code,
  channel, -- 'WEB','MOBILE','POS','ATM'
  tx_timestamp,
  full_name,
  date_of_birth,
  residency_country,
  risk_segment, -- 'LOW','MEDIUM','HIGH'
  pep_flag,
  kyc_status, -- 'PENDING','PASSED','FAILED'
  created_at,
  updated_at
FROM
  transactions_stream t
  LEFT JOIN customers_cl c
WITH
  ('source.idle.timeout.millis' = 1000) ON t.customer_id = c.customer_id;



CREATE STREAM transactions_customers_recent_txn_stream AS
SELECT 
  transaction_id,
  account_id,
  enriched_tx.customer_id,
  amount,
  currency,
  direction,   -- 'DEBIT'/'CREDIT'
  counterparty_iban,
  counterparty_name,
  merchant_category,
  country_code,
  channel,   -- 'WEB','MOBILE','POS','ATM'
  tx_timestamp,
  full_name,
  date_of_birth,
  residency_country,
  risk_segment,   -- 'LOW','MEDIUM','HIGH'
  pep_flag,
  kyc_status,   -- 'PENDING','PASSED','FAILED'
  created_at,
  updated_at,
  day_bucket_end,
  txn_count_1h,
  total_amount_1h,
  distinct_countries_1h,
  high_value_count_1h
  FROM transactions_customers_stream enriched_tx WITH ('timestamp'    = 'tx_timestamp')
    LEFT JOIN recent_txn_stats_cl_rekeyed r WITH ('source.idle.timeout.millis' = 1000)
        ON enriched_tx.customer_id = r.customer_id; 


CREATE STREAM transactions_customers_recent_txn_kyc_stream AS
SELECT 
  transaction_id,
  account_id,
  enriched_tx.customer_id,
  amount,
  currency,
  direction,   -- 'DEBIT'/'CREDIT'
  counterparty_iban,
  counterparty_name,
  merchant_category,
  country_code,
  channel,   -- 'WEB','MOBILE','POS','ATM'
  tx_timestamp,
  full_name,
  date_of_birth,
  residency_country,
  risk_segment,   -- 'LOW','MEDIUM','HIGH'
  pep_flag,
  kyc_status,   -- 'PENDING','PASSED','FAILED'
  created_at,
  updated_at,
  day_bucket_end,
  txn_count_1h,
  total_amount_1h,
  distinct_countries_1h,
  high_value_count_1h,
  event_id AS kyc_event_id,
  provider AS kyc_provider,
  check_type AS kyc_check_type,
  status AS status_from_kyc_provider,
  risk_level AS kyc_risk_level,
  reasons AS reasons_kyc,
  completed_at AS kyc_event_completed_at
  FROM transactions_customers_recent_txn_stream enriched_tx WITH ('timestamp'    = 'tx_timestamp')
    LEFT JOIN kyc_results_cl kyc WITH ('source.idle.timeout.millis' = 1000)
    ON enriched_tx.customer_id = kyc.customer_id; 



CREATE STREAM transactions_customers_recent_txn_kyc_sanctions_stream AS
SELECT 
  transaction_id,
  account_id,
  enriched_tx.customer_id,
  amount,
  currency,
  direction,   -- 'DEBIT'/'CREDIT'
  counterparty_iban,
  counterparty_name,
  merchant_category,
  country_code,
  channel,   -- 'WEB','MOBILE','POS','ATM'
  tx_timestamp,
  full_name,
  date_of_birth,
  residency_country,
  risk_segment,   -- 'LOW','MEDIUM','HIGH'
  pep_flag,
  kyc_status,   -- 'PENDING','PASSED','FAILED'
  created_at,
  updated_at,
  day_bucket_end,
  txn_count_1h,
  total_amount_1h,
  distinct_countries_1h,
  high_value_count_1h,
  kyc_event_id,
  kyc_provider,
  kyc_check_type,
  status_from_kyc_provider,
  kyc_risk_level,
  reasons_kyc,
  kyc_event_completed_at,
  match_id AS sanction_match_id,
  list_type AS sanction_list_type,
  entity_id AS sanction_entity_id,
  matched_name AS sanction_matched_name,
  match_score AS sanction_match_score,
  status AS sanction_status,
  reviewed_by AS sanction_reviewed_by,
  reviewed_at AS sanction_reviewed_at
  FROM transactions_customers_recent_txn_kyc_stream enriched_tx WITH ('timestamp'    = 'tx_timestamp')
    LEFT JOIN sanctions_matches_cl snc WITH ('source.idle.timeout.millis' = 1000)
    ON enriched_tx.customer_id = snc.customer_id;


CREATE MATERIALIZED VIEW aml_alerts_mv AS
SELECT
  UUID() AS alert_id,
  transaction_id,
  customer_id,
  'HIGH_RISK_TXN' AS alert_type,

  CONCAT(
    'High value / high risk transaction from ',
    country_code,
    ' for customer ', customer_id
  ) AS alert_reason,

  (
    CASE WHEN amount > 10000 THEN 0.3 ELSE 0.0 END +
    CASE WHEN pep_flag THEN 0.2 ELSE 0.0 END +
    CASE WHEN kyc_risk_level = 'HIGH' THEN 0.2 ELSE 0.0 END +
    CASE WHEN kyc_status = 'CONFIRMED' THEN 0.3
         WHEN kyc_status = 'POTENTIAL' THEN 0.15 ELSE 0.0 END +
    CASE WHEN txn_count_1h > 2 THEN 0.1 ELSE 0.0 END
  ) AS base_score,

  tx_timestamp AS alert_created_at,
  amount AS transaction_amount,
  currency AS transaction_currency,
  direction AS transaction_direction,   -- 'DEBIT'/'CREDIT'
  counterparty_iban AS transaction_counterparty_iban,
  counterparty_name AS transaction_counterparty_name,
  merchant_category AS transaction_merchant_category,
  country_code AS transaction_country_code,
  channel AS transaction_channel,   -- 'WEB','MOBILE','POS','ATM'
  residency_country AS customer_residency_country,
  risk_segment AS customer_risk_segment,   -- 'LOW','MEDIUM','HIGH'
  pep_flag AS customer_pep_flag,
  kyc_status,   -- 'PENDING','PASSED','FAILED'
  created_at,
  updated_at,
  day_bucket_end,
  txn_count_1h,
  total_amount_1h,
  distinct_countries_1h,
  high_value_count_1h,
  kyc_event_id,
  kyc_provider,
  kyc_check_type,
  status_from_kyc_provider,
  kyc_risk_level,
  reasons_kyc,
  kyc_event_completed_at,
  sanction_match_id,
  sanction_list_type,
  sanction_entity_id,
  sanction_matched_name,
  sanction_match_score,
  sanction_status,
  sanction_reviewed_by,
  sanction_reviewed_at
FROM transactions_customers_recent_txn_kyc_sanctions_stream
WHERE
  (
      amount > 10000
   OR  pep_flag = TRUE
   OR  kyc_risk_level = 'HIGH'
   OR  kyc_status IN ('POTENTIAL','CONFIRMED')
   OR  txn_count_1h > 2
  );
