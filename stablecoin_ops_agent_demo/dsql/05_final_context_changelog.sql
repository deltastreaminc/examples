CREATE CHANGELOG stablecoin_payment_demo.public.transfer_payment_ops_context_c
WITH (
  'topic' = 'stablecoin_demo_transfer_payment_ops_context',
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
  ticm.merchant_name,
  ticm.merchant_segment,
  ticm.payment_address,
  ticm.expected_payer_wallet_address,
  ticm.expected_chain,
  ticm.expected_token,
  ticm.expected_amount_minor,
  ticm.currency_code,
  ticm.invoice_state,
  ticm.fulfillment_state,
  ticm.created_time_ms,
  ticm.expires_time_ms,
  wr.wallet_address,
  wr.wallet_risk_score,
  wr.risk_band,
  wr.compliance_state,
  wr.risk_reason,
  ticm.matched_transfer_count,
  ticm.total_received_minor,
  ticm.latest_block_time_ms,
  ticm.latest_block_number,
  ticm.has_wrong_chain,
  ticm.has_wrong_token,
  ticm.has_unexpected_payer_wallet,
  CASE
    WHEN wr.compliance_state = 'BLOCKED' THEN 'HOLD_FOR_COMPLIANCE_REVIEW'
    WHEN wr.wallet_risk_score >= 85 THEN 'HOLD_FOR_COMPLIANCE_REVIEW'
    WHEN ticm.has_wrong_chain = 1 THEN 'PAYMENT_EXCEPTION_WRONG_CHAIN'
    WHEN ticm.has_wrong_token = 1 THEN 'PAYMENT_EXCEPTION_WRONG_TOKEN'
    WHEN ticm.has_unexpected_payer_wallet = 1 THEN 'PAYMENT_EXCEPTION_UNEXPECTED_PAYER_WALLET'
    WHEN ticm.total_received_minor < ticm.expected_amount_minor THEN 'PAYMENT_EXCEPTION_UNDERPAID'
    WHEN ticm.total_received_minor > ticm.expected_amount_minor THEN 'PAYMENT_EXCEPTION_OVERPAID'
    WHEN ticm.matched_transfer_count > 1 THEN 'PAYMENT_EXCEPTION_DUPLICATE_OR_SPLIT_PAYMENT'
    WHEN ticm.total_received_minor = ticm.expected_amount_minor THEN 'VALID_PAYMENT_READY_TO_RELEASE'
    ELSE 'PAYMENT_REQUIRES_REVIEW'
  END AS payment_ops_state,
  CASE
    WHEN wr.compliance_state = 'BLOCKED' THEN 'ESCALATE_COMPLIANCE'
    WHEN wr.wallet_risk_score >= 85 THEN 'ESCALATE_WALLET_RISK'
    WHEN ticm.has_wrong_chain = 1 THEN 'ESCALATE_WRONG_CHAIN'
    WHEN ticm.has_wrong_token = 1 THEN 'ESCALATE_WRONG_TOKEN'
    WHEN ticm.has_unexpected_payer_wallet = 1 THEN 'HOLD_VERIFY_PAYER_WALLET'
    WHEN ticm.total_received_minor < ticm.expected_amount_minor THEN 'REQUEST_ADDITIONAL_PAYMENT'
    WHEN ticm.total_received_minor > ticm.expected_amount_minor THEN 'CREATE_EXCESS_REFUND_TASK'
    WHEN ticm.matched_transfer_count > 1 THEN 'REVIEW_DUPLICATE_OR_SPLIT'
    WHEN ticm.total_received_minor = ticm.expected_amount_minor THEN 'RELEASE_IF_POLICY_ALLOWS'
    ELSE 'ESCALATE_PAYMENT_OPS'
  END AS recommended_next_action,
  CASE
    WHEN wr.compliance_state = 'BLOCKED' OR wr.wallet_risk_score >= 85 THEN 'P0'
    WHEN ticm.has_wrong_chain = 1 OR ticm.has_wrong_token = 1 OR ticm.has_unexpected_payer_wallet = 1 THEN 'P1'
    WHEN ticm.total_received_minor <> ticm.expected_amount_minor THEN 'P1'
    WHEN ticm.matched_transfer_count > 1 THEN 'P1'
    ELSE 'P3'
  END AS action_priority
FROM stablecoin_payment_demo.public.transfer_invoice_customer_merchant_context_c ticm
JOIN stablecoin_payment_demo.public.wallet_risk_profiles_c wr
  ON ticm.expected_payer_wallet_address = wr.wallet_address
QUERY WITH ('query.name' = stablecoin_demo_transfer_payment_ops_context);
