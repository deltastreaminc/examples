# Polymarket Live Signal Radar

A standalone demo that uses **PydanticAI + Anthropic Sonnet 4.6** with a **DeltaStream MCP server** and a React chat UI with SSE streaming.

This demo explains live Polymarket market activity from continuously precomputed DeltaStream context built on top of Goldsky Polymarket streams and Gamma metadata. The runtime agent does not scan raw fills, matches, balances, or market metadata at inference time. Instead, DeltaStream continuously prepares agent-ready materialized views, and the agent queries those views through the DeltaStream MCP toolset during inference.

Primary context:

- `"polymarket"."public"."pm_live_signal_radar_mv"`

Drill-down context:

- `"polymarket"."public"."pm_wallet_asset_flow_mv"`
- `"polymarket"."public"."pm_wallet_activity_mv"`
- `"polymarket"."public"."pm_recent_fills_mv"`
- `"polymarket"."public"."pm_market_asset_metadata_mv"`
- `"polymarket"."public"."pm_user_balances_mv"`

Every answer is anchored to `ctx_time_ms`, the latest reflected source-event timestamp in the fetched context.

Expected qualified runtime views:

- `"polymarket"."public"."pm_live_signal_radar_mv"`
- `"polymarket"."public"."pm_wallet_asset_flow_mv"`
- `"polymarket"."public"."pm_wallet_activity_mv"`
- `"polymarket"."public"."pm_recent_fills_mv"`
- `"polymarket"."public"."pm_market_asset_metadata_mv"`
- `"polymarket"."public"."pm_user_balances_mv"`

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
- PydanticAI + Anthropic can answer from those materialized views through DeltaStream MCP without scanning raw event streams at chat time.

## Runtime architecture

- FastAPI backend serves the React frontend and exposes chat endpoints.
- Backend validates the token against the configured LLM provider (Anthropic or Gemini) and DeltaStream MCP.
- PydanticAI registers the DeltaStream MCP server as an agent toolset.
- The agent queries the relevant DeltaStream materialized views during inference.
- Chat runs as a background job: the frontend calls `POST /api/chat/start` and then
  polls `GET /api/chat/poll/{job_id}` for incremental events (SQL, streamed answer
  tokens, timing, final). Polling is used instead of a long-lived SSE stream because
  many gateways buffer responses and enforce a short total-request timeout, which
  breaks streaming. Each poll is a short request immune to those limits.
- Because chat jobs are held in-process, run a **single worker / single replica**
  (the default `uvicorn` command uses one worker), or enable sticky sessions so polls
  reach the process that started the job.

## Question routing

- Broad briefing, movers, buy pressure, sell pressure, large-fill-driven:
  - `"polymarket"."public"."pm_live_signal_radar_mv"`
- Who is driving activity in a market or outcome:
  - `"polymarket"."public"."pm_wallet_asset_flow_mv"`
  - optionally `"polymarket"."public"."pm_wallet_activity_mv"`
- Raw fill examples or transaction-level evidence:
  - `"polymarket"."public"."pm_recent_fills_mv"`
  - plus `"polymarket"."public"."pm_market_asset_metadata_mv"` for human-readable labels
- Metadata lookups:
  - `"polymarket"."public"."pm_market_asset_metadata_mv"`
- Balance questions:
  - `"polymarket"."public"."pm_user_balances_mv"`

For broad briefings, the agent should use the DeltaStream MCP tools to query the fully qualified runtime views and apply the system-prompt sorting guidance for signal score, freshness, imbalance, large-fill share, and price range.

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

### Quick mode (faster responses)

To reduce timeout risk and speed up responses, the backend supports quick mode knobs in `.env`:

```bash
QUICK_MODE_ENABLED=true
QUICK_MODE_MAX_ATTEMPTS=2
QUICK_MODE_MAX_TOKENS=1400
QUICK_MODE_TIMEOUT_SECONDS=60
```

