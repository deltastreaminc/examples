SELECT COUNT(*) AS row_count
FROM stablecoin_payment_demo.public.stablecoin_payment_ops_context_mv
LIMIT 1;

SELECT ctx_time_ms, invoice_id, payment_ops_state, action_priority
FROM stablecoin_payment_demo.public.stablecoin_payment_ops_context_mv
ORDER BY ctx_time_ms DESC
LIMIT 25;

SELECT payment_ops_state, COUNT(*) AS state_count
FROM stablecoin_payment_demo.public.stablecoin_payment_ops_context_mv
GROUP BY payment_ops_state
ORDER BY state_count DESC
LIMIT 50;

SELECT invoice_id, open_support_case_count, latest_support_update_time_ms
FROM stablecoin_payment_demo.public.support_case_summary_by_invoice_mv
ORDER BY latest_support_update_time_ms DESC
LIMIT 25;
