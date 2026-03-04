-- ============================================================
-- Step 3: Create the Enriched Streams
--
-- These continuously transform the raw input streams into
-- clean, normalized, agent-ready output. DeltaStream runs
-- these as persistent streaming queries — new events are
-- processed automatically as they arrive from OCI.
--
-- Output topics are written back to OCI Streaming for Apache Kafka (or any
-- Kafka-compatible broker). Update 'topic' names if needed.
--
-- These are just sample SQL queries.  You can modify the WHERE clause
-- to better represent the data you are interested in.
-- ============================================================


-- ------------------------------------------------------------
-- Enriched OCI Audit Stream
--
-- Normalizes audit events: resolves principal identity,
-- extracts request/response details, and derives correlation
-- keys (traceid, spanid) for cross-stream analysis.
-- ------------------------------------------------------------
CREATE STREAM "oci_audit"
WITH (
  'store'            = 'oci_streaming_kafka',
  'topic'            = 'mcp-oci-audit',
  'topic.partitions' = 1,
  'topic.replicas'   = 2
) AS
SELECT
  TO_TIMESTAMP_LTZ("time", 'yyyy-MM-dd''T''HH:mm:ss.SSS''Z''') AS "audittime",
  "type"   AS "audittype",
  "source" AS "auditsource",

  -- Tenancy context
  "oracle"->"compartmentid" AS "compartmentid",
  "oracle"->"loggroupid"    AS "loggroupid",

  -- What happened
  "data"->"eventName"       AS "eventname",
  "data"->"eventGroupingId" AS "eventgroupingid",
  "data"->"resourceId"      AS "resourceid",
  "data"->"message"         AS "auditmessage",

  -- Request details
  "data"->"request"->"path"   AS "requestpath",
  "data"->"request"->"action" AS "requestaction",
  "data"->"request"->"id"     AS "auditrequestid",

  -- Response details
  CAST("data"->"response"->"status" AS VARCHAR) AS "responsestatus",
  "data"->"response"->"responseTime"            AS "responsetime",

  -- Who made the request
  "data"->"identity"->"principalName" AS "principalname",
  "data"->"identity"->"principalId"   AS "principalid",

  -- Correlation keys
  -- opcrequestid is the primary key for tracing across OCI services
  ("data"->"request"->"headers"['opc-request-id'])[1] AS "opcrequestid",

  -- traceid / spanid extracted from request id
  SPLIT_INDEX("data"->"request"->"id", '/', 1) AS "traceid",
  SPLIT_INDEX("data"->"request"->"id", '/', 2) AS "spanid",

  -- fallback trace/span from eventGroupingId when request id is absent
  SPLIT_INDEX("data"->"eventGroupingId", '/', 1) AS "eventtraceid",
  SPLIT_INDEX("data"->"eventGroupingId", '/', 2) AS "eventspanid",

  -- best_request_correlation: most reliable single correlation key
  -- prefers opc-request-id, falls back through request id, then event grouping id
  COALESCE(
    ("data"->"request"->"headers"['opc-request-id'])[1],
    SPLIT_INDEX("data"->"request"->"id", '/', 1),
    SPLIT_INDEX("data"->"eventGroupingId", '/', 1)
  ) AS "best_request_correlation",

  -- besttraceid: best available trace root for cross-stream correlation
  COALESCE(
    SPLIT_INDEX("data"->"request"->"id", '/', 1),
    SPLIT_INDEX("data"->"eventGroupingId", '/', 1)
  ) AS "besttraceid"

FROM "oci_audit_raw"
WITH ('starting.position' = 'earliest')
WHERE "type" LIKE 'com.oraclecloud.%';


-- ------------------------------------------------------------
-- Enriched OCI Logging Stream
--
-- Normalizes function invocation log events: extracts app and
-- function context, derives correlation keys, and pulls OCIDs
-- and lifecycle phase indicators from log message text.
--
-- Filtered to function invocation events only. Modify if desired 
-- ------------------------------------------------------------
CREATE STREAM "oci_logging"
WITH (
  'store'            = 'oci_streaming_kafka',
  'topic'            = 'mcp-oci-logging',
  'topic.partitions' = 1,
  'topic.replicas'   = 2
) AS
SELECT
  TO_TIMESTAMP_LTZ("time", 'yyyy-MM-dd''T''HH:mm:ss.SSS''Z''') AS "logtime",
  "type"    AS "logtype",
  "source"  AS "logsource",
  "subject" AS "logsubject",

  -- Tenancy context
  "oracle"->"compartmentid" AS "compartmentid",
  "oracle"->"loggroupid"    AS "loggroupid",
  "oracle"->"logid"         AS "logid",

  -- Function context
  "data"->"applicationId" AS "applicationid",
  "data"->"functionId"    AS "functionid",
  "data"->"containerId"   AS "containerid",

  -- Request identifiers
  "data"->"opcRequestId" AS "opcrequestid",
  "data"->"requestId"    AS "requestid",

  -- correlationid_full: best available full request id for display
  COALESCE("data"->"opcRequestId", "data"->"requestId") AS "correlationid_full",

  -- besttraceid: trace root for cross-stream correlation with oci_audit
  SPLIT_INDEX(
    COALESCE("data"->"opcRequestId", "data"->"requestId"),
    '/', 1
  ) AS "besttraceid",

  -- Invocation source
  "data"->"src" AS "src",

  -- Log message — primary field for error investigation
  "data"->"message" AS "message",

  -- containerinstance_ocid: OCID extracted from message text if present
  -- useful when the function logs a resource reference inline
  REGEXP_EXTRACT(
    "data"->"message",
    'ocid1\.[a-z]+\.[a-z0-9]+\.[a-z]+\.[a-zA-Z0-9]+'
  ) AS "containerinstance_ocid",

  -- lifecycle_phase: captures structured lifecycle keywords from message
  -- helps distinguish cold starts, processing, and completion events
  REGEXP_EXTRACT(
    "data"->"message",
    '^(Processing|Initiating|Found|Start request completed[a-z ]*)'
  ) AS "lifecycle_phase"

FROM "oci_logging_raw"
WITH ('starting.position' = 'earliest')
WHERE "type" = 'com.oraclecloud.functions.application.functioninvoke'
  AND "data"->"message" IS NOT NULL;
