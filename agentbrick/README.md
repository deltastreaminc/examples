We are building an end to end use case where a SOC agent is build with Databrick's AgentBricks platform and DeltaStream provides the real-time context for the agent. 
Goal: A Databricks SOC agent (Agent Bricks) that can answer SOC questions by calling DeltaStream’s MCP tools (your real-time materialized view context), plus optionally other Databricks-native tools later.

Key pieces

- DeltaStream continuously computes SOC context into a Materialized View and exposes it via its native MCP endpoint (tools = views your token can SELECT).
- Databricks connects to that MCP server as an External MCP server using a Unity Catalog HTTP connection and a managed proxy.
- Agent Bricks (Multi-Agent Supervisor) uses the external MCP connection as one of its “subagents/tools,” then publishes a serving endpoint you can chat with in Playground or call via API.

## 1) Databricks prerequisites (do these first)
### 1.1 Enable required previews / capabilities

Agent Bricks is Beta and has workspace requirements (admin tasks). Confirm you have:

- Mosaic AI Agent Bricks Preview enabled
- Serverless compute enabled
- Unity Catalog enabled
- Access to foundation models via system.ai
- A serverless budget policy with nonzero budget
- Workspace is in a supported region (us-east-1 or us-west-2 for AWS per docs)

If you’re specifically using Multi-Agent Supervisor, Databricks also calls out:

- “Agent Framework: On-Behalf-Of-User Authorization” preview enabled
- Production monitoring for MLflow (Beta) enabled (for tracing)

## 2) DeltaStream prerequisites (MCP endpoint + least-privilege token)

Build the real-time Materialized Views that represent Real-Time Context for the use case. 

Once the Materialized view(s) are ready prepare the credentials for the agent to access the context. See docs for details: https://docs.deltastream.io/how-do-i.../expose-a-materialized-view-over-mcp

## 3) Register DeltaStream as an External MCP server in Databricks

Databricks supports External MCP servers via a Unity Catalog HTTP connection and a managed proxy. Your MCP server must support Streamable HTTP transport (DeltaStream’s MCP endpoint is designed for MCP JSON-RPC over HTTP and lists tools; Databricks explicitly requires Streamable HTTP for external MCP).

- In Databricks, open Catalog (Catalog Explorer)

- Go to Connections → Create connection

- Choose HTTP connection type

- Fill:

  - Host / URL: your DeltaStream MCP endpoint (example: https://<deltastream-host>/mcp/v1)

  - Auth: Bearer token

  - Important: enable the checkbox “Is mcp connection” (this is what makes it usable as an MCP server)

- Save the connection (give it a clear name, e.g. deltastream_soc_mcp)

- Grant permissions:

  - Grant intended users/groups USE CONNECTION on that connection (otherwise the agent can’t use it for those users).
 
## 4) Build the SOC agent in Agent Bricks (Multi-Agent Supervisor)

For a SOC copilot that calls tools, the most straightforward “first Agent Bricks experience” is Agent Bricks: Multi-Agent Supervisor because it’s explicitly designed to orchestrate MCP servers, functions, Genie spaces, etc.

### 4.1 Open Agent Bricks builder

- In the left nav, go to Agents

- Find Multi-Agent Supervisor tile

- Click Build

### 4.2 Step 1: Provide the external MCP server as a “subagent/tool”

You can add subagents/tools including External MCP server.

- Choose External MCP Server

- Select your UC connection: deltastream_soc_mcp

- Give it a friendly name (example): RealTimeSOCContext

- In “Describe the content”, be explicit, e.g.:

“Real-time SOC context from DeltaStream materialized views. Use this to answer: top risky users/IPs, explain risk spikes, show recent correlated events (auth failures + suspicious outbound + IDS alerts), and return current risk scores/aggregations computed over rolling windows.”

This description directly helps the supervisor decide when to call the MCP tools.

### 4.3 Step 2: Configure the supervisor agent

On the Build tab:

- Name: SOC Copilot (DeltaStream RTC via MCP)

- Description: what it does

- Configure Agents: include your RealTimeSOCContext MCP server (and optionally other tools later)

- Instructions: paste strong SOC-specific behavioral rules. Example you can use immediately:

Suggested supervisor instructions (copy/paste)

- “You are a SOC copilot. Prefer calling RealTimeSOCContext for any question about ‘right now’, ‘last X minutes’, risk scores, suspicious entities, or correlated activity.”

- “Always cite or summarize the returned tool output before making conclusions.”

- “If the user asks for an action (create ticket, isolate host), ask for confirmation and list what you would do (don’t execute unless a tool exists and policy allows).”

- “When showing results, format as: Entities → risk score → why (key contributing signals) → timestamps/window.”

Click Create Agent. Databricks notes it can take minutes to longer depending on build/optimization.

## 5) Test and iterate (Playground + Examples)
### 5.1 Test in the right-side panel or AI Playground

Agent Bricks supports testing in-place or via Open in Playground.

Start with prompts that force tool use, mirroring your blog:

- “Show me the highest-risk users right now.”

- “Explain why risk spiked for IP 10.0.0.25 in the last 3 minutes.”

- “Which IPs show brute force + suspicious outbound flows?”
