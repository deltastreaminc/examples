-- Step 1: Create STREAMS to represent the raw Kafka topics.
-- DeltaStream will read from these topics continuously.

CREATE STREAM flight_events (
    flight_id            VARCHAR,
    flight_status        VARCHAR,
    origin               VARCHAR,
    destination          VARCHAR,
    scheduled_departure  TIMESTAMP_LTZ,
    event_timestamp      TIMESTAMP_LTZ
) WITH (
    'topic' = 'flight_events',
    'value.format' = 'json',
    'timestamp' = 'event_timestamp'
);


CREATE STREAM booking_events (
    booking_id           VARCHAR,
    flight_id            VARCHAR,
    passenger_id         VARCHAR,
    seat                 VARCHAR,
    booking_timestamp    TIMESTAMP_LTZ
) WITH (
    'topic' = 'booking_events',
    'value.format' = 'json',
    'timestamp' = 'booking_timestamp'
);

-- For customer profiles, which is dimensional data (slowly changing),
-- we create a changelog stream first and then a TABLE.
-- The TABLE will store only the LATEST profile for each passenger_id.

CREATE CHANGELOG customer_profiles_changelog (
    passenger_id         VARCHAR,
    first_name           VARCHAR,
    last_name            VARCHAR,
    loyalty_tier         VARCHAR,
    preferences          STRUCT<seating VARCHAR>,
    update_timestamp     TIMESTAMP_LTZ,
    PRIMARY KEY(passenger_id)
) WITH (
    'topic' = 'customer_profiles',
    'value.format' = 'json',
    'timestamp' = 'update_timestamp'
);


-- Step 2: Create the final Materialized View.
-- This is the core of our real-time context generation. It joins the streams
-- and filters for high-value customers on disrupted flights.


CREATE STREAM enriched_booking_events AS
SELECT 
    booking_id,
    flight_id,
    be.passenger_id,
    seat,
    booking_timestamp,
    first_name,
    last_name,
    loyalty_tier,
    preferences
FROM booking_events be
LEFT JOIN customer_profiles_changelog cpc WITH ('source.idle.timeout.millis' = 1000)
ON be.passenger_id = cpc.passenger_id;


CREATE MATERIALIZED VIEW disrupted_premium_passengers AS
SELECT
        ebe.passenger_id,
        ebe.first_name || ' ' || ebe.last_name AS full_name,
        ebe.loyalty_tier,
        f.flight_id,
        f.flight_status AS flight_status,
        f.origin,
        f.destination,
        f.event_timestamp AS disruption_timestamp,
        ebe.preferences->seating AS seating_preference
    FROM flight_events AS f
    -- Join flights with their bookings.
    -- We use a temporal window to limit the state we need to keep.
    -- This assumes a booking happens reasonably close to a flight event.
    INNER JOIN enriched_booking_events AS ebe 
    WITHIN  1 DAY
    ON f.flight_id = ebe.flight_id
    WHERE
        -- We only care about disruptions
        f.flight_status IN ('CANCELED', 'DELAYED')
        AND
        -- We only care about our premium customers
        ebe.loyalty_tier IN ('PLATINUM', 'GOLD');
