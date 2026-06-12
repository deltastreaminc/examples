CREATE STREAM stablecoin_payment_demo.public.confirmed_token_transfers_s
WITH (
  'topic' = 'stablecoin_demo_confirmed_token_transfers',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json'
) AS
SELECT
  event_time_ms AS ctx_time_ms,
  event_time_ms AS transfer_event_time_ms,
  onchain_event_id,
  chain_name,
  block_number,
  block_hash,
  tx_hash,
  log_index,
  block_time_ms,
  confirmation_count,
  contract_address,
  token_symbol,
  token_decimals,
  sender_address,
  receiver_address,
  amount_minor,
  amount_decimal_text,
  ingest_time_ms
FROM stablecoin_payment_demo.public.onchain_token_transfers_s
WHERE is_removed = false
  AND confirmation_count >= 3
  AND (token_symbol = 'USDC' OR token_symbol = 'USDT')
QUERY WITH ('query.name' = stablecoin_demo_confirmed_token_transfers);

CREATE STREAM stablecoin_payment_demo.public.transfer_invoice_matches_s
WITH (
  'topic' = 'stablecoin_demo_transfer_invoice_matches',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json'
) AS
SELECT
  CASE
    WHEN t.transfer_event_time_ms >= i.event_time_ms THEN t.transfer_event_time_ms
    ELSE i.event_time_ms
  END AS ctx_time_ms,
  i.event_time_ms AS invoice_event_time_ms,
  t.transfer_event_time_ms AS transfer_event_time_ms,
  i.invoice_id,
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
  t.onchain_event_id,
  t.chain_name AS actual_chain,
  t.token_symbol AS actual_token,
  t.sender_address AS actual_payer_wallet_address,
  t.receiver_address AS actual_receiver_address,
  t.amount_minor AS actual_amount_minor,
  t.amount_decimal_text AS actual_amount_decimal_text,
  t.tx_hash,
  t.log_index,
  t.block_number,
  t.block_time_ms,
  t.confirmation_count
FROM stablecoin_payment_demo.public.confirmed_token_transfers_s t
JOIN stablecoin_payment_demo.public.payment_invoices_by_address_c i
  ON t.receiver_address = i.payment_address
QUERY WITH ('query.name' = stablecoin_demo_transfer_invoice_matches);

CREATE CHANGELOG stablecoin_payment_demo.public.transfer_reconciliation_by_invoice_c
WITH (
  'topic' = 'stablecoin_demo_transfer_reconciliation_by_invoice',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  invoice_id,
  MAX(ctx_time_ms) AS ctx_time_ms,
  MAX(invoice_event_time_ms) AS latest_invoice_event_time_ms,
  MAX(transfer_event_time_ms) AS latest_transfer_event_time_ms,
  COUNT(onchain_event_id) AS matched_transfer_count,
  SUM(actual_amount_minor) AS total_received_minor,
  MAX(block_time_ms) AS latest_block_time_ms,
  MAX(block_number) AS latest_block_number,
  MAX(CASE WHEN actual_chain <> expected_chain THEN 1 ELSE 0 END) AS has_wrong_chain,
  MAX(CASE WHEN actual_token <> expected_token THEN 1 ELSE 0 END) AS has_wrong_token,
  MAX(CASE WHEN actual_payer_wallet_address <> expected_payer_wallet_address THEN 1 ELSE 0 END) AS has_unexpected_payer_wallet
FROM stablecoin_payment_demo.public.transfer_invoice_matches_s
GROUP BY invoice_id
QUERY WITH ('query.name' = stablecoin_demo_transfer_reconciliation_by_invoice);

CREATE CHANGELOG stablecoin_payment_demo.public.support_case_summary_by_invoice_c
WITH (
  'topic' = 'stablecoin_demo_support_case_summary_by_invoice',
  'topic.partitions' = 6,
  'topic.replicas' = 1,
  'value.format' = 'json',
  'enable.upsert.mode' = true
) AS
SELECT
  invoice_id,
  MAX(event_time_ms) AS ctx_time_ms,
  MAX(updated_time_ms) AS latest_support_update_time_ms,
  COUNT(support_case_id) AS open_support_case_count
FROM stablecoin_payment_demo.public.support_case_events_s
WHERE case_state = 'OPEN'
   OR case_state = 'PENDING'
   OR case_state = 'ESCALATED'
GROUP BY invoice_id
QUERY WITH ('query.name' = stablecoin_demo_support_case_summary_by_invoice);
