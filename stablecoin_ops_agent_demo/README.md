# Stablecoin Ops Agent Demo

A standalone demo that uses **PydanticAI + Anthropic Sonnet 4.6** with a **DeltaStream MCP server** and a React chat UI with SSE streaming.

This demo is a practical look at how you would run a stablecoin payment ops assistant in the real world. The agent is built with **PydanticAI + Anthropic Sonnet 4.6**, and it does not poke at raw systems when someone asks a question. Instead, the reconciliation work is done ahead of time in DeltaStream, and the agent reads from continuously updated context views: `stablecoin_payment_ops_context_mv` and `support_case_summary_by_invoice_mv`. Every row has a `ctx_time_ms` value, so answers are anchored to the latest event time reflected in context.

Under the hood, the input data is simulated but realistic: customer profiles, merchant payment policies, wallet risk/compliance profiles, payment invoices, support events, and simulated onchain transfer events (chain, token, sender/receiver, amounts, confirmations, block info). Everything is timestamped in epoch milliseconds, and the generator is restart-safe, so it continues from the next scenario instead of replaying old invoice IDs. The result is an agent that can explain what happened, call out payment exceptions, and recommend next steps with guardrails, without guessing or making unsafe release recommendations.

## Demo quickstart

Run the demo locally with Docker:

```bash
docker run --rm -p 8000:8000 public.ecr.aws/i3m5v2n6/deltastreaminc/stablecoin-ops-agent-demo:latest
```

Then:

1. Open `http://localhost:8000`.
2. Enter your email in the **Signup email** box and submit.
3. Follow the instructions in the signup email you receive.
4. Paste the issued access key/token into the **Access token** box.
5. Click **Validate token**, then start chatting.

Notes:

- If you lose your access token, submit the same email in the **Signup email** box again to request a new one.
- Per-minute request limits are enforced by the upstream demo services; this app code does not currently define its own in-process per-minute cap.

## High-level architecture

```text
                       +-----------------------------------------------+
                       |                Docker Container               |
                       |  stablecoin-ops-agent-demo:latest            |
                       |-----------------------------------------------|
Browser (User)  <----> |  FastAPI (Uvicorn, port 8000)                |
http://localhost:8000  |   - Serves React frontend static files (/)    |
                       |   - Exposes API endpoints (/api/*)            |
                       |   - SSE streaming chat endpoint               |
                       |          |                                     |
                       |          v                                     |
                       |  PydanticAI Agent                             |
                       |   - Anthropic Sonnet 4.6 model client         |
                       |   - System prompt + response policy           |
                       |   - Guardrail enforcement (release safety)    |
                       |          |                                     |
                       |          v                                     |
                       |  DeltaStream Context Service                  |
                       |   - MCP client (streamable HTTP)              |
                       |   - Queries both demo context MVs             |
                       +-----------------------------------------------+
                                   |                     |
                                   | HTTPS               | HTTPS
                                   v                     v
                    +---------------------------+   +----------------------+
                    | DeltaStream MCP Endpoint  |   | Anthropic API        |
                    | (query_mview/execute_dsql)|   | (LLM inference)      |
                    +---------------------------+   +----------------------+
```

## Source topics and pipeline

```text
                               Source Event Topics (Kafka)
+---------------------------+    +-------------------------------+
| customer_profiles         |    | merchant_payment_policies     |
| (customer state updates)  |    | (merchant payment rules)      |
+---------------------------+    +-------------------------------+
+---------------------------+    +-------------------------------+
| wallet_risk_profiles      |    | payment_invoices              |
| (risk/compliance state)   |    | (invoice/payment intent)      |
+---------------------------+    +-------------------------------+
+---------------------------+    +-------------------------------+
| support_case_events       |    | onchain_token_transfers       |
| (ops/support signals)     |    | (simulated onchain transfers) |
+---------------------------+    +-------------------------------+

                                      |
                                      v
                         DeltaStream Ingestion + Modeling
         (streams/changelogs, transfer matching, reconciliation, enrichment)

                                      |
                                      v
               stablecoin_payment_ops_context_mv (materialized view)
      - current payment ops state, exception flags, risk/compliance context
      - freshness via ctx_time_ms

               support_case_summary_by_invoice_mv (materialized view)
      - latest support case rollup by invoice
      - open_support_case_count and latest_support_update_time_ms

                                      |
                                      v
                    Backend in Docker (FastAPI + PydanticAI)
      - queries both MVs via DeltaStream MCP
      - sends structured context to Anthropic Sonnet 4.6
      - applies deterministic release guardrails
      - streams answer via SSE

                                      |
                                      v
                       Frontend in same Docker image
                           (served at http://localhost:8000)
```

## What this demo proves

- The agent does not query raw blockchain data, raw invoices, raw customer profiles, raw wallet risk, or raw support tickets at runtime.
- Simulated transfer data tells us what happened onchain.
- DeltaStream turns that into fresh operational context.
- PydanticAI + Anthropic Sonnet 4.6 turn that context into an operational AI agent response.

Core message:

