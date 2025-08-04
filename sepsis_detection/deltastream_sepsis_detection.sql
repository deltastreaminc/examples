
-- Create a Stream to represent the raw vital signs flowing through Kafka.
CREATE STREAM bio_vitals_stream (
  patient_id VARCHAR,
  event_timestamp TIMESTAMP_LTZ(6),
  heart_rate_bpm INT,
  respiratory_rate_rpm INT,
  skin_temp_c DECIMAL(5, 2),
  activity_level VARCHAR
) WITH (
  'topic' = 'bio_vitals',
  'value.format' = 'json',
  'timestamp' = 'event_timestamp'
);


CREATE CHANGELOG vital_features AS 
SELECT
    patient_id,
    window_start,
    window_end,
    AVG(heart_rate_bpm) AS avg_hr_15m,
    STDDEV(heart_rate_bpm) AS stddev_hr_15m,
    AVG(respiratory_rate_rpm) AS avg_rr_15m,
    MAX(skin_temp_c) AS max_temp_c_15m
  FROM TUMBLE(bio_vitals_stream, SIZE 15 MINUTE) 
  WITH
  (
    'starting.position' = 'earliest'
  )
  GROUP BY
    patient_id, window_start, window_end;


CREATE CHANGELOG llm_input AS 
SELECT
    patient_id,
    window_start,
    window_end,
    -- Create a detailed prompt string to send to the Gemini UDF
    'Analyze the following patient vitals for sepsis risk and respond with a JSON object containing "risk_score" and "justification". Vitals: ' ||
    'avg_hr_15m=' || CAST(avg_hr_15m AS VARCHAR) || ', ' ||
    'stddev_hr_15m=' || CAST(stddev_hr_15m AS VARCHAR) || ', ' ||
    'avg_rr_15m=' || CAST(avg_rr_15m AS VARCHAR) || ', ' ||
    'max_temp_c_15m=' || CAST(max_temp_c_15m AS VARCHAR) || '. Make sure the returned JSON starts with { and ends with } and is parsable without requiring any changes.' AS prompt
  FROM vital_features  WITH
  (
    'starting.position' = 'earliest'
  );



CREATE CHANGELOG patient_sepsis_alerts AS 
  SELECT
  patient_id,
  window_start,
  window_end,
  -- Parse the 'risk_score' field from the JSON string returned by the UDF
  call_gemini_explainer(prompt) AS json_response
FROM llm_input   
WITH
(
    'starting.position' = 'earliest'
);


SELECT
  patient_id,
  window_end,
  TRIM(LEADING '```json' FROM json_response) 
  -- Parse the 'risk_score' field from the JSON string returned by the UDF
  JSON_VALUE(
    json_response,
    '$.risk_score'
  ) AS sepsis_risk_score,
  -- Parse the 'justification' field from the JSON string
  JSON_VALUE(
    call_gemini_explainer(prompt),
    '$.justification'
  ) AS justification
FROM llm_input;
