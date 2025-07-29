-- Stream defined on the Kafka topic ingesting Okta logs
CREATE STREAM okta_logs_stream (
    event_timestamp BIGINT, user_email VARCHAR, event_type VARCHAR,
    outcome VARCHAR, ip_address VARCHAR, country VARCHAR, is_suspicious BOOLEAN
) WITH ('topic' = 'siem_okta_logs', 'value.format' = 'json', 'timestamp' = 'event_timestamp');

-- Stream defined on the Kafka topic ingesting Zscalar logs
CREATE STREAM zscaler_logs_stream (
    event_timestamp BIGINT, "user" VARCHAR, "action" VARCHAR,
    url VARCHAR, file_name VARCHAR, file_size_bytes INTEGER
) WITH ('topic' = 'siem_zscaler_logs', 'value.format' = 'json', 'timestamp' = 'event_timestamp');

-- Stream defined on the Kafka topic ingesting CrowdStrike logs
CREATE STREAM crowdstrike_alerts_stream (
    event_timestamp BIGINT, user_email VARCHAR, detection_name VARCHAR,
    severity VARCHAR, file_hash_sha256 VARCHAR, file_name VARCHAR, action_taken VARCHAR
) WITH ('topic' = 'siem_crowdstrike_alerts', 'value.format' = 'json', 'timestamp' = 'event_timestamp');


-- Corelate Okta, Zscalar and CrowdStrike events by joining the streams with 5 minutes window
CREATE STREAM correlated_okta_zscaler AS SELECT
    o.user_email, o.event_timestamp AS login_timestamp, o.ip_address, o.country, o.is_suspicious, z.url AS downloaded_url, z.file_name AS downloaded_file
FROM okta_logs_stream AS o 
JOIN zscaler_logs_stream AS z 
WITHIN 5 MINUTES ON o.user_email = z."user" 
WHERE o.is_suspicious = true;


CREATE STREAM correlated_security_incidents AS SELECT
    coz.user_email, coz.login_timestamp, coz.ip_address, coz.country, coz.downloaded_url, coz.downloaded_file, cs.detection_name AS malware_name, cs.severity AS malware_severity, cs.action_taken AS edr_action
FROM correlated_okta_zscaler AS coz 
JOIN crowdstrike_alerts_stream AS cs 
WITHIN 5 MINUTES ON coz.user_email = cs.user_email
WHERE coz.downloaded_file = cs.file_name AND cs.severity = 'CRITICAL';



CREATE STREAM ai_triaged_alerts AS SELECT
    *, 
    call_gemini_explainer(
        -- Concatenate strings and column values to build the full prompt
        'Analyze the following correlated security incident and return a single, valid JSON object with two keys: "summary" and "priority". Priority must be one of: CRITICAL, HIGH, MEDIUM, LOW. Incident Details: ' ||
        'User Email: ' || user_email || ', ' ||
        'Source IP Address: ' || ip_address || ', ' ||
        'Source Country: ' || country || ', ' ||
        'Downloaded URL: ' || downloaded_url || ', ' ||
        'Downloaded File Name: ' || downloaded_file || ', ' ||
        'Malware Detected: ' || malware_name || ', ' ||
        'Malware Severity: ' || malware_severity || ', ' ||
        'EDR Action Taken: ' || edr_action
    ) AS gemini_response_json 
FROM correlated_security_incidents;


