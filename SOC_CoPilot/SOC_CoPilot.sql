-- Auth events
CREATE STREAM securitydb.public.auth_events (
  event_timestamp BIGINT,
  user_id         VARCHAR,
  src_ip          VARCHAR,
  location        VARCHAR,
  device_id       VARCHAR,
  outcome         VARCHAR,
  mfa_used        BOOLEAN
) WITH (
  'topic'        = 'cyber_auth_events',
  'value.format' = 'json',
  'timestamp'    = 'event_timestamp'
);

-- Network flows
CREATE STREAM securitydb.public.network_flows (
  event_timestamp BIGINT,
  src_ip          VARCHAR,
  dest_ip         VARCHAR,
  dest_port       INT,
  protocol        VARCHAR,
  bytes_sent      BIGINT
) WITH (
  'topic'        = 'cyber_network_flows',
  'value.format' = 'json',
  'timestamp'    = 'event_timestamp'
);

-- IDS alerts
CREATE STREAM securitydb.public.ids_alerts (
  event_timestamp BIGINT,
  src_ip          VARCHAR,
  signature       VARCHAR,
  severity        VARCHAR
) WITH (
  'topic'        = 'cyber_ids_alerts',
  'value.format' = 'json',
  'timestamp'    = 'event_timestamp'
);


-- Join auth + flows on src_ip within a small time bound,
-- then left-join IDS alerts for the same src_ip window.

CREATE STREAM securitydb.public.auth_flow_enriched
WITH ('kafka.topic.retention.ms' = '604800000')  -- 7 days, tweak as needed
AS
SELECT
  a.event_timestamp                      AS event_timestamp,
  a.user_id                              AS user_id,
  a.src_ip                               AS src_ip,
  a.location                             AS location,
  a.device_id                            AS device_id,
  a.outcome                              AS outcome,
  a.mfa_used                             AS mfa_used,
  f.dest_ip                              AS dest_ip,
  f.dest_port                            AS dest_port,
  f.protocol                             AS protocol,
  f.bytes_sent                           AS bytes_sent
FROM securitydb.public.auth_events AS a
  WITH ('timestamp' = 'event_timestamp')
JOIN securitydb.public.network_flows AS f
  WITH ('timestamp' = 'event_timestamp')
WITHIN 30 SECONDS
ON a.src_ip = f.src_ip;

CREATE STREAM securitydb.public.security_events_enriched
WITH ('kafka.topic.retention.ms' = '604800000')
AS
SELECT
  e.event_timestamp                      AS event_timestamp,
  e.user_id                              AS user_id,
  e.src_ip                               AS src_ip,
  e.location                             AS location,
  e.device_id                            AS device_id,
  e.outcome                              AS outcome,
  e.mfa_used                             AS mfa_used,
  e.dest_ip                              AS dest_ip,
  e.dest_port                            AS dest_port,
  e.protocol                             AS protocol,
  e.bytes_sent                           AS bytes_sent,
  ia.signature                           AS ids_signature,
  ia.severity                            AS ids_severity
FROM securitydb.public.auth_flow_enriched AS e
LEFT JOIN securitydb.public.ids_alerts AS ia
  WITHIN 30 SECONDS
  ON e.src_ip = ia.src_ip;


-- The real-time context as a real-time Materialized View in DeltaStream
CREATE MATERIALIZED VIEW securitydb.public.security_risk_context_mv AS
SELECT
  window_start,
  window_end,
  user_id,
  src_ip,

  -- 5m auth failure stats
  SUM(
    CASE WHEN outcome = 'FAIL' THEN 1 ELSE 0 END
  ) AS failed_logins_5m,
  COUNT(*) AS total_auth_events_5m,

  -- MFA usage
  SUM(
    CASE WHEN mfa_used THEN 1 ELSE 0 END
  ) AS mfa_success_count_5m,

  -- Network exfil indicators
  SUM(bytes_sent) AS total_bytes_sent_5m,

  -- IDS alert counts
  SUM(
    CASE WHEN ids_severity IN ('HIGH','CRITICAL') THEN 1 ELSE 0 END
  ) AS high_critical_alerts_5m,
  COUNT(ids_signature) AS total_ids_alerts_5m,

  -- Simple rule-based risk score (you can swap in a UDF, etc.)
  (
      10 * SUM(CASE WHEN outcome = 'FAIL' THEN 1 ELSE 0 END)
    +  5 * SUM(CASE WHEN ids_severity IN ('HIGH','CRITICAL') THEN 1 ELSE 0 END)
    +  CASE WHEN SUM(bytes_sent) > 50000000 THEN 20 ELSE 0 END  -- > ~50MB
  ) AS risk_score_5m

FROM HOP(
  securitydb.public.security_events_enriched,
  SIZE  5 MINUTE,
  ADVANCE BY 30 SECOND
) WITH (
  'timestamp'          = 'event_timestamp',
  'starting.position'  = 'earliest'
)
GROUP BY
  window_start,
  window_end,
  user_id,
  src_ip;
