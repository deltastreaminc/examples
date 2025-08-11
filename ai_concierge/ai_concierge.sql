CREATE STREAM user_interaction_stream (
    event_type VARCHAR,
    user_id VARCHAR,
    event_ts_long BIGINT,
    content_id VARCHAR,
    search_query VARCHAR,
    duration_ms INT
) WITH ('topic' = 'user_interaction_stream', 'value.format' = 'json', 'timestamp' = 'event_ts_long');


-- Second, declare the Kafka topic for the content metadata.
-- This represents a changelog stream from a database, now populated by our Java app.
CREATE CHANGELOG content_metadata_cl (
    ts_long BIGINT,
    content_id VARCHAR,
    title VARCHAR,
    genres VARCHAR,
    PRIMARY KEY(content_id)
) WITH ('topic' = 'content_metadata', 'value.format' = 'json', 'timestamp' = 'ts_long');



CREATE STREAM enriched_user_interaction_stream
WITH
  ('kafka.topic.retention.ms' = '9272800000') AS
SELECT
  uis.event_type,
  uis.user_id,
  uis.event_ts_long,
  uis.content_id,
  uis.search_query,
  uis.duration_ms,
  cm.ts_long,
  cm.content_id AS cm_content_id,
  cm.title,
  cm.genres,
  -- A simple scoring model: viewing details is a stronger signal than a hover.
  CASE uis.event_type
    WHEN 'view_details' THEN 3
    WHEN 'hover' THEN 1
    ELSE 0
  END as weighted_interest_score
FROM
  user_interaction_stream AS uis
WITH
  ('starting.position' = 'earliest')
  -- A temporal join ensures that we always use the LATEST version of the metadata.
  JOIN content_metadata_cl AS cm
WITH
  ('source.idle.timeout.millis' = 1000) ON uis.content_id = cm.content_id
  -- We only look at events that signal content interest.
WHERE
  uis.event_type IN ('view_details', 'hover');




CREATE CHANGELOG windowed_session_stats
WITH
  ('kafka.topic.retention.ms' = '9272800000') AS
SELECT
  window_start AS w_start,
  UNIX_TIMESTAMP (
    CAST(window_start AS VARCHAR),
    'yyyy-MM-dd HH:mm:ss.SSS'
  ) * 1000 AS w_start_ux,
  window_end AS w_end,
  UNIX_TIMESTAMP (
    CAST(window_end AS VARCHAR),
    'yyyy-MM-dd HH:mm:ss.SSS'
  ) * 1000 AS w_end_ux,
  user_id,
  genres,
  SUM(weighted_interest_score) AS weighted_interest_score_sum,
  -- Count abandoned views in the window
  SUM(
    CASE
      WHEN event_type = 'view_details' THEN 1
      ELSE 0
    END
  ) as abandoned_views,
  -- Check for a play event in the window
  SUM(
    CASE
      WHEN event_type = 'play' THEN 1
      ELSE 0
    END
  ) > 0 as has_played_content
FROM
  HOP (
    enriched_user_interaction_stream,
    SIZE 5 MINUTE,
    ADVANCE BY 1 MINUTE
  )
WITH
  (
    'timestamp' = 'event_ts_long',
    'starting.position' = 'earliest'
  )
GROUP BY
  window_start,
  window_end,
  user_id,
  genres;



CREATE CHANGELOG windowed_session_stats_for_prompt
WITH
  ('kafka.topic.retention.ms' = '9272800000') AS
SELECT
  window_start,
  window_end AS w_end,
  UNIX_TIMESTAMP (
    CAST(window_start AS VARCHAR),
    'yyyy-MM-dd HH:mm:ss.SSS'
  ) * 1000 AS w_start_ux_new,
  w_start_ux,
  user_id,
  COUNT(*) AS cnt,
  LISTAGG (genres) AS genres_list,
  LISTAGG (CAST(weighted_interest_score_sum AS VARCHAR)) AS weighted_interest_score_sum_list,
  -- Count abandoned views in the window
  SUM(abandoned_views) as abandoned_views_in_window,
  -- Check for a play event in the window
  SUM(
    CASE
      WHEN has_played_content = TRUE THEN 1
      ELSE 0
    END
  ) as has_played_content_count
FROM
  TUMBLE (windowed_session_stats_stream, SIZE 1 MINUTE)
WITH
  (
    'timestamp' = 'w_start_ux',
    'starting.position' = 'earliest'
  )
GROUP BY
  window_start,
  window_end,
  w_start_ux,
  user_id;  

SELECT window_start, w_end, w_start_ux, user_id , 
-- This is where we construct the final, context-rich prompt for the LLM.
    call_gemini_explainer('User ' || user_id || ' seems indecisive. In the last 5 minutes, they have shown strong interest in the ' ||
    'different genres but have not played any content after viewing ' || CAST(abandoned_views_in_window AS VARCHAR) ||
    ' titles. Please generate a short, friendly, and enticing conversational prompt (max 2 sentences) to suggest a specific title from this genre.' ||
    ' Here are the genres list and their weighted interest score list in the same order in two lists: [' || CAST(genres_list AS VARCHAR) || '],[' ||
    CAST(weighted_interest_score_sum_list AS VARCHAR) || ']')
    AS llm_prompt
FROM windowed_session_stats_for_prompt --WITH ('starting.position' = 'earliest')
-- THE TRIGGERING LOGIC:
WHERE
    abandoned_views_in_window > 2
    AND has_played_content_count = 0;
