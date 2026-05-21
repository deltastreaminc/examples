# DeltaStream Hello World Agent (Pageviews)

This is a minimal template for building an agent app with DeltaStream.

It demonstrates one clear flow:

1. Write `pageviews` events into Kafka.
2. Build a DeltaStream stream and materialized view for cumulative page counts.
3. Ask a chat agent questions that are answered with DeltaStream MCP tools.

The code is intentionally small and readable so teams can fork it as a starting point.

## What this template creates

- Kafka topic: `pageviews`
- DeltaStream stream: `pageviews_stream`
- DeltaStream materialized view: `pageview_counts_mv`
- Deterministic query name: `hello_world_pageview_counts_q`
- Database: `hello_world_demo`
- Schema: `public`

The MV is all-time cumulative:

```sql
SELECT page, COUNT(*) AS pageview_count
FROM pageviews_stream
GROUP BY page;
```

## Prerequisites

- Python 3.11+
- Kafka cluster credentials reachable by DeltaStream (for example Confluent Cloud)
- Anthropic API key
- DeltaStream API token
- DeltaStream account with permissions to create database/store/relations

## Quickstart (local Python)

1. Install dependencies:

```bash
make install
```

This creates a local virtual environment in `.venv` automatically.

2. Start app:

```bash
make run
```

You can pass runtime config directly to `make run`:

```bash
make run \
  KAFKA_BROKERS="pkc-lzvrd.us-west4.gcp.confluent.cloud:9092" \
  KAFKA_USERNAME="<kafka-user>" \
  KAFKA_PASSWORD="<kafka-password>" \
  ANTHROPIC_API_KEY="<anthropic-key>" \
  DELTASTREAM_API_TOKEN="<deltastream-token>" \
  DELTASTREAM_API_URL="https://api-kap822.deltastream.io" \
  DELTASTREAM_MCP_URL="https://api-kap822.deltastream.io/mcp/v2" \
  ANTHROPIC_MODEL="claude-sonnet-4-20250514"
```

These values are used to pre-fill the web form on startup.

3. Open Streamlit URL (usually `http://localhost:8501`).
4. Enter credentials in the Setup section.
5. Click `Validate Connections`.
6. Click `Run Setup`.
7. Click `Start Datagen`.
8. Ask chat questions like:
   - `What are the top pages by pageviews?`
   - `How many views does /pricing have?`

## Quickstart (Docker)

Build image:

```bash
make docker-build
```

Build local image with buildx (single platform):

```bash
make docker-build-local
```

Build and publish multi-platform image (amd64 + arm64):

```bash
make docker-build-multi
```

Run container:

```bash
make docker-run
```

Detached mode:

```bash
make docker-run-detached
```

Stop detached container:

```bash
make docker-stop
```

Defaults:

- Image: `deltastream-hello-world-agent:latest`
- Container: `deltastream-hello-world-agent-app`

Override examples:

```bash
make docker-build IMAGE_TAG=v0.1.0
make docker-run PORT=8502
```

## UI behavior

- `Validate Connections`: tests Kafka, Anthropic, and DeltaStream credentials.
- `Run Setup`: attempts topic creation and applies static SQL statements.
  - Topic defaults: `pageviews` with 3 partitions and replication factor 3 (Confluent-friendly).
  - If topic creation fails due to ACLs, the app shows manual-create guidance.
- `Run Cleanup`: deterministically terminates query `hello_world_pageview_counts_q`, then drops
  `pageview_counts_mv` and `pageviews_stream`.
- `Run Cleanup + Drop DB`: same as cleanup, plus drops `hello_world_demo`.
- `Check Pipeline Status`: checks whether `pageviews_stream` and `pageview_counts_mv` exist and
  confirms the pipeline query `actual_state` is `running`.
- `Wait Until Ready`: polls pipeline status until relations are ready (or timeout).
- `Start Datagen` / `Stop Datagen`: controls a local background pageview producer.
- `Reset Demo`: clears chat history and datagen counters; it does not delete DeltaStream objects.

Chat history is session-only and is not persisted across app restarts.

## Project layout

- `app.py` - Streamlit UI
- `src/config.py` - typed runtime config and validation
- `src/setup.py` - setup and validation workflow
- `src/datagen.py` - pageviews data generator
- `src/chat_backend.py` - pluggable chat backend and pydantic-ai implementation
- `sql/pageviews.sql` - static DeltaStream SQL
- `Dockerfile`, `Makefile`, `.dockerignore` - container workflow

## Troubleshooting

- Kafka topic creation fails:
  - Create topic `pageviews` manually in your Kafka cluster.
  - Then run `Run Setup` again.
- Chat responds with no data:
  - Ensure datagen is running and setup succeeded.
  - Wait a few seconds and ask again.
- DeltaStream setup fails on store creation:
  - Check broker/username/password values.
  - Confirm your token can create stores.

## Extending this template

- Add fields to `sql/pageviews.sql` and `src/datagen.py` together.
- Add new MVs and update system prompt guidance in `src/chat_backend.py`.
- Add new model/provider backends by implementing `ChatBackend`.