- Simulated onchain event feeds make blockchain data live.
- DeltaStream makes it agent-ready.
- PydanticAI + Anthropic Sonnet 4.6 turn it into an operational AI agent.

## What the agent can answer from computed context

Because the agent reads precomputed DeltaStream context (not raw source feeds), it is strongest at operational triage and reconciliation answers such as:

- Invoice-level status and disposition (current `payment_ops_state`, action priority, recommended next action).
- Release-readiness guidance with guardrails (for example valid payment ready to release vs hold for compliance review).
- Exception diagnostics (wrong chain, wrong token, unexpected payer wallet, underpaid, overpaid, duplicate/split transfers).
- Queue and recency views (freshest P0/P1 exceptions, most recently changed exceptions by `ctx_time_ms`).
- Support context by invoice (`open_support_case_count`, latest support update timestamp).
- Focused operational filters (for example, "show wrong-chain payments" or "show underpaid/overpaid invoices").

Scope note: this demo is optimized for answers represented in the materialized views. It is not intended for deep raw-event forensics outside the modeled context fields.

## Setup

1. Copy env file and insert real keys:

```bash
cp .env.example .env
```

Use quoted three-part MV names in `.env` so MCP `query_mview` targets resolve correctly:

```bash
OPS_MV_FQN="stablecoin_payment_demo"."public"."stablecoin_payment_ops_context_mv"
SUPPORT_MV_FQN="stablecoin_payment_demo"."public"."support_case_summary_by_invoice_mv"
```

2. Install dependencies:

```bash
make install
```

3. Run backend + frontend in dev mode:

```bash
make dev
```

4. Start the idempotent datagen (in another shell):

```bash
make datagen-run
```

5. Open:

```text
http://localhost:5173
```

## Useful Make targets

- `make run` - start backend agent API only
- `make dev` - start backend and frontend together
- `make datagen-run` - run streaming datagen loop
- `make datagen-run-once` - emit one scenario event
- `make datagen-reset-state` - reset persisted datagen sequence
- `make dsql-list` - print ordered DSQL files to execute
- `make build-image` - build single Docker image (frontend + backend)
- `make run-image` - run single Docker container with `.env`
- `make stop-image` - stop backend Docker container
- `make health` - check backend health endpoint

## Demo prompts

- Show me the freshest high-priority stablecoin payment exceptions.
- What happened with invoice inv_7350? Can we release the order?
- Customer says they paid invoice inv_7349. What does the latest context say?
- Why is invoice inv_7352 blocked even though payment arrived?
- Find recent invoices where the payment arrived on the wrong chain.
- Find recent invoices where the customer underpaid or overpaid.
- Which payment exceptions changed most recently?
- Does invoice inv_6323 look underpaid or overpaid right now?

## API

- `GET /api/health`
- `POST /api/signup`
- `POST /api/token/validate`
- `POST /api/chat/stream` (SSE stream with events: `start`, `context_meta`, `token`, `final`, `done`, `error`)

## DSQL execution order

Execute core setup files in this order:

- `dsql/01_database.sql`
- `dsql/02_sources.sql`
- `dsql/03_transfer_pipeline.sql`
- `dsql/04_invoice_enrichment_pipeline.sql`
- `dsql/05_final_context_changelog.sql`
- `dsql/06_materialized_views.sql`
- `dsql/09_grants.sql`
- `dsql/10_query_tags.sql`

Optional read-only query files (run after core setup):

- `dsql/07_validation_queries.sql`
- `dsql/08_demo_queries.sql`

Teardown:

- `dsql/99_teardown.sql` terminates 14 named demo queries, then drops 2 materialized views and 20 upstream stream/changelog relations.
- `make dsql-teardown` runs `scripts/teardown_demo.sh`.
- Teardown uses query names (no version suffix).
- Teardown does not revoke grants from `dsql/09_grants.sql`.
- Per-user role provisioning/inheritance is managed by backend services; this repo only grants to `base_demo_role`.
- DSQL relations are fully qualified under `stablecoin_payment_demo.public`.
- All Kafka topic names use the `stablecoin_demo_` prefix.

Teardown script environment variables:

- `DS_API_TOKEN` (or `DS_TOKEN`) - required API token passed to every client request.
- `DS_SERVER` - optional API endpoint override (default `https://api.local.deltastream.io/v2`).
- `DS_ORG` - optional organization ID/name.
- `DROP_DATABASE` - optional `true|false` flag to drop the demo DB after relation teardown (default `false`).
- `DATABASE_NAME` - optional database name for drop step (default `stablecoin_payment_demo`).

Example (kap822):

```bash
DS_SERVER="https://api-kap822.deltastream.io/v2" \
DS_ORG="<org_id>" \
DS_API_TOKEN="<api_token>" \
DROP_DATABASE=true \
DATABASE_NAME="stablecoin_payment_demo" \
./scripts/teardown_demo.sh
```

## Docker (single image)

The Docker image now contains both the built React frontend and the FastAPI backend.

- Start app: `make run-image`
- Open UI: `http://localhost:8000`
- Health check: `http://localhost:8000/api/health`
