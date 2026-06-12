CREATE MATERIALIZED VIEW stablecoin_payment_demo.public.stablecoin_payment_ops_context_mv
AS
SELECT
  ctx_time_ms,
  invoice_event_time_ms,
  customer_event_time_ms,
  merchant_policy_event_time_ms,
  wallet_risk_event_time_ms,
  latest_transfer_event_time_ms,
  invoice_id,
  invoice_id_from_invoice_index,
  payment_order_id,
  customer_id,
  customer_id_profile,
  customer_name,
  customer_region,
  customer_tier,
  merchant_id,
  merchant_id_policy,
  merchant_name,
  merchant_segment,
  payment_address,
  expected_payer_wallet_address,
  expected_chain,
  expected_token,
  expected_amount_minor,
  currency_code,
  invoice_state,
  fulfillment_state,
  created_time_ms,
  expires_time_ms,
  wallet_address,
  wallet_risk_score,
  risk_band,
  compliance_state,
  risk_reason,
  matched_transfer_count,
  total_received_minor,
  latest_block_time_ms,
  latest_block_number,
  has_wrong_chain,
  has_wrong_token,
  has_unexpected_payer_wallet,
  payment_ops_state,
  recommended_next_action,
  action_priority
FROM stablecoin_payment_demo.public.transfer_payment_ops_context_c
QUERY WITH ('query.name' = stablecoin_demo_payment_ops_context_mv);

CREATE MATERIALIZED VIEW stablecoin_payment_demo.public.support_case_summary_by_invoice_mv
AS
SELECT
  invoice_id,
  ctx_time_ms,
  latest_support_update_time_ms,
  open_support_case_count
FROM stablecoin_payment_demo.public.support_case_summary_by_invoice_c
QUERY WITH ('query.name' = stablecoin_demo_support_case_summary_mv);
