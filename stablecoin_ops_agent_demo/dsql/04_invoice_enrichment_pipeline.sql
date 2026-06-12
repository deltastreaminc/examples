CREATE STREAM stablecoin_payment_demo.public.invoice_customer_context_s
WITH (
  'topic' = 'stablecoin_demo_invoice_customer_context',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json'
) AS
SELECT
  CASE
    WHEN i.event_time_ms >= c.event_time_ms THEN i.event_time_ms
    ELSE c.event_time_ms
  END AS ctx_time_ms,
  i.event_time_ms AS invoice_event_time_ms,
  c.event_time_ms AS customer_event_time_ms,
  i.invoice_id,
  i.payment_order_id,
  i.customer_id,
  c.customer_name,
  c.customer_region,
  c.customer_tier,
  c.payer_wallet_address,
  c.risk_score AS customer_risk_score,
  i.merchant_id,
  i.payment_address,
  i.expected_payer_wallet_address,
  i.expected_chain,
  i.expected_token,
  i.expected_amount_minor,
  i.currency_code,
  i.invoice_state,
  i.created_time_ms,
  i.expires_time_ms,
  i.fulfillment_state
FROM stablecoin_payment_demo.public.payment_invoices_s i
LEFT JOIN stablecoin_payment_demo.public.customer_profiles_c c
  ON i.customer_id = c.customer_id
QUERY WITH ('query.name' = stablecoin_demo_invoice_customer_context);

CREATE STREAM stablecoin_payment_demo.public.invoice_customer_merchant_context_s
WITH (
  'topic' = 'stablecoin_demo_invoice_customer_merchant_context',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json'
) AS
SELECT
  CASE
    WHEN ic.ctx_time_ms >= m.event_time_ms THEN ic.ctx_time_ms
    ELSE m.event_time_ms
  END AS ctx_time_ms,
  ic.invoice_event_time_ms,
  ic.customer_event_time_ms,
  m.event_time_ms AS merchant_policy_event_time_ms,
  ic.invoice_id,
  ic.payment_order_id,
  ic.customer_id,
  ic.customer_name,
  ic.customer_region,
  ic.customer_tier,
  ic.payer_wallet_address,
  ic.customer_risk_score,
  ic.merchant_id,
  m.merchant_name,
  m.merchant_segment,
  m.settlement_wallet_address,
  m.default_chain,
  m.default_token,
  m.invoice_expiry_minutes,
  m.required_confirmations,
  m.auto_release_limit_minor,
  ic.payment_address,
  ic.expected_payer_wallet_address,
  ic.expected_chain,
  ic.expected_token,
  ic.expected_amount_minor,
  ic.currency_code,
  ic.invoice_state,
  ic.created_time_ms,
  ic.expires_time_ms,
  ic.fulfillment_state
FROM stablecoin_payment_demo.public.invoice_customer_context_s ic
LEFT JOIN stablecoin_payment_demo.public.merchant_payment_policies_c m
  ON ic.merchant_id = m.merchant_id
QUERY WITH ('query.name' = stablecoin_demo_invoice_customer_merchant_context);

CREATE STREAM stablecoin_payment_demo.public.invoice_customer_merchant_risk_context_s
WITH (
  'topic' = 'stablecoin_demo_invoice_customer_merchant_risk_context',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json'
) AS
SELECT
  CASE
    WHEN icm.ctx_time_ms >= wr.event_time_ms THEN icm.ctx_time_ms
    ELSE wr.event_time_ms
  END AS ctx_time_ms,
  icm.invoice_event_time_ms,
  icm.customer_event_time_ms,
  icm.merchant_policy_event_time_ms,
  wr.event_time_ms AS wallet_risk_event_time_ms,
  wr.wallet_address,
  icm.invoice_id,
  icm.payment_order_id,
  icm.customer_id,
  icm.customer_name,
  icm.customer_region,
  icm.customer_tier,
  icm.payer_wallet_address,
  icm.customer_risk_score,
  icm.merchant_id,
  icm.merchant_name,
  icm.merchant_segment,
  icm.settlement_wallet_address,
  icm.required_confirmations,
  icm.auto_release_limit_minor,
  icm.payment_address,
  icm.expected_payer_wallet_address,
  icm.expected_chain,
  icm.expected_token,
  icm.expected_amount_minor,
  icm.currency_code,
  icm.invoice_state,
  icm.created_time_ms,
  icm.expires_time_ms,
  icm.fulfillment_state,
  wr.wallet_risk_score,
  wr.risk_band,
  wr.compliance_state,
  wr.risk_reason
