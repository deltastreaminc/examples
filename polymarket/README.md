# Polymarket Trader Activity MV

This folder contains the SQL and scripts for Polymarket activity pipelines in
DeltaStream.

## Use Case

Build a validated DeltaStream-native enrichment path from Polymarket order fills
to Gamma market questions:

- maintain `token_id -> market_question` inside DeltaStream
- enrich `asset` token IDs in order fills using that mapping
- validate the enriched rows before adding any downstream activity calculations

This pipeline intentionally excludes `user_positions` and `user_balances`.

In the current working scope, the only Gamma field we care about is:

- `token_id -> market_question`

DeltaStream-managed Gamma relations are the primary enrichment path for this
project. The Java UDF remains available as a fallback tool, but it is too slow
for the general case and is not the main enrichment strategy.

## SQL Files

- `sql/01_gamma_markets_changelog.sql` - phase 1: raw Gamma changelog on `demo_pm_gamma_markets`
- `sql/02_gamma_token_pipeline.sql` - phase 2: Gamma token normalization into `token_id -> market_question`
- `sql/03_mv2_gamma_enriched_draft.sql` - phase 3: order source, changelog-join enrichment, and validation MV
- `sql/04_mv1_demo_earliest.sql` - historical order-only baseline pipeline
- `gamma-udf/` - Java scalar UDF project for on-demand Gamma enrichment

## Protected Source Topics

These topics are upstream source topics and must never be deleted, truncated, or
repurposed by this project:

- `demo_pm_orders_filled`
- `demo_pm_orders_matched`
- `demo_pm_gamma_markets`

Any derived or helper relations in this repo should write to separate sink
topics. Cleanup or teardown workflows must not target the protected source
topics above.

## Current vs Draft

Current deployed order-fill source:

- `sql/04_mv1_demo_earliest.sql` defines the original fill pipeline over
  `pm_orders_filled_s`

Validated replacement:

- `sql/03_mv2_gamma_enriched_draft.sql` defines the current changelog-join
  validation pipeline for order enrichment

## Execution Order

Run the pipeline in phases so Gamma data is ready before any order enrichment
begins:

1. `sql/01_gamma_markets_changelog.sql`
   - creates `pm_gamma_markets_cl`
2. `sql/02_gamma_token_pipeline.sql`
   - declares `pm_gamma_markets_s` as the replayable raw Gamma stream used for flattening
   - builds `pm_gamma_token_question_flat_s`
   - builds `pm_gamma_token_question_cl`
3. Validate Gamma relations are populated
4. `sql/03_mv2_gamma_enriched_draft.sql`
   - creates `pm_orders_filled_s`
   - creates `pm_orders_filled_by_id_cl`
   - creates `pm_orders_filled_enriched_activity_cl`
   - creates `pm_orders_filled_enriched_validation_mv`

Do not add downstream activity calculations until the validation MV shows the
expected Gamma-enriched rows.

## Current Direction

The current recommended design is DeltaStream-first:

1. Use DeltaStream-managed Gamma relations for the `token_id -> market_question`
   mapping.
2. Declare the raw `demo_pm_orders_filled` topic as an upsert changelog keyed
   by fill id.
3. Join the two changelogs in DeltaStream.

The Java UDF remains available as a fallback tool, but it is too slow for the
general case and is not the primary enrichment path.

## Historical Draft Intent

The current validation pipeline separates concerns into distinct relations:

1. `pm_gamma_markets_cl`
   - raw Gamma changelog keyed by `conditionId`
2. `pm_gamma_token_question_cl`
   - canonical `token_id -> market_question` changelog
3. `pm_orders_filled_by_id_cl`
   - order_filled changelog keyed by fill id, declared directly on the raw topic
4. `pm_orders_filled_enriched_validation_mv`
   - validation-only MV to inspect enriched rows before downstream calculations

## Pipeline Purpose

The current pipeline is intended to prove that DeltaStream can enrich
low-level Polymarket fill events with the Gamma market question using a native
changelog join.

At a high level:

- the raw fills tell us **who traded what token, when, and how much**
- the Gamma data tells us **what market question that token belongs to**
- the validation MV combines those two sources into **reviewable enriched fill rows**

The immediate validation question is simpler:

- does a given `asset` token id resolve to the expected `market_question`?

The validation MV is intentionally narrower than the eventual activity view.
It exists to verify the enrichment path before any 1-hour aggregations are
added.

## Data Flow

Current recommended flow:

1. Read Goldsky `order_filled` events from topic `demo_pm_orders_filled` in
   store `warpstream`.
2. Maintain `pm_gamma_markets_cl` over the raw Gamma topic.
3. Derive `pm_gamma_token_question_cl` as the canonical `token_id -> market_question`
   DeltaStream helper.
4. Declare `pm_orders_filled_by_id_cl` directly on the raw order topic as an
   upsert changelog keyed by fill id.
5. Validate the result in `pm_orders_filled_enriched_validation_mv`, which reads
   directly from the changelog join, before any
   downstream activity calculations.

## Current DeltaStream Validation Notes

- `pm_gamma_markets_cl` creation succeeded in the live `polymarket.public`
  workspace.
- Direct `CREATE STREAM ... AS SELECT ... FROM pm_gamma_markets_cl CROSS JOIN
  UNNEST(...)` was rejected by DeltaStream with:
  `Invalid sink type detected for CREATE_STREAM_AS statement: Expected CHANGELOG but got STREAM.`
