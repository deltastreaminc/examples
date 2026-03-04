-- ============================================================
-- Step 4: Create Materialized Views for MCP
--
-- Materialized views give the DeltaStream MCP server a
-- queryable, always-current snapshot of each stream.
-- The agent calls these views as tools — one call per view,
-- no query orchestration needed.
--
-- Run this after Step 3. The views will backfill from
-- 'earliest' and then stay current as new events arrive.
-- ============================================================


-- ------------------------------------------------------------
-- Audit Materialized View
-- ------------------------------------------------------------
CREATE MATERIALIZED VIEW "oci_audit_mv" AS
SELECT * FROM "oci_audit"
WITH ('starting.position' = 'earliest');


-- ------------------------------------------------------------
-- Logging Materialized View
-- ------------------------------------------------------------
CREATE MATERIALIZED VIEW "oci_logging_mv" AS
SELECT * FROM "oci_logging"
WITH ('starting.position' = 'earliest');


-- ============================================================
-- Step 5: Set AI-Friendly Descriptions
--
-- These descriptions are read by the DeltaStream MCP server
-- and surfaced to the agent as tool descriptions. The clearer
-- these are, the better the agent reasons about when and how
-- to use each view.
-- ============================================================

ALTER RELATION "oci_audit_mv" SET description =
'Continuously updated feed of OCI audit events from across your tenancy.
Every API call made against OCI services produces an audit event here
within seconds — whether triggered by a human user, a service principal,
or an automated process.

Use this view to answer questions about who did what, when, to which
resource, and whether it succeeded. It is the authoritative source for
security, compliance, and change-tracking questions.

Key fields:
- audittime: when the event occurred. Always filter by time window.
- eventname: human-readable action name (e.g. CreateUser, DeleteBucket).
- principalname: who triggered the action (e.g. alice@corp, svc-deploy).
- requestaction: HTTP method — GET, POST, PUT, DELETE.
- requestpath: the API path called.
- responsestatus: HTTP status code. Filter 4xx/5xx for failures.
- compartmentid: scope to a specific part of the tenancy.
- resourceid: OCID of the affected resource.
- opcrequestid: primary correlation key. Match to oci_logging_mv.opcrequestid
  to find function invocations triggered by this API call.
- besttraceid: fallback correlation key when opcrequestid is unavailable.
- best_request_correlation: most reliable single identifier for this request.

Usage tips:
- Always include a time window on audittime (e.g. last 15 minutes).
- For failures: filter responsestatus LIKE ''4%'' OR ''5%''.
- For changes: filter requestaction IN (''POST'', ''PUT'', ''DELETE'').
- For a specific principal: filter on principalname.
- To correlate with function logs: match besttraceid to oci_logging_mv.besttraceid.';


ALTER RELATION "oci_logging_mv" SET description =
'Continuously updated feed of OCI Functions invocation log events.
Each record represents a single function invocation and captures the
log output, identifiers needed to trace the call back to its origin,
and the application and function context.

Use this view to answer questions about function behavior, errors, and
invocation patterns. It is the primary source for questions about what
a function did, what it logged, and whether it succeeded or failed.

Key fields:
- logtime: when the invocation occurred. Always filter by time window.
- message: log output from the function — primary field for error investigation.
  Search for: error, exception, failed, timeout, null.
- functionid: OCID of the specific function. Filter to isolate one function.
- applicationid: OCID of the Functions application. Use to group functions.
- logsubject: human-readable function/application identifier.
- compartmentid: scope to a specific part of the tenancy.
- opcrequestid: primary correlation key. Match to oci_audit_mv.opcrequestid
  to find the API call that triggered this invocation.
- besttraceid: fallback correlation key when opcrequestid is unavailable.
- correlationid_full: best available full request identifier for display.
- containerinstance_ocid: OCID extracted from message text, if present.
- lifecycle_phase: structured lifecycle keyword extracted from message
  (e.g. Processing, Initiating, Found). Helps identify cold starts.

Usage tips:
- Always include a time window on logtime (e.g. last 15 minutes).
- For errors: filter message LIKE ''%error%'' OR ''%failed%'' OR ''%exception%''.
- For a specific function: filter on functionid or logsubject.
- To find what triggered a function error: match besttraceid to
  oci_audit_mv.besttraceid and look for recent write actions (POST/PUT/DELETE).';
