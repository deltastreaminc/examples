# DeltaStream Roles and Tokens

Use `deltastream/05_rbac_and_tokens.sql` for the manual RBAC step.

Goal: create two least-privilege API tokens for benchmark A/B.

- `combined` token: can query only `customer_returns_context_mv`
- `raw` token: can query only the 4 raw MVs

## Objects covered by script

- `aws_returns_bench.public.customer_returns_context_mv`
- `aws_returns_bench.public.orders_raw_mv`
- `aws_returns_bench.public.shipments_raw_mv`
- `aws_returns_bench.public.returns_raw_mv`
- `aws_returns_bench.public.refunds_raw_mv`

## How to run

1. Execute `deltastream/05_rbac_and_tokens.sql` in DeltaStream.
2. Capture the two token values returned by `CREATE API_TOKEN`.
3. Export env vars for the benchmark harness:

```bash
export COMBINED_MCP_TOKEN=<combined_token_value>
export RAW_MCP_TOKEN=<raw_token_value>
```

## Verification

Optionally run `deltastream/04_verify_setup.sql`.

Using each token against MCP:
- combined token should discover/query only `customer_returns_context_mv`
- raw token should discover/query only the four `*_raw_mv` relations
- each token should fail on unauthorized relations
