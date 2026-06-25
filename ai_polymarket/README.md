# Polymarket Live Signal Radar

A standalone demo that uses **PydanticAI + Anthropic Sonnet 4.6** with a **DeltaStream MCP server** and a React chat UI with SSE streaming.

This demo explains live Polymarket market activity from continuously precomputed DeltaStream context built on top of Goldsky Polymarket streams and Gamma metadata. The runtime agent does not scan raw fills, matches, balances, or market metadata at inference time. Instead, DeltaStream continuously prepares agent-ready materialized views, and the app routes each question to the relevant context views before sending structured context to the model.

Primary context:

- `pm_live_signal_radar_mv`

Drill-down context:

- `pm_wallet_asset_flow_mv`
- `pm_wallet_activity_mv`
- `pm_recent_fills_mv`
- `pm_market_asset_metadata_mv`
- `pm_user_balances_mv`

Every answer is anchored to `ctx_time_ms`, the latest reflected source-event timestamp in the fetched context.

## Demo quickstart

Run locally in dev mode:

```bash
cp .env.example .env
make install
make dev
```

Then:

1. Open `http://localhost:5173`.
2. Enter your email in the signup box.
3. Follow the instructions in the signup email.
4. Paste the issued access token into the token box.
5. Validate the token, then start chatting.

## What this demo proves

- Goldsky Polymarket data can be turned into live agent context through DeltaStream.
- DeltaStream can precompute broad market signals, wallet-driver context, and raw evidence context continuously.
- PydanticAI + Anthropic can answer from those materialized views without scanning raw event streams at chat time.

## Runtime architecture

- FastAPI backend serves the React frontend and exposes chat endpoints.
- Backend validates the token against Anthropic and DeltaStream MCP.
- Backend fetches only the relevant DeltaStream materialized views for the question.
- PydanticAI sends that structured context to Anthropic Sonnet 4.6.
- Responses stream back to the browser over SSE.

## Question routing

- Broad briefing, movers, buy pressure, sell pressure, large-fill-driven:
  - `pm_live_signal_radar_mv`
- Who is driving activity in a market or outcome:
  - `pm_wallet_asset_flow_mv`
  - optionally `pm_wallet_activity_mv`
- Raw fill examples or transaction-level evidence:
  - `pm_recent_fills_mv`
  - plus `pm_market_asset_metadata_mv` for human-readable labels
- Metadata lookups:
  - `pm_market_asset_metadata_mv`
- Balance questions:
  - `pm_user_balances_mv`

For broad briefings, the backend fetches a fresh slice, keeps the latest row per `asset`, and then ranks the latest asset rows by `signal_score DESC` unless the user explicitly asks for the freshest signals.

## Setup

1. Copy env file:

```bash
cp .env.example .env
```

2. Install dependencies:

```bash
make install
```

3. Run backend + frontend:

```bash
make dev
```

4. Open:

```text
http://localhost:5173
```

## Useful Make targets

- `make run` - start backend only
- `make dev` - start backend and frontend together
- `make build-image` - build the single Docker image
- `make run-image` - run the Docker image locally
- `make stop-image` - stop the Docker container
- `make health` - check backend health endpoint
- `make frontend-build` - build the frontend
- `make backend-check` - compile backend Python files
- `make dsql-list` - print ordered SQL files

## Demo prompts

- What is moving right now on Polymarket?
- Give me the top live signals right now.
- Which markets show strong buy pressure?
- Which markets look large-fill-driven?
- Give me the freshest signals instead of the highest score.
- Who is driving activity in this market?
- Show recent fills behind this signal.
- What market metadata do we have for this asset?

## API

- `GET /api/health`
- `POST /api/signup`
- `POST /api/token/validate`
- `POST /api/chat/stream`

SSE events:

- `start`
- `context_meta`
- `token`
- `final`
- `done`
- `error`

## DSQL file order

- `dsql/01_sources.sql`
- `dsql/02_normalization.sql`
- `dsql/03_metadata.sql`
- `dsql/04_flow_windows.sql`
- `dsql/05_signal_context.sql`
- `dsql/06_materialized_views.sql`

The SQL statements in `dsql/` are preserved exactly from the provided Polymarket definitions, only split into smaller files for organization.

## Docker

Recommended image name:

`public.ecr.aws/i3m5v2n6/deltastreaminc/polymarket-live-signal-radar-demo:latest`

Run the demo locally with Docker:

```bash
docker run --rm -p 8000:8000 public.ecr.aws/i3m5v2n6/deltastreaminc/polymarket-live-signal-radar-demo:latest
```

Then open:

```text
http://localhost:8000
```
