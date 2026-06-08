# DeltaStream Signup Chat Starter

This example is a minimal Python starter app you can run locally or in Docker.

It demonstrates:
- Email signup flow against the demo signup API
- A single shared `api_token` used for both Anthropic and DeltaStream MCP
- A Streamlit chat UI backed by a pydantic-ai agent
- Safety guardrails that only allow queries against `starter.public.pageviews_mview`

## DeltaStream Setup (Required)

Before using chat in this app, set up the required relations in DeltaStream.

Prerequisites:
- Your default store already has a `pageviews` topic.
- Datagen for `pageviews` is already running.
- No manual write/`INSERT INTO` step is required for this example.

Run these statements in order (or run each file in order):

```sql
-- dsql/01_database.sql
CREATE DATABASE starter;
```

```sql
-- dsql/02_pageviews_stream.sql
CREATE STREAM starter.public.pageviews (
  viewtime BIGINT,
  userid VARCHAR,
  pageid VARCHAR
)
WITH (
  'topic'='pageviews',
  'value.format'='json',
  'key.format'='json',
  'key.type'='STRUCT<userid VARCHAR>'
);
```

```sql
-- dsql/03_pageviews_mview.sql
CREATE MATERIALIZED VIEW starter.public.pageviews_mview
WITH (
  'retention.millis' = 3600000,
  'timestamp' = 'viewtime'
)
AS
SELECT
  viewtime,
  userid,
  pageid
FROM starter.public.pageviews;
```

```sql
-- dsql/04_grants.sql
GRANT USAGE ON DATABASE starter TO ROLE base_demo_role;
GRANT USAGE ON SCHEMA public TO ROLE base_demo_role;
GRANT SELECT ON RELATION starter.public.pageviews_mview TO ROLE base_demo_role;
```

Quick verification:

```sql
SELECT * FROM starter.public.pageviews_mview LIMIT 20;
```

## Flow

1. Enter an email and submit signup.
2. Check email and click confirmation link.
3. Copy the API token from the confirmation page.
4. Paste token in the app.
5. Chat with the agent.

Notes:
- Re-signup is allowed and revokes old token after confirm.
- Confirmation links are single-use and expire after 24 hours.
- Token expires after 30 days.

## Endpoints Configured In Code

These live in `src/constants.py` so they are easy to update:
- Signup API: `https://demo.local.deltastream.io/api/signup`
- Anthropic base URL: `https://demo.local.deltastream.io/anthropic/`
- DeltaStream MCP URL: `https://api-kd8j38.stage.deltastream-internal.name/mcp/v2`

This environment uses a self-signed certificate, so TLS verification is disabled by default.
You can override endpoints (including the Anthropic proxy for k3d) and TLS mode with env vars.

Example override:

```bash
ANTHROPIC_BASE_URL="https://<your-k3d-anthropic-host>/anthropic/" make run
```

## Local Run

```bash
make install
make run
```

Open `http://localhost:8501`.

Optional token prefill:

```bash
cp .env.example .env
API_TOKEN="<your token>" make run
```

Full override example:

```bash
SIGNUP_API_URL="https://demo.local.deltastream.io/api/signup" \
ANTHROPIC_BASE_URL="https://<your-k3d-anthropic-host>/anthropic/" \
DELTASTREAM_MCP_URL="https://api-kd8j38.stage.deltastream-internal.name/mcp/v2" \
INSECURE_DEMO_TLS=true \
make run
```

## Docker Run

```bash
make docker-build
make docker-run
```

Open `http://localhost:8501`.

If `demo.local.deltastream.io` is only in your host `/etc/hosts`, the container will not see that
entry by default. Pass an explicit IP mapping when running Docker:

```bash
make docker-run DEMO_HOST_IP=195.252.249.195
```

You can find the IP from your host `/etc/hosts` entry and use that value.

## Project Layout

- `app.py`: Streamlit UI for signup, token validation, and chat
- `dsql/`: Required DeltaStream SQL setup statements for this example
- `src/constants.py`: Endpoint and policy constants
- `src/config.py`: Typed runtime configuration
- `src/http_clients.py`: Signup + endpoint probe helpers
- `src/chat_backend.py`: pydantic-ai + MCP backend with query policy guardrails

## Guardrails

The starter enforces query policy in multiple places:
- Prompt instructions require read-only access and `LIMIT`
- Runtime SQL validator rejects non-`SELECT` statements
- Runtime SQL validator rejects relations outside the allowed materialized view

If you build on this template, keep these checks unless you explicitly intend broader access.
