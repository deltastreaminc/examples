GRANT USAGE ON DATABASE stablecoin_payment_demo TO ROLE base_demo_role;
GRANT USAGE ON SCHEMA public TO ROLE base_demo_role;
GRANT SELECT ON RELATION stablecoin_payment_demo.public.stablecoin_payment_ops_context_mv TO ROLE base_demo_role;
GRANT SELECT ON RELATION stablecoin_payment_demo.public.support_case_summary_by_invoice_mv TO ROLE base_demo_role;
