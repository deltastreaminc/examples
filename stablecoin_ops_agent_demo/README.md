# Stablecoin Ops Agent Demo

A standalone demo that uses **PydanticAI + Anthropic Sonnet 4.6** with a **DeltaStream MCP server** and a React chat UI with SSE streaming.

This demo is a practical look at how you would run a stablecoin payment ops assistant in the real world. The agent is built with **PydanticAI + Anthropic Sonnet 4.6**, and it does not poke at raw systems when someone asks a question. Instead, the reconciliation work is done ahead of time in DeltaStream, and the agent reads from one clean, continuously updated context view: `stablecoin_payment_ops_context_mv`. Every row has a `ctx_time_ms` value, so answers are anchored to the latest event time reflected in context.

Under the hood, the input data is simulated but realistic: customer profiles, merchant payment policies, wallet risk/compliance profiles, payment invoices, support events, and simulated onchain transfer events (chain, token, sender/receiver, amounts, confirmations, block info). Everything is timestamped in epoch milliseconds, and the generator is restart-safe, so it continues from the next scenario instead of replaying old invoice IDs. The result is an agent that can explain what happened, call out payment exceptions, and recommend next steps with guardrails, without guessing or making unsafe release recommendations.

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
                       |   - Queries stablecoin_payment_ops_context_mv |
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
      - current payment ops state
      - exception flags (wrong chain/token, under/overpaid, etc.)
      - risk/compliance context
      - freshness via ctx_time_ms

                                      |
                                      v
                    Backend in Docker (FastAPI + PydanticAI)
      - queries MV via DeltaStream MCP
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

## Setup

1. Copy env file and insert real keys:

```bash
cp .env.example .env
```

2. Install dependencies:

```bash
make install
```

3. Run backend + frontend in dev mode:

```bash
make dev
```

4. Open:

```text
http://localhost:5173
```

## Useful Make targets

- `make run` - start backend agent API only
- `make dev` - start backend and frontend together
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
- `POST /api/chat/stream` (SSE stream with events: `start`, `context_meta`, `token`, `final`, `done`, `error`)

## Docker (single image)

The Docker image now contains both the built React frontend and the FastAPI backend.

- Start app: `make run-image`
- Open UI: `http://localhost:8000`
- Health check: `http://localhost:8000/api/health`
