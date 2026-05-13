-- Returns benchmark DeltaStream setup
-- Step 5: RBAC split + API tokens
-- Run with a role that can create roles and grant privileges.

-- Role creation
CREATE ROLE IF NOT EXISTS aws_returns_combined_role;
CREATE ROLE IF NOT EXISTS aws_returns_raw_role;

-- Optional role hierarchy (uncomment if your org requires this pattern)
-- GRANT ROLE aws_returns_combined_role TO ROLE sysadmin;
-- GRANT ROLE aws_returns_raw_role TO ROLE sysadmin;

-- Scope usage
GRANT USAGE ON DATABASE aws_returns_bench TO ROLE aws_returns_combined_role;
GRANT USAGE ON SCHEMA aws_returns_bench.public TO ROLE aws_returns_combined_role;

GRANT USAGE ON DATABASE aws_returns_bench TO ROLE aws_returns_raw_role;
GRANT USAGE ON SCHEMA aws_returns_bench.public TO ROLE aws_returns_raw_role;

-- Combined-surface permissions
GRANT SELECT ON RELATION aws_returns_bench.public.customer_returns_context_mv TO ROLE aws_returns_combined_role;

-- Raw-surface permissions
GRANT SELECT ON RELATION aws_returns_bench.public.orders_raw_mv TO ROLE aws_returns_raw_role;
GRANT SELECT ON RELATION aws_returns_bench.public.shipments_raw_mv TO ROLE aws_returns_raw_role;
GRANT SELECT ON RELATION aws_returns_bench.public.returns_raw_mv TO ROLE aws_returns_raw_role;
GRANT SELECT ON RELATION aws_returns_bench.public.refunds_raw_mv TO ROLE aws_returns_raw_role;

-- Token creation
-- Keep names stable so benchmark configs do not need updates.
-- NOTE: CREATE API_TOKEN is NOT idempotent; re-running will error if the token
-- already exists. To rotate, first run:
--   DROP API_TOKEN aws_returns_combined_token;
--   DROP API_TOKEN aws_returns_raw_token;
CREATE API_TOKEN aws_returns_combined_token WITH ('token.role_name' = aws_returns_combined_role);
CREATE API_TOKEN aws_returns_raw_token WITH ('token.role_name' = aws_returns_raw_role);

-- All GRANT statements above are idempotent in DeltaStream (re-granting is a no-op),
-- so this script is safe to re-run after dropping the API tokens.

-- Recommended manual checks after running this script:
-- DESCRIBE ROLE aws_returns_combined_role;
-- DESCRIBE ROLE aws_returns_raw_role;
-- LIST API_TOKENS;
