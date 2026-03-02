# OCI Real-Time AI Agent — Reference Implementation

This repo contains everything you need to build a real-time AI agent on top of OCI Logging, using OCI Streaming for Apache Kafka, DeltaStream, and OpenAI Agent Builder.

The companion blog post and demo video walk through the architecture and show the agent in action. This repo is the code behind them.

**Architecture:**
```
OCI Logging → Connector Hub → OCI Streaming → DeltaStream → MCP → AI Agent
```

---

## What's in this repo

```
.
├── .env.example                          # Credential placeholders — copy to .env
├── .gitignore
├── deltastream/
│   ├── 01_store.sql                      # Connect DeltaStream to OCI Streaming
│   ├── 02_raw_streams.sql                # Define raw input streams from Connector Hub topics
│   ├── 03_enriched_streams.sql           # Transform and enrich raw events
│   ├── 04_materialized_views.sql         # Create agent-queryable views + set descriptions
│   └── mcp_config.json                   # DeltaStream MCP server configuration
└── docs/
    └── connector_hub_setup.md            # Step-by-step Connector Hub configuration guide
```

---

## Prerequisites

- An OCI tenancy with OCI Logging enabled (audit logs and/or service logs)
- A DeltaStream account — see [Resources](#resources) below for how to get access
- An OpenAI account with access to Agent Builder
- Node.js 18+ (for the DeltaStream MCP server)

---

## Setup

### 1. Clone and configure credentials

```bash
git clone https://github.com/deltastreaminc/examples.git
cd examples/oci-realtime-agent
cp .env.example .env
```

Open `.env` and fill in your values:

| Variable | Where to find it |
|---|---|
| `OCI_STREAMING_BOOTSTRAP` | OCI Console → Streaming → Stream Pools → your pool → Kafka connection settings |
| `OCI_STREAM_POOL_OCID` | OCI Console → Streaming → Stream Pools → your pool |
| `OCI_SASL_USERNAME` | Format: `<tenancy>/<username>/<stream_pool_ocid>` |
| `OCI_AUTH_TOKEN` | OCI Console → Profile (top right) → Auth Tokens → Generate Token |
| `DELTASTREAM_TOKEN` | DeltaStream Console → Integrations → API Tokens |
| `OPENAI_API_KEY` | platform.openai.com → API Keys |

---

### 2. Configure OCI Connector Hub

Connector Hub routes your OCI Logging events into OCI Streaming topics with no code required.

See **[docs/connector_hub_setup.md](docs/connector_hub_setup.md)** for a step-by-step walkthrough.

You will create two service connectors:
- **Audit logs** → OCI Streaming topic (set `OCI_AUDIT_TOPIC` in your `.env`)
- **Service/function logs** → OCI Streaming topic (set `OCI_LOGGING_TOPIC` in your `.env`)

---

### 3. Run the DeltaStream SQL scripts

Run the scripts in order using the DeltaStream console or CLI. Each script builds on the previous one.

```sql
-- In the DeltaStream console, run each file in order:
-- 01_store.sql             → creates two stores (see below)
-- 02_raw_streams.sql       → defines input streams on your Connector Hub topics
-- 03_enriched_streams.sql  → transforms raw events into clean, enriched streams
-- 04_materialized_views.sql  → creates agent-queryable views with descriptions
```

**Why two stores?** OCI has two distinct Kafka-compatible streaming services with different auth patterns:

- **`oci_streaming`** (SASL/PLAIN + Auth Token) — this is OCI Streaming native, which is where Connector Hub delivers your raw log events. It uses your OCI tenancy credentials.
- **`oci_streaming_kafka`** (SASL/SCRAM-SHA-512 + super-user) — this is OCI Streaming for Apache Kafka, a fully managed Kafka cluster. DeltaStream writes the enriched output streams here, and the MCP server reads from it.

Both are in `01_store.sql`. Replace the placeholders in each with the corresponding values from your `.env`.

- `<OCI_STREAMING_BOOTSTRAP>` → your OCI Streaming bootstrap server
- `<OCI_SASL_USERNAME>` → your SASL username
- `<OCI_AUTH_TOKEN>` → your OCI auth token
- `<OCI_AUDIT_TOPIC>` → the topic name you configured in Connector Hub
- `<OCI_LOGGING_TOPIC>` → the topic name you configured in Connector Hub

> **Tip:** After running `04_materialized_views.sql`, give the views a minute to backfill before querying. The `starting.position = 'earliest'` setting will process historical events first, then stay current. You can remove this if you do NOT want backfill.

---

### 4. Configure the MCP server

Copy `deltastream/mcp_config.json` to your OpenAI Agent Builder MCP configuration location and fill in your values:

| Placeholder | Value |
|---|---|
| `<YOUR_DELTASTREAM_API_TOKEN>` | Your DeltaStream API token |
| `<YOUR_DATABASE_NAME>` | The DeltaStream database containing your views |
| `<YOUR_SCHEMA_NAME>` | The DeltaStream schema containing your views |

---

### 5. Create your agent in OpenAI Agent Builder

1. Go to [platform.openai.com/agents](https://platform.openai.com/agents)
2. Create a new agent
3. Set the system prompt (see below)
4. Add DeltaStream as an MCP tool provider using your `mcp_config.json`
5. The agent will automatically discover `oci_audit_mv` and `oci_logging_mv` as available tools

**Suggested system prompt:**

```
You are an OCI operations assistant with access to real-time data from an OCI tenancy.

You have two tools available:
- oci_audit_mv: real-time feed of audit events — API calls, policy changes, resource modifications, identity actions
- oci_logging_mv: real-time feed of OCI Functions invocation logs — what functions ran, what they logged, and any errors

When answering questions:
- Always query with a recent time window (last 15–30 minutes unless asked otherwise)
- For failure questions, check responsestatus for 4xx/5xx in audit, and search message for "error", "failed", or "exception" in logging
- For incident questions, use besttraceid to correlate audit events with function logs
- Be specific: name principals, function IDs, timestamps, and status codes in your answers
- If you don't find relevant events in the time window, say so and suggest widening the window
```

---

## Adapting this to your environment

The two streams in this repo are a starting point, not a prescription. Your environment likely has different services, log groups, and questions that matter. Some directions to take it further:

- **Add more log sources** — extend `02_raw_streams.sql` to include API Gateway logs, VCN flow logs, or custom application logs
- **Narrow the filter** — modify the `WHERE` clause in `03_enriched_streams.sql` to focus on specific event types or compartments
- **Add derived fields** — extend the `SELECT` in `03_enriched_streams.sql` with additional `REGEXP_EXTRACT` or `COALESCE` logic specific to your naming conventions
- **Add more views** — create additional materialized views in `04_materialized_views.sql` focused on specific use cases (e.g. a view filtered to failed events only, or scoped to a single application)

The architecture is the same regardless of what you put in the streams.

---

## Troubleshooting

**Events not arriving in raw streams**
- Verify Connector Hub is in "Active" state in OCI Console
- Confirm the topic names in `02_raw_streams.sql` match what Connector Hub is writing to
- Check that your OCI Auth Token hasn't expired (they have a maximum 1-year lifetime)

**DeltaStream store connection failing**
- Confirm the SASL username format: `<tenancy_name>/<oci_username>/<stream_pool_ocid>`
- Verify the bootstrap server URL matches your OCI region
- Ensure the Auth Token was generated for the correct user

**Materialized views showing no data**
- Wait 1–2 minutes after creation for backfill to complete
- Verify the enriched streams (`oci_audit`, `oci_logging`) have data first
- Check that the `WHERE` filters in `03_enriched_streams.sql` match your actual event types

**Agent not finding the MCP tools**
- Confirm `DELTASTREAM_RELATIONS` in `mcp_config.json` matches the exact view names
- Verify the database and schema names are correct
- Check that the DeltaStream API token has read access to the views

---

## Resources

- [DeltaStream Documentation](https://docs.deltastream.io)
- [DeltaStream — get in touch if you'd like access](https://www.deltastream.io/contact-us)
- [OCI Streaming for Apache Kafka](https://docs.oracle.com/en-us/iaas/Content/Streaming/Tasks/kafkacompatibility.htm)
- [OCI Connector Hub Documentation](https://docs.oracle.com/en-us/iaas/Content/connector-hub/overview.htm)
- [OpenAI Agent Builder](https://platform.openai.com/agents)
- [Blog post — companion to this repo](#)
- [Demo video](#)