Quick mode lowers retry depth and constrains model generation budget/time per attempt.

### Choose the LLM provider

The LLM provider is selected by the `MODEL_NAME` prefix in `.env`. No code changes are needed.
The Anthropic and Gemini proxy URLs are derived automatically from `AI_DEMO_BACKEND`.

- Gemini (default):

```bash
MODEL_NAME=google:gemini-3.5-flash
```

- Anthropic:

```bash
MODEL_NAME=anthropic:claude-sonnet-4-6
```

Both providers use the same DeltaStream demo access token. With the default `google:` (or
`gemini:`) model, requests are routed to the `/gemini` gateway with the token sent as a
`Authorization: Bearer` header, and token validation probes the Gemini endpoint. Switching to
an `anthropic:` model routes to `/anthropic` instead. The DeltaStream MCP toolset, system
prompt, quick mode, and streaming behave identically across providers.

Gemini is a "thinking" model, so reasoning tokens share the output budget and dynamic thinking
can dominate latency on multi-tool agentic tasks. The backend bounds this by default:

```bash
GEMINI_MAX_OUTPUT_TOKENS=8192   # headroom so the visible answer is not truncated
GEMINI_THINKING_LEVEL=low       # Gemini 3.x thinking control (low|high)
# GEMINI_THINKING_BUDGET=512    # Gemini 2.5 thinking control (token budget)
```

If answers get cut off, raise `GEMINI_MAX_OUTPUT_TOKENS`. If requests time out, keep
`GEMINI_THINKING_LEVEL=low` and/or raise `QUICK_MODE_TIMEOUT_SECONDS`.

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

## Run locally in Docker

The image works at any mount path — the serving base path is chosen at runtime from
`ROOT_PATH` (unset means root), so the **same published image** runs standalone or behind a
prefix with no rebuild. To run it locally, just pull and run:

```bash
docker run --rm -p 8000:8000 \
  public.ecr.aws/i3m5v2n6/deltastreaminc/polymarket-live-signal-radar-demo:latest
```

Then open <http://localhost:8000/> and paste your DeltaStream access token in the UI.

Notes:

- Your machine must be able to reach `demo.deltastream.io` (Gemini/Anthropic gateway + signup)
  and `api-kd8j38.stage.deltastream-internal.name` (MCP).
- No API key is required; the DeltaStream access token you paste in the UI drives everything.
- The image defaults to Gemini (`google:gemini-3.5-flash`). To use Anthropic instead, override
  the provider at run time: `-e MODEL_NAME=anthropic:claude-sonnet-4-6`.

Alternatively, `make dev` runs the backend and Vite dev server together without Docker.

## Deploying behind a path prefix

The app serves at the root path (`/`) by default. To serve it behind a prefix such as
`/polymarket`, set the `ROOT_PATH` environment variable on the container — no rebuild or build
arg needed:

```bash
docker run --rm -p 8000:8000 -e ROOT_PATH=/polymarket <image>
# or in Kubernetes: env: [{ name: ROOT_PATH, value: /polymarket }]
```

At startup the backend serves everything under that prefix and injects
`<base href="/polymarket/">` plus `window.__APP_BASE__` into `index.html`, so the frontend's
relative asset URLs and the chat API call resolve correctly. The frontend is built once with a
relative base, so a single image works at any mount path.

Your Ingress should route `/polymarket/*` to the container **without stripping** the prefix
(the app expects to see `/polymarket/...`). For a Gateway API `HTTPRoute`, a `PathPrefix` match
on `/polymarket` with no `URLRewrite` filter is correct.

Note: token validation and signup are served by the demo platform at the host root (`/api/*`)
and are called directly by the browser; only the chat endpoints run in this container under the
prefix. Leaving `ROOT_PATH` unset keeps everything at `/` (local Docker / `make dev`).

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
- `dsql/09_grants.sql`

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