- Direct stream-changelog temporal joins from `pm_orders_filled_s` to Gamma token
  changelogs produced rows but all Gamma fields were empty during replay.
- A changelog-to-changelog join is the current working direction and has
  produced matched enriched rows in live validation (`rick_orders_gamma_changelog_join_mv`).
- Building a separate derived order helper topic introduced Kafka sink timeout
  failures. The current checked-in design instead declares the raw
  `demo_pm_orders_filled` topic directly as the upsert order changelog used for
  the join.
- `CREATE FUNCTION_SOURCE` still needs a client path that can successfully upload
  the local jar. The SQL is kept in the repo, but registration should be treated
  as a manual prereq until that path is confirmed.

## Validation Output

The current validation target is:

- `pm_orders_filled_enriched_validation_mv`

This should show one row per matched fill id with:

- `id`
- `user_id`
- `asset`
- `amount_usdc`
- `amount_shares`
- `price`
- `side`
- `fee`
- `gamma_token_id`
- `market_question`
- `market_updated_at`

## Common Queries

Top assets by activity:

```sql
SELECT
  asset,
  MAX(fills_count_1h) AS fills_count_1h,
  MAX(filled_usdc_1h) AS filled_usdc_1h
FROM polymarket.public.polymarket_trader_activity_mv
GROUP BY asset
ORDER BY fills_count_1h DESC, filled_usdc_1h DESC
LIMIT 10;
```

Top wallet/asset pairs:

```sql
SELECT
  user_id,
  asset,
  fills_count_1h,
  filled_usdc_1h,
  event_time_ms
FROM polymarket.public.polymarket_trader_activity_mv
ORDER BY fills_count_1h DESC, filled_usdc_1h DESC
LIMIT 10;
```

## Agent Questions

The final materialized view is meant to support agent-facing questions that can
be answered directly from one current-state row per active `user_id + asset`
pair.

Examples:

- Which wallet/asset pairs are the most active right now?
- Which active pairs have the largest net buy pressure in the last hour?
- Which wallets are aggressively selling a specific market outcome?
- What market question and outcome label correspond to this token id?
- Which active pairs are trading in a given event or league?
- Which markets currently have the highest concentration of activity?
- For a specific wallet, what assets is it actively trading right now?
- What was the latest side and latest price for a wallet/asset pair?
- Which active pairs are tagged `high_activity` right now?
- Which markets with a specific `sports_market_type` or `line` are seeing the most action?

Fields expected to be useful for agents include:

- identity/state: `user_id`, `asset`, `user_asset_key`
- market context: `condition_id`, `market_question`, `market_slug`,
  `outcome_label`, `event_title`, `event_league`, `sports_market_type`, `line`
- current activity: `fills_count_1h`, `filled_usdc_1h`, `filled_shares_1h`,
  `buy_shares_1h`, `sell_shares_1h`, `net_shares_1h`, `fee_total_1h`,
  `activity_flag`
- latest context: `latest_side`, `latest_price`, `latest_block_timestamp`

## Query-Time UDF Enrichment

The Java scalar UDF in `gamma-udf/` is the fallback enrichment path.

The UDF:

- accepts a single `asset` token id
- calls the Gamma API on demand
- caches results for 24 hours in process
- returns the question string directly
- returns `NULL` on miss or error

Registration pattern:

```sql
CREATE FUNCTION_SOURCE gamma_udf_src
WITH (
  'file' = '/absolute/path/to/gamma-udf/target/gamma-udf-0.1.0-SNAPSHOT-all.jar',
  'description' = 'Polymarket Gamma question lookup UDF'
);

CREATE FUNCTION gamma_question(asset VARCHAR)
RETURNS VARCHAR
LANGUAGE JAVA
WITH (
  'source.name' = 'gamma_udf_src',
  'class.name' = 'polymarket.udf.GammaQuestionLookup',
  'egress.allow.uris' = 'gamma-api.polymarket.com:443'
);
```

Example usage:

```sql
SELECT
  asset,
  gamma_question(asset) AS question
FROM polymarket.public.pm_orders_filled_s
LIMIT 10;
```

Recommended usage in the DeltaStream pipeline:

```sql
COALESCE(g.market_question, gamma_question(o.asset)) AS market_question
```

Use the UDF only for `market_question` fallback. The rest of the market fields
should continue to come from `pm_gamma_tokens_cl` so the main enrichment stays
inside DeltaStream.

## Metadata Enrichment Script

- `fetch_market_metadata.py`

Input: token IDs from MV `asset` column.

Example:

```bash
python3 fetch_market_metadata.py --assets-csv top_assets.csv --format json
```

The script queries:

- `https://clob.polymarket.com/markets-by-token/{token_id}`
- `https://gamma-api.polymarket.com/markets?clob_token_ids={token_id}`
- fallback: `.../markets?condition_ids={condition_id}`

The Python enrichment script is still useful as the reference implementation of
the lookup logic. The Java UDF in `gamma-udf/` is intended to follow the same
lookup order and outcome-resolution approach.

## Notes

- All query inputs are configured from earliest.
- Relation names do not use `demo_`; backing topic names may.
- If DeltaStream query lifecycle gets stuck in `terminate_requested`, cycling
  `STOP/START COMPUTE_POOL polymarket_cp` may be needed.
