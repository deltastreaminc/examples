-- Step 1: Create relations for the raw Kafka topics.

-- A STREAM for the high-velocity player actions.
CREATE STREAM player_actions_stream (
    match_id        VARCHAR,
    player_id       VARCHAR,
    event_timestamp BIGINT,
    action_type     VARCHAR,
    weapon         VARCHAR,
    target_id       VARCHAR,
    is_headshot     BOOLEAN,
    reaction_time_ms INTEGER
) WITH (
    'topic' = 'player_actions_kafka',
    'value.format' = 'json',
    'timestamp' = 'event_timestamp'
);

-- A TABLE for the slower-moving historical player data.
-- This stores the latest known stats for each player.
CREATE CHANGELOG player_historical_stats (
    player_id                 VARCHAR,
    update_timestamp         BIGINT,
    total_matches_played       INTEGER,
    historical_headshot_rate   DOUBLE,
    historical_accuracy       DOUBLE,
    PRIMARY KEY(player_id)
) WITH (
    'topic' = 'player_history_kafka',
    'value.format' = 'json',
    'timestamp' = 'update_timestamp'
);


-- Step 2: Enrich the live action stream with historical context.
-- We use a Temporal Join to add the player's history to every single action they take.
CREATE STREAM enriched_player_actions AS
SELECT
    pas.match_id,
    pas.player_id,
    pas.event_timestamp,
    pas.action_type,
    pas.weapon,
    pas.target_id,
    pas.is_headshot,
    pas.reaction_time_ms,
    phs.total_matches_played,
    phs.historical_headshot_rate,
    phs.historical_accuracy
FROM player_actions_stream AS pas
LEFT JOIN player_historical_stats AS phs WITH ('source.idle.timeout.millis' = 1000)
ON pas.playerId = phs.playerId;


-- Step 3: Apply pattern matching on the ENRICHED stream.
CREATE MATERIALIZED VIEW suspicious_aimbot_patterns AS
SELECT
  player_id,
  match_timestamp,
  suspicious_reaction_time,
  was_headshot,
  player_historical_hs_rate,
  player_matches_played
FROM
  enriched_player_actions MATCH_RECOGNIZE (
    PARTITION BY
      player_id
    ORDER BY
      event_timestamp MEASURES MATCH_ROWTIME () AS match_timestamp,
      L.reaction_time_ms AS suspicious_reaction_time,
      F.is_headshot AS was_headshot,
      -- Include the historical context in the output for the agent
      L.historical_headshot_rate AS player_historical_hs_rate,
      L.total_matches_played AS player_matches_played ONE ROW PER MATCH AFTER MATCH SKIP TO NEXT ROW
      -- The pattern remains the same: AIM -> LOCK_ON_TARGET -> FIRE
      PATTERN (A L + F)
      -- The DEFINE clause is now much more intelligent
      DEFINE A AS A.action_type = 'AIM',
      -- The lock-on is still inhumanly fast...
      L AS L.action_type = 'LOCK_ON_TARGET'
      AND L.reaction_time_ms < 20,
      -- ...and the final shot is a headshot FROM A PLAYER who historically has a low headshot rate.
      -- This helps ignore pros who might have very fast (but not inhuman) reactions.
      F AS F.action_type = 'FIRE'
      AND F.is_headshot = TRUE
      AND F.historical_headshot_rate < 0.25
  )
WITH
  ('timestamp' = 'event_timestamp');

