-- Step 1: Define Datastore and raw data streams from Kafka. For simplicity, we assume the default store, database and namespace/schema are set correctly.

CREATE STREAM onchain_transactions (
    tx_hash VARCHAR, block_number BIGINT, event_timestamp BIGINT,
    from_address VARCHAR, to_address VARCHAR, tx_token VARCHAR, tx_amount DOUBLE
) WITH ('topic' = 'onchain_transactions', 'value.format' = 'json');

CREATE STREAM dex_prices (
    event_timestamp BIGINT, token_pair VARCHAR, price DOUBLE, join_helper VARCHAR
) WITH ('topic' = 'dex_prices', 'value.format' = 'json');

CREATE STREAM mempool_data (
    event_timestamp BIGINT, block_number BIGINT, avg_gas_price_gwei INTEGER
) WITH ('topic' = 'mempool_data', 'value.format' = 'json');


-- Step 2: Create intermediate streams to identify key atomic events.

-- A stream of very large loans from known flash loan providers.
CREATE STREAM flash_loans AS
SELECT from_address AS provider, to_address AS attacker, tx_token, tx_amount, block_number, event_timestamp
FROM onchain_transactions WITH ('starting.position' = 'earliest')
WHERE
    from_address = '0xA9754f1D6516a24A413148Db4534A4684344C1fE' -- Simulated Aave Pool
    AND tx_amount > 1000000; -- Loan amount over $1M



-- A stream of very large repayments back to the providers.
CREATE STREAM loan_repayments AS
SELECT from_address AS attacker, to_address AS provider, tx_token, tx_amount, block_number, event_timestamp
FROM onchain_transactions WITH ('starting.position' = 'earliest')
WHERE
    to_address = '0xA9754f1D6516a24A413148Db4534A4684344C1fE'
    AND tx_amount > 1000000;


-- Step 3: Detect the core attack pattern by joining loans and repayments.
-- This is the crucial step: finding a loan and repayment by the same actor in a tight window.
CREATE STREAM potential_flash_loan_attacks AS
SELECT
    l.attacker, l.tx_token, l.tx_amount, l.block_number, l.event_timestamp AS attack_timestamp, 'A' AS pfla_join_helper
FROM flash_loans AS l WITH ('timestamp' = 'event_timestamp', 'starting.position' = 'earliest')
JOIN loan_repayments AS r WITH ('timestamp' = 'event_timestamp', 'starting.position' = 'earliest')
    WITHIN 24 HOURS
    -- Join on the attacker's address
    ON l.attacker = r.attacker
    -- The repayment must happen within 2 blocks of the loan, a key flash loan indicator
    WHERE r.block_number BETWEEN l.block_number AND l.block_number + 2;


-- Step 4: Contextualize the attack with market data to create a final trigger.
-- This enriches the detected attack with surrounding on-chain activity. We do this with two join queries.
CREATE STREAM pfla_dex_sentinel_triggers AS
SELECT
    p.attacker, p.tx_token, p.tx_amount, p.block_number, p.attack_timestamp,
    d.price AS price_at_attack
FROM potential_flash_loan_attacks AS p WITH ('timestamp' = 'attack_timestamp', 'starting.position' = 'earliest')
LEFT JOIN dex_prices AS d WITH ('timestamp' = 'event_timestamp', 'starting.position' = 'earliest')
  WITHIN 2 SECONDS
  ON p.pfla_join_helper = d.join_helper
  ;


CREATE STREAM sentinel_triggers AS
SELECT
    p.attacker, p.tx_token, p.tx_amount, p.block_number, p.attack_timestamp,
    p.price_at_attack,
    m.avg_gas_price_gwei AS gas_at_attack
FROM pfla_dex_sentinel_triggers AS p WITH ('timestamp' = 'attack_timestamp', 'starting.position' = 'earliest')
LEFT JOIN mempool_data AS m WITH ('timestamp' = 'event_timestamp', 'starting.position' = 'earliest')
WITHIN 24 HOURS
    ON m.block_number = p.block_number
    ;



-- Step 5: Create the final, AI-assessed risk stream.
-- This assumes a built-in UDF `call_sentinel_agent(VARCHAR)` that sends a prompt to a GenAI model.
CREATE STREAM ai_risk_assessments AS
SELECT
    attacker,
    tx_token,
    tx_amount,
    -- Use JSON_VALUE to parse the structured JSON response from the GenAI agent
        call_gemini_explainer(
            -- This is sophisticated prompt engineering done directly in SQL
            'You are an autonomous on-chain risk sentinel for a DeFi protocol. Analyze the following real-time, correlated event data for signs of a flash loan-based price manipulation attack. ' ||
            'The attack signature is a large loan and repayment within the same transaction, correlated with anomalous market activity. ' ||
            'Based on the data, provide a structured JSON response with three keys: "risk_level" (CRITICAL, HIGH, MEDIUM, LOW), "summary" (a plain-English explanation of the event for a human analyst), and "recommended_actions" (a list of 2-3 immediate, automated actions). ' ||
            '--- Correlated Event Data --- ' ||
            'Attacker Address: ' || attacker || ', ' ||
            'Flash Loan Token: ' || tx_token || ', ' ||
            'Flash Loan Amount: ' || CAST(tx_amount AS VARCHAR) || ', ' ||
            'Block Number: ' || CAST(block_number AS VARCHAR) || ', ' ||
            'DEX Price at Attack: ' || CAST(price_at_attack AS VARCHAR) || ', ' ||
            'Gas Price (Gwei) at Attack: ' || CAST(gas_at_attack AS VARCHAR)   
    ) AS genai_response
FROM sentinel_triggers WITH ('starting.position' = 'earliest');

-- To monitor the final output of your Sentinel Agent:
-- SELECT * FROM ai_risk_assessments;
