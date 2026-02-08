# Banking Customer Support / Concierge Agent Demo (DeltaStream Real-Time Context Engine)

This repo contains an end-to-end demo showing how **DeltaStream** acts as the **Real-Time Context Engine for GenAI Agents** in a high-stakes, constantly-changing environment: **banking customer support**.

The core idea is simple:

> Support agents fail when context is stale.  
> DeltaStream continuously builds **live, consistent, auditable context** from event streams and exposes it to agents via DeltaStream’s **built-in MCP server**.

Instead of an agent making many slow calls to ledger, payments, transfers, disputes, and notifications systems—and stitching context at runtime—DeltaStream computes a single up-to-the-moment “support truth” view the agent can query instantly.

---

## What this demo includes

- A **Java data generator** that produces realistic banking events into Kafka topics:
  - Ledger updates (balances)
  - Authorization events (pending/settled/reversed)
  - Transfer lifecycle updates (pending/failed/returned/completed)
  - Holds (placed/released)
  - Disputes (open/investigating/resolved)
  - Notifications (what the customer was told and when)

- A **DeltaStream SQL script** that ingests those topics and builds real-time context / materialized views:
  - `support_context_mv` (the unified “account session context” for the agent)
  - `bank_support_recent_transfer_stats_mv`
  - `bank_support_recent_auth_stats_mv`
  - `latest_transfer_per_customer_mv`
  - `latest_auth_per_customer_mv`
  - `latest_notification_per_customer_mv`

- (Optional) A simple flow for how an agent on **OpenAI Frontier** would call DeltaStream MCP tools to fetch context, then have the LLM explain and act.

---

## Why this matters (in one paragraph)

In banking support, **state changes mid-conversation**. Transfers update, authorizations settle/reverse, holds change, disputes advance, and notifications go out. If an agent builds context at runtime via multiple API calls (even through MCP), it will see inconsistent “as-of” timestamps and produce contradictions. DeltaStream solves this by continuously computing a single, consistent real-time context view and serving it with **sub-second latency** through MCP—so the agent reasons over truth, not guesses.

---

## Deploy the DeltaStream SQL (build the real-time context)

Open your DeltaStream workspace and run statements in DeltaStreamBankingCustomerSupport.sql.

Query DeltaStream materialized views

In DeltaStream SQL editor:

```sql
SELECT * FROM support_context_mv LIMIT 10;
```

Or filter to a specific customer:

```sql
SELECT *
FROM support_context_mv
WHERE customer_id = 'C000123';
```

You should see:

  - balances
  - latest transfer lifecycle state
  - latest auth state
  - hold/dispute info (if present)
  - latest customer notification and timestamp

## Using the context from an AI agent (via DeltaStream MCP)

DeltaStream exposes the real-time contexts through its built-in MCP server, allowing an agent to retrieve live context with a single tool call.

A typical agent flow is:

  - Customer asks: “Where is my transfer?”
  - Agent calls MCP tool: support_context_mv (by customer_id)
  - (Optional) Agent fetches recent activity: bank_support_recent_transfer_stats_mv
  - LLM responds grounded in current truth (no guessing, no contradictions)

Why this is different from “runtime context building”
  - If you instead expose raw systems through MCP and let the agent stitch context at runtime, you’ll get:
  - multiple round-trips per prompt
  - inconsistent “as-of” timestamps
  - higher latency under load
  - duplicated join logic across agents

DeltaStream solves this by computing consistent, real-time context continuously.
