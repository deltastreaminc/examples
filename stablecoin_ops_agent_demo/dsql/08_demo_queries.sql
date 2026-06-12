SELECT *
FROM stablecoin_payment_demo.public.stablecoin_payment_ops_context_mv
WHERE invoice_id = '<invoice_id>'
LIMIT 25;

SELECT *
FROM stablecoin_payment_demo.public.stablecoin_payment_ops_context_mv
WHERE payment_order_id = '<payment_order_id>'
LIMIT 25;

SELECT *
FROM stablecoin_payment_demo.public.stablecoin_payment_ops_context_mv
WHERE action_priority = 'P0'
   OR action_priority = 'P1'
ORDER BY ctx_time_ms DESC
LIMIT 25;

SELECT *
FROM stablecoin_payment_demo.public.stablecoin_payment_ops_context_mv
WHERE payment_ops_state <> 'VALID_PAYMENT_READY_TO_RELEASE'
ORDER BY ctx_time_ms DESC
LIMIT 25;

SELECT *
FROM stablecoin_payment_demo.public.support_case_summary_by_invoice_mv
WHERE invoice_id = '<invoice_id>'
LIMIT 25;
