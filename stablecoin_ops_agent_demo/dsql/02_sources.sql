CREATE STREAM stablecoin_payment_demo.public.onchain_token_transfers_s (
  event_time_ms BIGINT,
  onchain_event_id VARCHAR,
  chain_name VARCHAR,
  block_number BIGINT,
  block_hash VARCHAR,
  tx_hash VARCHAR,
  log_index INTEGER,
  block_time_ms BIGINT,
  confirmation_count INTEGER,
  contract_address VARCHAR,
  token_symbol VARCHAR,
  token_decimals INTEGER,
  sender_address VARCHAR,
  receiver_address VARCHAR,
  amount_minor BIGINT,
  amount_decimal_text VARCHAR,
  is_removed BOOLEAN,
  ingest_time_ms BIGINT,
  source_op VARCHAR
) WITH (
  'topic' = 'stablecoin_demo_onchain_token_transfers',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'timestamp' = 'event_time_ms'
);

CREATE STREAM stablecoin_payment_demo.public.payment_invoices_s (
  event_time_ms BIGINT,
  invoice_id VARCHAR NOT NULL,
  payment_order_id VARCHAR,
  customer_id VARCHAR NOT NULL,
  merchant_id VARCHAR NOT NULL,
  payment_address VARCHAR NOT NULL,
  expected_payer_wallet_address VARCHAR,
  expected_chain VARCHAR,
  expected_token VARCHAR,
  expected_amount_minor BIGINT,
  currency_code VARCHAR,
  invoice_state VARCHAR,
  created_time_ms BIGINT,
  expires_time_ms BIGINT,
  fulfillment_state VARCHAR
) WITH (
  'topic' = 'stablecoin_demo_payment_invoices',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'timestamp' = 'event_time_ms'
);

CREATE CHANGELOG stablecoin_payment_demo.public.payment_invoices_by_invoice_c (
  event_time_ms BIGINT,
  invoice_id VARCHAR,
  payment_order_id VARCHAR,
  customer_id VARCHAR,
  merchant_id VARCHAR,
  payment_address VARCHAR,
  expected_payer_wallet_address VARCHAR,
  expected_chain VARCHAR,
  expected_token VARCHAR,
  expected_amount_minor BIGINT,
  currency_code VARCHAR,
  invoice_state VARCHAR,
  created_time_ms BIGINT,
  expires_time_ms BIGINT,
  fulfillment_state VARCHAR,
  PRIMARY KEY (invoice_id)
) WITH (
  'topic' = 'stablecoin_demo_payment_invoices',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'timestamp' = 'event_time_ms',
  'enable.upsert.mode' = true
);

CREATE CHANGELOG stablecoin_payment_demo.public.payment_invoices_by_address_c (
  event_time_ms BIGINT,
  invoice_id VARCHAR,
  payment_order_id VARCHAR,
  customer_id VARCHAR,
  merchant_id VARCHAR,
  payment_address VARCHAR,
  expected_payer_wallet_address VARCHAR,
  expected_chain VARCHAR,
  expected_token VARCHAR,
  expected_amount_minor BIGINT,
  currency_code VARCHAR,
  invoice_state VARCHAR,
  created_time_ms BIGINT,
  expires_time_ms BIGINT,
  fulfillment_state VARCHAR,
  PRIMARY KEY (payment_address)
) WITH (
  'topic' = 'stablecoin_demo_payment_invoices',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'timestamp' = 'event_time_ms',
  'enable.upsert.mode' = true
);

CREATE CHANGELOG stablecoin_payment_demo.public.customer_profiles_c (
  event_time_ms BIGINT,
  customer_id VARCHAR,
  customer_name VARCHAR,
  customer_region VARCHAR,
  customer_tier VARCHAR,
  payer_wallet_address VARCHAR,
  risk_score INTEGER,
  PRIMARY KEY (customer_id)
) WITH (
  'topic' = 'stablecoin_demo_customer_profiles',
  'topic.partitions' = 3,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'timestamp' = 'event_time_ms',
  'enable.upsert.mode' = true
);

CREATE CHANGELOG stablecoin_payment_demo.public.merchant_payment_policies_c (
  event_time_ms BIGINT,
  merchant_id VARCHAR,
  merchant_name VARCHAR,
  merchant_segment VARCHAR,
  settlement_wallet_address VARCHAR,
  default_chain VARCHAR,
  default_token VARCHAR,
  invoice_expiry_minutes INTEGER,
  required_confirmations INTEGER,
  auto_release_limit_minor BIGINT,
  PRIMARY KEY (merchant_id)
) WITH (
  'topic' = 'stablecoin_demo_merchant_payment_policies',
  'topic.partitions' = 3,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'timestamp' = 'event_time_ms',
  'enable.upsert.mode' = true
);

CREATE CHANGELOG stablecoin_payment_demo.public.wallet_risk_profiles_c (
  event_time_ms BIGINT,
  wallet_address VARCHAR,
  customer_id VARCHAR,
  wallet_risk_score INTEGER,
  risk_band VARCHAR,
  compliance_state VARCHAR,
  risk_reason VARCHAR,
  PRIMARY KEY (wallet_address)
) WITH (
  'topic' = 'stablecoin_demo_wallet_risk_profiles',
  'topic.partitions' = 3,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'timestamp' = 'event_time_ms',
  'enable.upsert.mode' = true
);

CREATE STREAM stablecoin_payment_demo.public.support_case_events_s (
  event_time_ms BIGINT,
  support_case_id VARCHAR,
  invoice_id VARCHAR,
  payment_order_id VARCHAR,
  customer_id VARCHAR,
  merchant_id VARCHAR,
  case_state VARCHAR,
  case_category VARCHAR,
  case_reason VARCHAR,
  updated_time_ms BIGINT
) WITH (
  'topic' = 'stablecoin_demo_support_case_events',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'timestamp' = 'event_time_ms'
);