FROM stablecoin_payment_demo.public.invoice_customer_merchant_context_s icm
LEFT JOIN stablecoin_payment_demo.public.wallet_risk_profiles_c wr
  ON icm.expected_payer_wallet_address = wr.wallet_address
QUERY WITH ('query.name' = stablecoin_demo_invoice_customer_merchant_risk_context);

CREATE CHANGELOG stablecoin_payment_demo.public.transfer_invoice_context_c
WITH (
  'topic' = 'stablecoin_demo_transfer_invoice_context',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  r.invoice_id,
  i.invoice_id AS invoice_id_from_invoice_index,
  CASE
    WHEN r.ctx_time_ms >= i.event_time_ms THEN r.ctx_time_ms
    ELSE i.event_time_ms
  END AS ctx_time_ms,
  i.event_time_ms AS invoice_event_time_ms,
  r.latest_transfer_event_time_ms,
  i.payment_order_id,
  i.customer_id,
  i.merchant_id,
  i.payment_address,
  i.expected_payer_wallet_address,
  i.expected_chain,
  i.expected_token,
  i.expected_amount_minor,
  i.currency_code,
  i.invoice_state,
  i.created_time_ms,
  i.expires_time_ms,
  i.fulfillment_state,
  r.matched_transfer_count,
  r.total_received_minor,
  r.latest_block_time_ms,
  r.latest_block_number,
  r.has_wrong_chain,
  r.has_wrong_token,
  r.has_unexpected_payer_wallet
FROM stablecoin_payment_demo.public.transfer_reconciliation_by_invoice_c r
JOIN stablecoin_payment_demo.public.payment_invoices_by_invoice_c i
  ON r.invoice_id = i.invoice_id
QUERY WITH ('query.name' = stablecoin_demo_transfer_invoice_context);

CREATE CHANGELOG stablecoin_payment_demo.public.transfer_invoice_customer_context_c
WITH (
  'topic' = 'stablecoin_demo_transfer_invoice_customer_context',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  tic.invoice_id,
  tic.invoice_id_from_invoice_index,
  tic.customer_id,
  c.customer_id AS customer_id_profile,
  CASE
    WHEN tic.ctx_time_ms >= c.event_time_ms THEN tic.ctx_time_ms
    ELSE c.event_time_ms
  END AS ctx_time_ms,
  tic.invoice_event_time_ms,
  c.event_time_ms AS customer_event_time_ms,
  tic.latest_transfer_event_time_ms,
  tic.payment_order_id,
  c.customer_name,
  c.customer_region,
  c.customer_tier,
  c.payer_wallet_address,
  c.risk_score AS customer_risk_score,
  tic.merchant_id,
  tic.payment_address,
  tic.expected_payer_wallet_address,
  tic.expected_chain,
  tic.expected_token,
  tic.expected_amount_minor,
  tic.currency_code,
  tic.invoice_state,
  tic.created_time_ms,
  tic.expires_time_ms,
  tic.fulfillment_state,
  tic.matched_transfer_count,
  tic.total_received_minor,
  tic.latest_block_time_ms,
  tic.latest_block_number,
  tic.has_wrong_chain,
  tic.has_wrong_token,
  tic.has_unexpected_payer_wallet
FROM stablecoin_payment_demo.public.transfer_invoice_context_c tic
JOIN stablecoin_payment_demo.public.customer_profiles_c c
  ON tic.customer_id = c.customer_id
QUERY WITH ('query.name' = stablecoin_demo_transfer_invoice_customer_context);

CREATE CHANGELOG stablecoin_payment_demo.public.transfer_invoice_customer_merchant_context_c
WITH (
  'topic' = 'stablecoin_demo_transfer_invoice_customer_merchant_context',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  ticc.invoice_id,
  ticc.invoice_id_from_invoice_index,
  ticc.customer_id,
  ticc.customer_id_profile,
  ticc.merchant_id,
  m.merchant_id AS merchant_id_policy,
  CASE
    WHEN ticc.ctx_time_ms >= m.event_time_ms THEN ticc.ctx_time_ms
    ELSE m.event_time_ms
  END AS ctx_time_ms,
  ticc.invoice_event_time_ms,
  ticc.customer_event_time_ms,
  m.event_time_ms AS merchant_policy_event_time_ms,
  ticc.latest_transfer_event_time_ms,
  ticc.payment_order_id,
  ticc.customer_name,
  ticc.customer_region,
  ticc.customer_tier,
  ticc.payer_wallet_address,
  ticc.customer_risk_score,
  m.merchant_name,
  m.merchant_segment,
  m.settlement_wallet_address,
  m.required_confirmations,
  m.auto_release_limit_minor,
  ticc.payment_address,
  ticc.expected_payer_wallet_address,
  ticc.expected_chain,
  ticc.expected_token,
  ticc.expected_amount_minor,
  ticc.currency_code,
  ticc.invoice_state,
  ticc.created_time_ms,
  ticc.expires_time_ms,
  ticc.fulfillment_state,
  ticc.matched_transfer_count,
  ticc.total_received_minor,
  ticc.latest_block_time_ms,
  ticc.latest_block_number,
  ticc.has_wrong_chain,
  ticc.has_wrong_token,
  ticc.has_unexpected_payer_wallet
FROM stablecoin_payment_demo.public.transfer_invoice_customer_context_c ticc
JOIN stablecoin_payment_demo.public.merchant_payment_policies_c m
  ON ticc.merchant_id = m.merchant_id
QUERY WITH ('query.name' = stablecoin_demo_transfer_invoice_customer_merchant_context);

CREATE CHANGELOG stablecoin_payment_demo.public.transfer_full_context_c
WITH (
  'topic' = 'stablecoin_demo_transfer_full_context',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  ticm.invoice_id,
  ticm.invoice_id_from_invoice_index,
  ticm.customer_id,
  ticm.customer_id_profile,
  ticm.merchant_id,
  ticm.merchant_id_policy,
  CASE
    WHEN ticm.ctx_time_ms >= wr.event_time_ms THEN ticm.ctx_time_ms
    ELSE wr.event_time_ms
  END AS ctx_time_ms,
  ticm.invoice_event_time_ms,
  ticm.customer_event_time_ms,
  ticm.merchant_policy_event_time_ms,
  wr.event_time_ms AS wallet_risk_event_time_ms,
  ticm.latest_transfer_event_time_ms,
  ticm.payment_order_id,
  ticm.customer_name,
  ticm.customer_region,
  ticm.customer_tier,
  ticm.payer_wallet_address,
  ticm.customer_risk_score,
  ticm.merchant_name,
  ticm.merchant_segment,
  ticm.settlement_wallet_address,
  ticm.required_confirmations,
  ticm.auto_release_limit_minor,
  ticm.payment_address,
  ticm.expected_payer_wallet_address,
  ticm.expected_chain,
  ticm.expected_token,
  ticm.expected_amount_minor,
  ticm.currency_code,
  ticm.invoice_state,
  ticm.created_time_ms,
  ticm.expires_time_ms,
  ticm.fulfillment_state,
  wr.wallet_risk_score,
  wr.wallet_address,
  wr.risk_band,
  wr.compliance_state,
  wr.risk_reason,
  ticm.matched_transfer_count,
  ticm.total_received_minor,
  ticm.latest_block_time_ms,
  ticm.latest_block_number,
  ticm.has_wrong_chain,
  ticm.has_wrong_token,
  ticm.has_unexpected_payer_wallet
FROM stablecoin_payment_demo.public.transfer_invoice_customer_merchant_context_c ticm
JOIN stablecoin_payment_demo.public.wallet_risk_profiles_c wr
  ON ticm.expected_payer_wallet_address = wr.wallet_address
QUERY WITH ('query.name' = stablecoin_demo_transfer_full_context);
