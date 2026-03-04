-- ============================================================
-- Step 2: Define the Raw Input Streams
--
-- These point at the OCI Streaming topics that Connector Hub
-- is writing to. They define the schema of the raw CloudEvent
-- JSON that OCI Logging produces.
--
-- The topic names must match what you configured in
-- Connector Hub. Update them if yours differ.
-- ============================================================


-- ------------------------------------------------------------
-- Raw OCI Audit Events
-- Receives audit log events from OCI Connector Hub
-- Source topic: set 'topic' to match your Connector Hub config
-- ------------------------------------------------------------
CREATE STREAM "oci_audit_raw" (
  "dataschema"  VARCHAR,
  "id"          VARCHAR,
  "specversion" VARCHAR,
  "time"        VARCHAR,
  "type"        VARCHAR,
  "source"      VARCHAR,

  "oracle" STRUCT<
    "compartmentid" VARCHAR,
    "ingestedtime"  VARCHAR,
    "loggroupid"    VARCHAR,
    "tenantid"      VARCHAR
  >,

  "data" STRUCT<
    "additionalDetails"  VARCHAR,
    "availabilityDomain" VARCHAR,
    "compartmentId"      VARCHAR,
    "compartmentName"    VARCHAR,
    "definedTags"        VARCHAR,
    "eventGroupingId"    VARCHAR,
    "eventName"          VARCHAR,
    "freeformTags"       VARCHAR,

    "identity" STRUCT<
      "authType"         VARCHAR,
      "callerId"         VARCHAR,
      "callerName"       VARCHAR,
      "consoleSessionId" VARCHAR,
      "credentials"      VARCHAR,
      "ipAddress"        VARCHAR,
      "principalId"      VARCHAR,
      "principalName"    VARCHAR,
      "tenantId"         VARCHAR,
      "userAgent"        VARCHAR
    >,

    "message" VARCHAR,

    "request" STRUCT<
      "action"  VARCHAR,
      "headers" STRUCT<
        "User-Agent"       ARRAY<VARCHAR>,
        "X-Forwarded-For"  ARRAY<VARCHAR>,
        "opc-request-id"   ARRAY<VARCHAR>
      >,
      "id"         VARCHAR,
      "parameters" VARCHAR,
      "path"       VARCHAR
    >,

    "resourceId" VARCHAR,

    "response" STRUCT<
      "headers"      VARCHAR,
      "message"      VARCHAR,
      "payload"      VARCHAR,
      "responseTime" VARCHAR,
      "status"       VARCHAR
    >,

    "stateChange" STRUCT<
      "current" STRUCT<
        "responseObject" VARCHAR
      >,
      "previous" STRUCT<
        "requestObject" VARCHAR
      >
    >
  >
)
WITH (
  'topic'        = '<OCI_AUDIT_TOPIC>',   -- e.g. 'oci-audit-raw'
  'store'        = 'oci_streaming',
  'value.format' = 'JSON'
);


-- ------------------------------------------------------------
-- Raw OCI Logging Events
-- Receives service/function log events from OCI Connector Hub
-- Source topic: set 'topic' to match your Connector Hub config
-- ------------------------------------------------------------
CREATE STREAM "oci_logging_raw" (
  "id"          VARCHAR,
  "time"        VARCHAR,
  "type"        VARCHAR,
  "source"      VARCHAR,
  "subject"     VARCHAR,
  "specversion" VARCHAR,

  "oracle" STRUCT<
    "compartmentid" VARCHAR,
    "tenantid"      VARCHAR,
    "ingestedtime"  VARCHAR,
    "loggroupid"    VARCHAR,
    "logid"         VARCHAR
  >,

  "data" STRUCT<
    "applicationId" VARCHAR,
    "functionId"    VARCHAR,
    "containerId"   VARCHAR,
    "message"       VARCHAR,
    "opcRequestId"  VARCHAR,
    "requestId"     VARCHAR,
    "src"           VARCHAR
  >
)
WITH (
  'topic'        = '<OCI_LOGGING_TOPIC>',  -- e.g. 'oci-logging-raw'
  'store'        = 'oci_streaming',
  'value.format' = 'JSON'
);
