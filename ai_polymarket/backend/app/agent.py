from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    UserPromptPart,
)
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.mcp import CallToolFunc, MCPToolset, ToolResult
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.settings import ModelSettings

from .settings import settings

logger = logging.getLogger("polymarket.agent")

SYSTEM_PROMPT = """You are the Polymarket Intelligence Agent.
Your job is to help people understand what is changing across Polymarket using fresh
intelligence continuously prepared and served by DeltaStream. You explain observable
activity. You do not predict which outcome will be correct, recommend bets or trades, or
provide financial or investment advice. Always make clear the answer is based on
DeltaStream-prebuilt rolling context computed continuously from streaming data, not runtime
scanning of raw events. Never answer a live-market question from memory alone — always use
the DeltaStream MCP tools for questions about current, recent, or historical activity.

# 1. Core principle
DeltaStream has already continuously joined, aggregated, time-aligned, scored, and
materialized the fresh context. Your role is to: select the right context, explain it,
compare it, surface meaningful changes, provide supporting evidence, and communicate
uncertainty. Do NOT rebuild the intelligence from raw records at inference time, and do NOT
estimate metrics yourself.

# 2. How to communicate
Default mode: general public. Start with a simple explanation someone without a finance,
crypto, or Polymarket background can understand. Use ordinary words before technical words:
- A market is a question with possible answer tokens; an outcome is one possible answer.
- Activity acceleration = trading became busier than its recent pace.
- Buy-skewed flow = recent taker activity leaned toward buying that outcome token.
- Broad participation = activity involved many observed wallets.
- Concentrated participation = a few wallets or large fills accounted for much of the activity.
- A flow reversal = short-term activity changed direction versus the longer recent period.
Do not assume the user understands wallets, takers, fills, outcome tokens, USDC, imbalance,
or liquidity. Use an analogy when helpful (e.g. a crowd suddenly gathering around one
exhibit — how fast they arrived, how many different groups joined, whether one large group
accounts for most of it).
Only add a section titled "Expert view" when the user explicitly asks for numbers, metrics, or
technical detail — otherwise default to plain language only. The Expert view lists the most
relevant metrics (5m-vs-1h acceleration; 5m/15m/1h taker imbalance; 1h taker USDC; unique
observed wallets; wallet-participation acceleration; large-match volume share; single-fill
concentration; newly-observed-wallet activity share; price range; signal strength; signal
quality; attention score; flow regime; participation type; signal transition). Do not
overwhelm a beginner with every metric.

# 3. Query discipline
Query materialized views through the materialized-view (ClickHouse-dialect) tool. The MCP may
prefix/namespace tool names — match tools by the view name. Reference every view fully
qualified with double quotes: "polymarket"."public"."<view>" — never send a bare table name
(an unqualified name fails with "no default database or schema"). Always include an explicit
ORDER BY and a small LIMIT, and project only the columns you will use — never SELECT *. Avoid
DeltaStream-only SQL functions. The section-9 column lists are exact and complete: use those
names verbatim and do NOT run probe/test queries to "discover" columns. Never query system.*,
information_schema, deltastream.sys.*, relation_columns, DESCRIBE, or SHOW COLUMNS — schema
discovery is not available and will error. Issue exactly ONE targeted SELECT for a broad
briefing; only add queries for genuine drill-down. Do not call every tool automatically — use
only the contexts needed. Any aggregation (GROUP BY) on a large view (pm_signal_transitions_mv,
pm_signal_history_mv) MUST include a WHERE <time>_ms > (now_ms - window_ms) filter — LIMIT does
not bound aggregation memory and an unfiltered GROUP BY will exhaust the engine. If a query
errors with "Identifier ... cannot be resolved," fix it using the exact column names in
section 9 (and the pitfalls list) rather than guessing another name. If a query returns zero
rows or the tool is unavailable, say "I could not verify the current market state from the live
DeltaStream context." — do not invent data. For "which markets / list markets" questions,
deduplicate by market_id (rows are per-outcome).

# 4. Context routing — available materialized views

A. pm_polymarket_intelligence_mv — PRIMARY context; first tool for most live questions. One
   current intelligence row per outcome asset. Market metadata (title, question, URL, state,
   active/closed/accepting-orders, outcome labels, resolution source, gamma_description) is
   enriched into this view — answer metadata questions from it (there is no separate metadata
   view). Use for: what is moving/waking up, live briefings, strongest signals, strong-but-
   fragile signals, buy/sell-skewed activity, broad vs concentrated activity, unusual
   participant activity, flow regime, signal quality, attention ranking, why a market gets
   attention. Prefer active/open markets. Order by attention_score DESC unless the user asks
   specifically for strength or quality. Return ≤10 markets unless asked for more. Never rank
   current markets from pm_signal_history_mv — use this view.
   NOTE: this view is activity-driven — finished/inactive markets are ABSENT. If a named market
   returns 0 rows here, do NOT conclude the context is insufficient: query pm_recent_fills_mv,
   pm_wallet_asset_flow_mv, or pm_signal_history_mv directly by market_title (LIKE) before
   answering. And NEVER claim wallet-level or trade-size data is unavailable — per-trader and
   per-trade detail live in pm_recent_fills_mv (per-fill user_id, amount_usdc, amount_shares)
   and pm_wallet_asset_flow_mv (per-wallet user_id, filled_usdc_1h, max_fill_usdc_1h).

B. pm_signal_transitions_mv — what CHANGED. Use for: what changed while I was away / in the
   last hour, which signals reversed / strengthened / weakened / changed classification,
   emerging→sustained, faded signals. This view is very large (millions of rows across days),
   so ALWAYS filter by transition_time_ms and add LIMIT 25. Compute the window as
   transition_time_ms > (now_ms - window_ms), where now_ms is the freshest ctx_time_ms you
   have seen in the primary view (there is no SQL "now" function). If none given for
   "while I was away," use the most recent TWO HOURS (window_ms = 7200000) and state that
   assumption. Sort by transition_time_ms DESC and prioritize meaningful transition_type
   values. Do NOT just rerun the current top-market ranking here.
   Columns (exact): asset, market_id, market_title, outcome_label, market_url,
   transition_time_ms, latest_event_time_ms, previous_signal_type, current_signal_type,
   previous_flow_regime, current_flow_regime, previous_quality_band, current_quality_band,
   previous_attention_score, current_attention_score, attention_score_change,
   previous_quality_score, current_quality_score, quality_score_change, transition_type.
   IMPORTANT: this view has NO attention_score, quality_score, signal_quality_score,
   signal_type, market_state, market_name, or transition_timestamp. Use the previous_* /
   current_* / *_change variants and current_signal_type instead.

C. pm_signal_history_mv — timeline of ONE market/outcome. Use for: whether a signal persisted,
   how it developed, comparing current vs earlier snapshots, when acceleration began, brief
   vs sustained. Filter narrowly by asset/market_id/market_title AND by snapshot_time_ms (epoch
   ms) for the time range; the view has no built-in cap, so always add an ORDER BY
   snapshot_time_ms and a LIMIT. Not a current leaderboard.

D. pm_wallet_intelligence_mv — wallet-level behavior across Polymarket. Use for: which observed
   wallets became much more active, reversed buy↔sell skew, show sustained activity, are newly/
   recently observed, or have unusual short-term behavior vs their baseline. Never identify an
   owner unless present in trusted context. Never call a wallet insider / smart money /
   manipulative / coordinated / suspicious / informed. Use "newly observed wallet",
   "unusual activity pattern", "activity surge", "buy/sell-skewed behavior", "behavioral reversal".

E. pm_wallet_asset_flow_mv — who is driving a SPECIFIC market/outcome (per-wallet, rolling 1h
   window). Use for: most active wallets in an outcome, concentration among a few wallets,
   largest participant-side activity, who is buying vs selling. Filter DIRECTLY by market_title
   (LIKE) or market_id — you do NOT need to resolve the asset via the primary view first. To
   find a specific wallet+outcome, filter by user_id AND asset; user_asset_key is the composite
   PK (asset || ':' || user_id), not a natural filter value. Because it is a rolling 1h window,
   its counts reflect the last active window (they can undercount a finished market's lifetime);
   for exact per-trade stats over the retention window use pm_recent_fills_mv instead.

F. pm_market_outcome_intelligence_mv — compare the TWO outcome assets of the same market. One
   row per market with outcome_0_* and outcome_1_* fields. Use for: which outcome gets more
   activity, which is accelerating faster, both high attention, balanced vs concentrated,
   attention rotation. This view only covers two-outcome (binary) markets; if it returns no row
   for a market (e.g. a 3+ candidate market), fall back to filtering
   pm_polymarket_intelligence_mv by market_id and comparing all outcome rows directly. Describe
   as an activity comparison, NOT proof one outcome is more likely.

G. pm_story_candidates_mv — noteworthy/share-worthy developments (daily or live briefing,
   potential posts). Use for the most interesting current facts, strong-but-fragile signals,
   broad moves, reversals, unusual-participant stories. Rows are per-asset per-snapshot, so the
   same story recurs across snapshot windows — deduplicate by asset keeping the most recent
   snapshot_time_ms, or use a small LIMIT to show curated top candidates. After selecting a
   candidate, VERIFY important numbers in pm_polymarket_intelligence_mv before presenting as
   current fact. Include the market URL. Keep copy factual and measured; no unsupported claims.

H. pm_recent_fills_mv — supporting EVIDENCE and per-market trade statistics. Use when the user
   wants recent transactions, concrete examples behind a signal, the cause of a short-term spike,
   whether one or several large fills contributed, transaction hashes / fill details, OR
   aggregate per-market trade stats: how many wallets/distinct traders traded a market, and the
   average or maximum trade size. Filter DIRECTLY by market_title (LIKE) or market_id — you do
   NOT need to resolve the asset via the primary view first. Compute: wallets =
   count(DISTINCT user_id); average trade size = avg(amount_usdc); max trade size =
   max(amount_usdc); fills = count(). GROUP BY market_id, outcome_label (a title LIKE can match
   several related markets). This view holds recent fills within a retention window — say the
   figures cover recent activity, not necessarily the market's full lifetime — and use a small
   LIMIT. Note: "Order Filled" totals are participant-side execution records and can contain
   multiple perspectives — use them for evidence and participant behavior, NOT as a substitute
   for taker turnover.
   Columns (exact): ctx_time_ms, fill_event_id, block_number, transaction_hash, user_id, asset,
   amount_usdc, amount_shares, price, trade_side, order_hash, counterparty_id, order_type, fee,
   builder, market_id, market_title, outcome_label, market_url. IMPORTANT: the amounts are
   amount_usdc (USDC) and amount_shares (shares) — there is no amount, size, quantity, or
   usd_size column.

I. pm_user_balances_mv — an observed wallet's outcome-token balances. Use ONLY when explicitly
   asked. A balance is not proof of conviction, profitability, identity, or future behavior.

# 5. Freshness rules
snapshot_time_ms = when DeltaStream produced the current intelligence snapshot.
ctx_time_ms = the latest underlying market event included in that snapshot.
When both are available, say "Context updated…" (snapshot_time_ms) and "Latest included market
activity…" (ctx_time_ms). Bands: ≤5 min = live; >5 and ≤15 min = recent; >15 min = potentially
stale (say so clearly). Never claim something is happening "right now" when the latest context
is old. For pm_signal_transitions_mv, use transition_time_ms as the event timestamp and
latest_event_time_ms for how recently the market itself was active (this view has no
snapshot_time_ms or ctx_time_ms).

# 6. Metric interpretation & value scales
- signal_strength_score, signal_quality_score, attention_score: 0–100. Strength = size/intensity
  of activity; quality = structural support (breadth, persistence, low concentration);
  attention = how unusual/noteworthy. A low-quality signal may still matter (thin/concentrated/
  brief/fragile). "Strong but fragile" = high strength + low quality. None are outcome
  probabilities.
- taker_imbalance_* and buy_sell_imbalance_*: -1.0 (all sells) … +1.0 (all buys); ~0 balanced.
  Beginners: "buy-skewed" / "sell-skewed" / "balanced". Experts: include the number (+0.67).
- price_range_1h etc.: 0–1 implied probability. A value of 0.12 ≈ traded across ~12 cents in the
  period — it is a RANGE, not a 12-point rise/fall, and has no direction. Never call a price a
  forecast of the outcome.
- *_usdc = USDC dollar amounts; *_shares = outcome-share counts.
- unique_wallets_* / newly_observed_wallets_*: unique blockchain addresses OBSERVED by the
  pipeline — not necessarily unique people. Say "observed wallets", not "people".
- "Newly observed" = newly seen within the source history available to this deployment. It does
  NOT mean new to Polymarket, a new account, an insider, a new person, or coordinated. State
  this caveat whenever newly observed wallets are central. Concentrated activity is not evidence
  of manipulation.
- intelligence_reason is a precomputed natural-language reason — lean on it rather than
  re-deriving reasoning.

# 7. Field vocabularies (translate into natural language; never imply certainty)
- signal_type: SUSTAINED_BUY_PRESSURE, SUSTAINED_SELL_PRESSURE, EMERGING_BUY_PRESSURE,
  EMERGING_SELL_PRESSURE, FLOW_REVERSAL_TO_BUY, FLOW_REVERSAL_TO_SELL, WIDE_PRICE_RANGE,
  LARGE_MATCH_DRIVEN, ACTIVITY_ACCELERATION, UNUSUAL_PARTICIPANT_ACTIVITY, NORMAL_ACTIVITY.
- flow_regime: SUSTAINED_BUY, SUSTAINED_SELL, EMERGING_BUY, EMERGING_SELL, REVERSAL_TO_BUY,
  REVERSAL_TO_SELL, MIXED_FLOW.
- participation_type: BROAD_PARTICIPATION, MIXED_PARTICIPATION, THIN_PARTICIPATION,
  CONCENTRATED_FILL_STRUCTURE.
- unusual_participant_type: NORMAL_PARTICIPANT_MIX, ELEVATED_NEW_WALLET_ACTIVITY,
  HIGH_NEW_WALLET_CONCENTRATION, INSUFFICIENT_PROFILE_COVERAGE.
- signal_quality_band: HIGH_QUALITY, MEDIUM_QUALITY, LOW_QUALITY.
- transition_type (pm_signal_transitions_mv): SIGNAL_TYPE_CHANGED, QUALITY_BAND_CHANGED,
  FLOW_REVERSAL, ATTENTION_STRENGTHENED, ATTENTION_WEAKENED, MATERIAL_SCORE_CHANGE.
- story_type (pm_story_candidates_mv): MARKET_WAKING_UP_STORY, REVERSAL_STORY,
  UNUSUAL_PARTICIPANT_STORY, BROAD_MOVE_STORY, HIGH_ATTENTION_STORY, STRONG_BUT_FRAGILE_STORY.
- outcome_attention_state (pm_market_outcome_intelligence_mv): OUTCOME_0_ACCELERATING_FASTER,
  OUTCOME_1_ACCELERATING_FASTER, BOTH_OUTCOMES_HIGH_ATTENTION, BALANCED_OUTCOME_ATTENTION,
  OUTCOME_0_ACTIVITY_DOMINANT, OUTCOME_1_ACTIVITY_DOMINANT.
- data_quality_flag: COMPLETE, MISSING_MARKET_METADATA. If MISSING_MARKET_METADATA (or wallet
  profile coverage is low), say so and qualify participant-novelty conclusions.

# 8. Sorting by intent (pm_polymarket_intelligence_mv unless noted)
- What deserves attention / default briefing: attention_score DESC.
- What is waking up: volume_acceleration_5m_vs_1h DESC.
- Strongest signals: signal_strength_score DESC.
- Best-quality: signal_quality_score DESC.
- Strong but fragile: high signal_strength_score with low signal_quality_score.
- Broad activity: BROAD_PARTICIPATION with meaningful unique_wallets_1h.
- Unusual wallets: unusual_participant_type + newly_observed_volume_share_1h.
- Strongest buy/sell pressure: taker_imbalance_1h DESC / ASC.
- Freshest: ctx_time_ms DESC.

# 9. Columns per view
# Column pitfalls — wrong name (do NOT use) → correct name. These are the most common
# mistakes; always use the correct names from the lists below.
#  pm_signal_transitions_mv: attention_score → current_attention_score (or attention_score_change);
#    quality_score / signal_quality_score → current_quality_score (or quality_score_change);
#    signal_type / from_signal_type / to_signal_type / from_signal → previous_signal_type,
#    current_signal_type; quality band → current_quality_band / previous_quality_band;
#    market_name → market_title; transition_timestamp → transition_time_ms; (no market_state).
#  pm_recent_fills_mv: amount / size / quantity → amount_shares; usd_size / usd_volume /
#    notional → amount_usdc.
#  pm_polymarket_intelligence_mv: market_name → market_title; quality_band → signal_quality_band;
#    structural_quality_score → signal_quality_score; signal_reason → intelligence_reason;
#    asset_name → outcome_label; usd_volume → taker_usdc_1h; num_fills → participant_fill_events_1h;
#    outcome → outcome_label.
"polymarket"."public"."pm_polymarket_intelligence_mv": asset, market_id, market_title,
 question, outcome_label, outcome_index, market_url, market_state, active, closed,
 accepting_orders, gamma_description, resolution_source, gamma_volume, gamma_spread,
 last_trade_price, best_ask, snapshot_time_ms, ctx_time_ms, signal_type, intelligence_reason,
 flow_regime, participation_type, unusual_participant_type, signal_strength_score,
 signal_quality_score, signal_quality_band, attention_score, taker_usdc_1h, taker_buy_usdc_1h,
 taker_sell_usdc_1h, taker_imbalance_5m, taker_imbalance_15m, taker_imbalance_1h,
 volume_acceleration_5m_vs_1h, volume_acceleration_15m_vs_1h, avg_taker_price_1h,
 min_taker_price_1h, max_taker_price_1h, price_range_1h, large_match_count_1h,
 large_match_volume_share_1h, max_match_usdc_1h, unique_wallets_5m, unique_wallets_15m,
 unique_wallets_1h, unique_buyers_1h, unique_sellers_1h, wallet_participation_acceleration,
 single_fill_concentration_share_1h, newly_observed_wallets_1h, newly_observed_volume_share_1h,
 wallet_profile_coverage_1h, data_quality_flag
"polymarket"."public"."pm_signal_transitions_mv": asset, market_id, market_title, outcome_label,
 market_url, transition_time_ms, latest_event_time_ms, previous_signal_type, current_signal_type,
 previous_flow_regime, current_flow_regime, previous_quality_band, current_quality_band,
 previous_attention_score, current_attention_score, attention_score_change, previous_quality_score,
 current_quality_score, quality_score_change, transition_type
"polymarket"."public"."pm_signal_history_mv": asset, market_id, market_title, outcome_label,
 market_url, snapshot_time_ms, ctx_time_ms, signal_type, intelligence_reason, flow_regime,
 participation_type, unusual_participant_type, signal_strength_score, signal_quality_score,
 signal_quality_band, attention_score, volume_acceleration_5m_vs_1h, taker_imbalance_5m,
 taker_imbalance_15m, taker_imbalance_1h, unique_wallets_5m, unique_wallets_1h, price_range_1h,
 newly_observed_volume_share_1h, data_quality_flag
"polymarket"."public"."pm_wallet_intelligence_mv": user_id, ctx_time_ms, wallet_age_ms,
 first_seen_ms, last_seen_ms, lifetime_fill_events, lifetime_participant_side_usdc, fill_events_1h,
 participant_side_usdc_1h, buy_usdc_1h, sell_usdc_1h, unique_assets_1h, max_fill_usdc_1h,
 fill_events_24h, participant_side_usdc_24h, buy_usdc_24h, sell_usdc_24h, unique_assets_24h,
 max_fill_usdc_24h, activity_acceleration_1h_vs_24h, buy_sell_imbalance_1h, buy_sell_imbalance_24h,
 wallet_novelty_band, wallet_behavior_state
"polymarket"."public"."pm_wallet_asset_flow_mv": user_asset_key, user_id, asset, market_id,
 market_title, outcome_label, market_url, ctx_time_ms, fills_count_1h, filled_usdc_1h,
 filled_shares_1h, buy_usdc_1h, sell_usdc_1h, net_shares_1h, fee_total_1h, max_fill_usdc_1h,
 wallet_asset_activity_state
"polymarket"."public"."pm_market_outcome_intelligence_mv": market_id, market_title, market_url,
 snapshot_time_ms, ctx_time_ms, outcome_0_asset, outcome_0_label, outcome_0_taker_usdc_1h,
 outcome_0_acceleration, outcome_0_attention_score, outcome_0_signal_type, outcome_1_asset,
 outcome_1_label, outcome_1_taker_usdc_1h, outcome_1_acceleration, outcome_1_attention_score,
 outcome_1_signal_type, outcome_0_activity_share, outcome_1_activity_share, outcome_attention_state
"polymarket"."public"."pm_story_candidates_mv": asset, market_id, market_title, outcome_label,
 market_url, snapshot_time_ms, ctx_time_ms, signal_type, intelligence_reason, signal_strength_score,
 signal_quality_score, attention_score, flow_regime, participation_type, unusual_participant_type,
 volume_acceleration_5m_vs_1h, taker_usdc_5m, taker_usdc_1h, taker_imbalance_5m, taker_imbalance_1h,
 unique_wallets_5m, unique_wallets_1h, newly_observed_wallets_1h, newly_observed_volume_share_1h,
 price_range_1h, data_quality_flag, story_type
"polymarket"."public"."pm_recent_fills_mv": ctx_time_ms, fill_event_id, block_number,
 transaction_hash, user_id, asset, amount_usdc, amount_shares, price, trade_side, order_hash,
 counterparty_id, order_type, fee, builder, market_id, market_title, outcome_label, market_url
"polymarket"."public"."pm_user_balances_mv": id, owner_address, contract_address, token_id,
 token_type, balance_amount, block_number, ctx_time_ms

# 10. Response formats
Live briefing — headline "Live Polymarket intelligence", then per market (only the most
meaningful, ≤10): "N. Market title — Outcome", one-sentence plain-English explanation, then
What changed / Why it stands out / Signal strength / Signal quality / Attention / Participation
/ Freshness / Market link. End with: "These scores describe observable activity, not the
probability that an outcome will occur."
Single-market explanation — Plain-English explanation; Why it stands out (acceleration,
direction, breadth, concentration, unusual participants, reversal); Expert view (metrics);
Evidence and freshness; What this does not mean.
What changed while I was away — "What changed since [time]"; New or strengthening; Reversals;
Weakening or fading; Current leaders (which transitions still matter now).

# 11. Style & safety
Lead with the insight, not the retrieval process. Prefer "Activity accelerated to about 4.1×
its recent hourly pace" over raw field names. Round sensibly: $12,438.71 → ~$12.4K; 0.6732 →
+0.67; 0.124 price range → about 12 cents; 47.291 → 47. Include market titles/outcome labels
and URLs, not just asset IDs. Do not expose tool IDs, query syntax, or raw payloads unless
asked. Never provide betting/trade recommendations, position sizing, expected returns,
guaranteed outcomes, "mispriced" claims, instructions to copy a wallet, insider claims, or
accusations of manipulation/coordination without proof. If asked "should I buy?" respond:
"I can explain the current activity and signal structure, but I cannot recommend a bet or
trade." then give a neutral intelligence summary.

# Worked examples
# 1) Broad "what deserves attention" briefing (one query). The active/closed filter is
#    future-proofing — this view is currently all-active, so the filter may be dropped.
SELECT market_title, outcome_label, market_state, signal_type, intelligence_reason,
  attention_score, signal_strength_score, signal_quality_score, taker_usdc_1h, taker_imbalance_1h,
  volume_acceleration_5m_vs_1h, participation_type, data_quality_flag, snapshot_time_ms, ctx_time_ms
FROM "polymarket"."public"."pm_polymarket_intelligence_mv"
WHERE active = true AND closed = false
ORDER BY attention_score DESC LIMIT 10

# 2) "What changed in the last two hours" (transitions). Replace <now_ms> with the freshest
#    ctx_time_ms you have observed in the primary view; 7200000 ms = 2 hours.
SELECT market_title, outcome_label, transition_type, previous_signal_type, current_signal_type,
  previous_flow_regime, current_flow_regime, attention_score_change, quality_score_change,
  transition_time_ms, market_url
FROM "polymarket"."public"."pm_signal_transitions_mv"
WHERE transition_time_ms > (<now_ms> - 7200000)
ORDER BY transition_time_ms DESC LIMIT 25

# 3) "What is interesting / share-worthy right now" (story candidates). Dedupe by asset in the
#    answer (same story recurs across snapshots); verify numbers in the primary view.
SELECT story_type, market_title, outcome_label, signal_type, intelligence_reason,
  attention_score, signal_strength_score, signal_quality_score, taker_usdc_1h,
  volume_acceleration_5m_vs_1h, market_url, snapshot_time_ms, ctx_time_ms
FROM "polymarket"."public"."pm_story_candidates_mv"
ORDER BY attention_score DESC, snapshot_time_ms DESC LIMIT 10

# 4) "For market X, how many wallets traded and the average / max trade size" (per-market trade
#    stats). Works even for finished markets absent from the primary view. Filter by market_title
#    (LIKE) or market_id; group per outcome.
SELECT outcome_label, count(DISTINCT user_id) AS wallets, count() AS fills,
  avg(amount_usdc) AS avg_trade_usdc, max(amount_usdc) AS max_trade_usdc
FROM "polymarket"."public"."pm_recent_fills_mv"
WHERE market_title LIKE '%Liberty%' AND market_title LIKE '%Wings%'
GROUP BY outcome_label LIMIT 100
"""

RUNTIME_INSTRUCTIONS = {
    "organization": "Use the registered DeltaStream MCP toolset for all data access.",
    "constraints": [
        "Only query the fully qualified DeltaStream views named in the system prompt.",
        "Do not fabricate context if the views do not support the question.",
        "Explain that DeltaStream precomputed the context continuously from streaming data before inference time.",
        "For topic market existence or active-market list questions, use pm_polymarket_intelligence_mv (market metadata is enriched into it) and deduplicate by market_id to distinct markets before answering.",
        "For 'what changed' / 'while I was away' questions, use pm_signal_transitions_mv for the requested period (default the most recent two hours and state that assumption); do not just rerun the current top-market ranking.",
        "Do not stop at intermediate findings; continue making MCP calls until you can answer directly.",
        "The schema is already provided in the system prompt. Never run DESCRIBE, SHOW, or query deltastream.sys.* or relation_columns, and never run exploratory or schema-discovery queries.",
        "Answer broad briefings with a single SELECT against pm_polymarket_intelligence_mv. Only run additional queries for genuine drill-down.",
    ],
    "query_constraints": {
        "select_only_needed_columns": True,
        "avoid_select_star": True,
        "no_schema_discovery": True,
        "broad_briefing_row_limit": 10,
        "drilldown_row_limit": 25,
        "guidance": (
            "Keep result sets small and fast. The schema is already known, so do not "
            "inspect it. Project only the columns you will show in the answer. Never "
            "SELECT *. Always include an explicit small LIMIT and ORDER BY so the query "
            "returns quickly. Issue exactly one query for broad briefings."
        ),
    },
}

# Leading planning phrases that indicate a transitional (non-final) stub.
# These are only treated as transitional when the output is short and lacks a
# real answer body, to avoid rejecting legitimate final answers that happen to
# contain phrases like "let me know" or end a header line with a colon.
TRANSITIONAL_LEADING_PATTERNS = [
    r"^(let me|now let me|i need to|i am going to|i'?m going to|i will|i'?ll)\b",
    r"^(let me search|let me check|let me query|let me fetch|let me look)\b",
    r"^(now i can see|i now have|intermediate findings?)\b",
    r"^(i'?ll\s+deduplicat\w*)\b",
]

# Below this length an answer with no markdown structure and a leading planning
# phrase is considered a transitional stub rather than a real answer.
TRANSITIONAL_MAX_STUB_CHARS = 280

MAX_RESPONSE_CHARS = 4500


def messages_from_transcript(
    transcript: list[tuple[str, str]],
) -> list[ModelMessage]:
    """Rebuild pydantic-ai message history from a plain (question, answer) transcript.

    Each prior turn becomes a user ModelRequest followed by an assistant
    ModelResponse containing only the final answer text. Tool calls and results
    are intentionally omitted: this keeps the history small, leaks no internal
    SQL/tool payloads, and is enough for the model to resolve references such as
    "that market" from its own prior answers. The agent's system prompt is
    applied to the new request by the Agent, so it is not included here.
    """
    messages: list[ModelMessage] = []
    for question, answer in transcript:
        if question:
            messages.append(ModelRequest(parts=[UserPromptPart(content=question)]))
        if answer:
            messages.append(ModelResponse(parts=[TextPart(content=answer)]))
    return messages


def _build_prompt(
    question: str,
    follow_up_instruction: str | None = None,
    previous_attempt: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "user_question": question,
        "runtime_instructions": RUNTIME_INSTRUCTIONS,
    }
    if follow_up_instruction:
        payload["follow_up_instruction"] = follow_up_instruction
    if previous_attempt:
        payload["previous_attempt"] = previous_attempt
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    return (
        "Use the DeltaStream MCP tools to query the required fully qualified materialized views. "
        "If data is missing, clearly say context is insufficient.\n\n"
        f"{serialized}"
    )


def _is_blank_answer(text: str) -> bool:
    return not text.strip()


def _question_requires_data(question: str) -> bool:
    normalized = question.strip().lower()
    if not normalized:
        return False
    non_data_patterns = [
        r"^(hi|hello|hey|thanks|thank you)[!. ]*$",
        r"^(who are you|what can you do|help)\??$",
    ]
    return not any(re.search(pattern, normalized) for pattern in non_data_patterns)


def _is_transitional_output(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return True
    lowered = cleaned.lower()
    has_leading_planning = any(
        re.search(pattern, lowered) for pattern in TRANSITIONAL_LEADING_PATTERNS
    )
    if not has_leading_planning:
        return False
    # A real answer typically has a headline/structure and substantive length.
    has_structure = "\n" in cleaned or cleaned.startswith("#")
    if has_structure and len(cleaned) >= TRANSITIONAL_MAX_STUB_CHARS:
        return False
    return len(cleaned) < TRANSITIONAL_MAX_STUB_CHARS


def _normalize_answer_style(text: str) -> str:
    # Preserve markdown block structure: strip trailing whitespace per line and
    # collapse runs of 3+ blank lines to a single blank line, but keep the blank
    # lines that separate headings, paragraphs, and list blocks (Markdown needs
    # them to render correctly). Do NOT delete all blank lines.
    cleaned = text.strip()
    if not cleaned:
        return ""
    lines = [line.rstrip() for line in cleaned.splitlines()]
    normalized_lines: list[str] = []
    blank_run = 0
    for line in lines:
        if line:
            blank_run = 0
            normalized_lines.append(line)
        else:
            blank_run += 1
            if blank_run <= 1:
                normalized_lines.append(line)
    return "\n".join(normalized_lines).strip()


def _last_response_finish_reason(messages: list[Any] | None) -> str | None:
    if not messages:
        return None
    for message in reversed(messages):
        if isinstance(message, ModelResponse):
            return message.finish_reason
    return None


def _is_upstream_timeout_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "status_code: 504" in lowered
        or "upstream request timeout" in lowered
        or "gateway timeout" in lowered
        or "timed out" in lowered
    )


def _bare_model_name(model_name: str) -> str:
    for prefix in ("anthropic:", "google:", "gemini:"):
        if model_name.startswith(prefix):
            return model_name[len(prefix) :]
    return model_name


def _extract_tool_call_display(name: str, args: dict[str, Any]) -> tuple[str, str] | None:
    if name in {"query_mview", "execute_dsql"}:
        sql = args.get("sql") or args.get("query") or args.get("statement")
        if isinstance(sql, str) and sql.strip():
            return (name, sql)
        return None
    if name == "doc_search":
        query = args.get("query") or args.get("search") or args.get("q")
        if isinstance(query, str) and query.strip():
            return (name, query)
    return None


_SQL_ARG_KEYS = ("sql", "query", "statement")
_SCHEMA_DISCOVERY_RE = re.compile(
    r"\b(system\.[a-z_]+|information_schema|deltastream\.sys|relation_columns)\b",
    re.IGNORECASE,
)
_HAS_LIMIT_RE = re.compile(r"\blimit\b", re.IGNORECASE)
_IS_SELECT_RE = re.compile(r"^\s*(with|select)\b", re.IGNORECASE)


def _sanitize_query_sql(sql: str) -> str:
    """Deterministic guardrails for model-generated ClickHouse SQL.

    - Strips trailing whitespace and semicolons (a trailing ';' returns null via MCP).
    - Rejects schema-discovery / system-table queries with an actionable ModelRetry.
    - Appends a default LIMIT to SELECTs that lack one (prevents unbounded scans).
    Note: this cannot fix hallucinated column names — the system prompt handles that.
    """
    cleaned = sql.strip().rstrip(";").rstrip()
    if _SCHEMA_DISCOVERY_RE.search(cleaned):
        raise ModelRetry(
            "Schema discovery is not available. Do not query system tables, "
            "information_schema, deltastream.sys.*, or relation_columns. Use only the "
            'fully qualified "polymarket"."public"."<view>" relations and the exact '
            "columns listed in the system prompt."
        )
    if _IS_SELECT_RE.match(cleaned) and not _HAS_LIMIT_RE.search(cleaned):
        cleaned = f"{cleaned} LIMIT {settings.query_limit}"
    return cleaned


def _build_model(api_token: str) -> AnthropicModel | GoogleModel:
    bare_name = _bare_model_name(settings.model_name)
    if settings.llm_provider == "google":
        from google.genai import Client
        from google.genai.types import HttpOptions

        # The demo /gemini gateway authenticates off a Bearer token and serves the
        # standard Gemini REST surface at `{base}/v1beta/models/<model>:generateContent`.
        # A custom (non-googleapis) base_url makes google-genai drop its default
        # api_version, so set it explicitly to v1beta to match the gateway path.
        client = Client(
            vertexai=False,
            api_key=api_token,
            http_options=HttpOptions(
                base_url=settings.gemini_base_url,
                api_version="v1beta",
                headers={"Authorization": f"Bearer {api_token}"},
            ),
        )
        provider = GoogleProvider(client=client)
        return GoogleModel(bare_name, provider=provider)

    anthropic_key = settings.anthropic_api_key or api_token
    provider = AnthropicProvider(api_key=anthropic_key, base_url=settings.anthropic_base_url)
    return AnthropicModel(bare_name, provider=provider)


def _build_agent(
    api_token: str,
    tool_call_callback: Callable[[str, str], None] | None = None,
) -> Agent:
    model = _build_model(api_token)

    async def process_tool_call(
        ctx: RunContext[Any],
        call_tool: CallToolFunc,
        name: str,
        args: dict[str, Any],
    ) -> ToolResult:
        del ctx
        # Deterministic guardrails on model-generated SQL before it executes:
        # strip trailing ';', block schema discovery, and inject a default LIMIT.
        if name in {"query_mview", "execute_dsql"}:
            for key in _SQL_ARG_KEYS:
                value = args.get(key)
                if isinstance(value, str) and value.strip():
                    args[key] = _sanitize_query_sql(value)
                    break
        # Debug: record every MCP tool request (and its DSQL/SQL when present) so the
        # exact statement sent to DeltaStream is visible in the process logs. Logged
        # after sanitization so it matches what actually executes.
        _sql_for_log = next(
            (args[k] for k in _SQL_ARG_KEYS if isinstance(args.get(k), str) and args[k].strip()),
            None,
        )
        if _sql_for_log is not None:
            logger.info("MCP tool request: %s | dsql=%s", name, _sql_for_log)
        else:
            logger.info("MCP tool request: %s | args=%s", name, json.dumps(args, default=str))
        tool_call_display = _extract_tool_call_display(name, args)
        if tool_call_display and tool_call_callback is not None:
            tool_name, tool_payload = tool_call_display
            tool_call_callback(tool_name, tool_payload)
        return await call_tool(name, args)

    toolset = MCPToolset(
        settings.deltastream_mcp_url,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
        process_tool_call=process_tool_call,
    )
    agent = Agent(
        model,
        system_prompt=SYSTEM_PROMPT,
        toolsets=[toolset],
        retries=4,
    )

    @agent.output_validator
    def _validate_final_output(ctx: RunContext[Any], output: str) -> str:
        if _is_transitional_output(output):
            raise ModelRetry(
                "Return only the final user-facing answer. Do not include planning narration or intermediate steps."
            )
        normalized = _normalize_answer_style(output)
        # Length is a soft cap: retry once to elicit a tighter answer, but if the
        # model insists on a long response, soft-truncate with a note rather than
        # discarding a valid answer (which would surface the generic fallback).
        if len(normalized) > MAX_RESPONSE_CHARS:
            if ctx.retry < 1:
                raise ModelRetry(
                    "Return a more concise answer: a short headline, only the metrics that "
                    "matter, and a brief takeaway."
                )
            truncated = normalized[:MAX_RESPONSE_CHARS].rstrip()
            return (
                f"{truncated}\n\n_Response trimmed for length. Ask a narrower question for full detail._"
            )
        return normalized

    return agent


async def stream_answer(
    question: str,
    api_token: str,
    history: list[ModelMessage] | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    tool_call_events: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    had_data_query = False

    def on_tool_call(tool_name: str, tool_payload: str) -> None:
        nonlocal had_data_query
        if tool_name in {"query_mview", "execute_dsql"}:
            had_data_query = True
        tool_call_events.put_nowait((tool_name, tool_payload))

    agent = _build_agent(api_token, tool_call_callback=on_tool_call)
    yielded_tool_calls: set[tuple[str, str]] = set()
    # Seed with prior-turn history (if any) so follow-up questions can resolve
    # references like "that market" against earlier answers. The retry loop
    # keeps extending this within the current turn.
    message_history: list[Any] | None = list(history) if history else None
    previous_attempt: str | None = None
    final_text = ""
    total_start = time.perf_counter()
    attempts_used = 0
    timeout_reached = False
    truncated = False
    # LLM usage accounting across all attempts of this call, so we can log how many
    # requests were actually sent to the model per user question.
    total_requests = 0
    total_tool_calls = 0
    total_input_tokens = 0
    total_output_tokens = 0

    def _attempt_usage(run: Any) -> dict[str, int]:
        """Read this attempt's model usage (requests/tool_calls/tokens) and fold it
        into the running totals. Best-effort: never let telemetry break a response."""
        nonlocal total_requests, total_tool_calls, total_input_tokens, total_output_tokens
        try:
            # `usage` is a property on AgentRun (not a method) — no parentheses.
            usage = run.usage
        except Exception as exc:  # noqa: BLE001
            logger.debug("usage read failed: %r", exc)
            return {"model_requests": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0}
        requests = int(getattr(usage, "requests", 0) or 0)
        tool_calls = int(getattr(usage, "tool_calls", 0) or 0)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        total_requests += requests
        total_tool_calls += tool_calls
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        return {
            "model_requests": requests,
            "tool_calls": tool_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    max_attempts = 3
    model_settings: ModelSettings | None = None
    if settings.quick_mode_enabled:
        max_attempts = max(1, settings.quick_mode_max_attempts)
        quick_max_tokens = max(256, settings.quick_mode_max_tokens)
        quick_timeout = max(5.0, settings.quick_mode_timeout_seconds)
        if settings.llm_provider == "google":
            # Gemini reasoning tokens count against max_tokens, so use a larger output
            # budget to avoid truncating the visible answer. Bound thinking to keep
            # latency in check on agentic, multi-tool tasks (prefer thinking_level for
            # 3.x models, fall back to thinking_budget for 2.5).
            google_max_tokens = max(quick_max_tokens, settings.gemini_max_output_tokens)
            google_kwargs: dict[str, Any] = {
                "max_tokens": google_max_tokens,
                "timeout": quick_timeout,
            }
            thinking_config: dict[str, Any] = {}
            if settings.gemini_thinking_level:
                thinking_config["thinking_level"] = settings.gemini_thinking_level
            elif settings.gemini_thinking_budget is not None:
                thinking_config["thinking_budget"] = max(0, settings.gemini_thinking_budget)
            if thinking_config:
                thinking_config["include_thoughts"] = False
                google_kwargs["google_thinking_config"] = thinking_config
            model_settings = GoogleModelSettings(**google_kwargs)
        else:
            model_settings = AnthropicModelSettings(
                max_tokens=quick_max_tokens,
                timeout=quick_timeout,
            )

    def _flush_tool_events() -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        while not tool_call_events.empty():
            tool_name, tool_payload = tool_call_events.get_nowait()
            event_key = (tool_name, tool_payload)
            if event_key in yielded_tool_calls:
                continue
            yielded_tool_calls.add(event_key)
            events.append((tool_name, tool_payload))
        return events

    def _fallback_message(reason: str) -> str:
        if reason == "no_data_queries":
            return (
                "# Context unavailable\n\n"
                "I could not run a successful DeltaStream data query for this request. "
                "Please retry or narrow the question to a specific market, topic, or outcome."
            )
        if reason == "internal_process":
            return (
                "# Context unavailable\n\n"
                "I could not produce a clean user-facing response from the model output for this request. "
                "Please retry, and if needed narrow to a specific market or timeframe."
            )
        if reason == "tool_error":
            return (
                "# Context unavailable\n\n"
                "I couldn't complete the DeltaStream data query for this request after several attempts. "
                "Please retry, or narrow the question to a specific market, outcome, or timeframe."
            )
        return (
            "# Context unavailable\n\n"
            "I could not generate a complete answer from the available DeltaStream context. "
            "Please retry the question or make it more specific."
        )

    requires_data = _question_requires_data(question)

    for attempt_number in range(max_attempts):
        attempts_used = attempt_number + 1
        attempt_start = time.perf_counter()
        follow_up_instruction = None
        if attempt_number > 0:
            follow_up_instruction = (
                "Continue until you can return the final user-facing answer. "
                "Do not narrate tool usage, planning, or intermediate findings. "
                "Keep the answer concise with a short headline, up to 7 signals, and a short takeaway."
            )

        user_prompt = _build_prompt(
            question,
            follow_up_instruction=follow_up_instruction,
            previous_attempt=previous_attempt,
        )
        run_result = None
        # Clear any previously streamed answer text before producing a new
        # candidate (e.g. on a retry attempt).
        yield ("reset", "")
        try:
            async with agent.iter(
                user_prompt,
                message_history=message_history,
                model_settings=model_settings,
            ) as run:
                async for node in run:
                    for tool_name, tool_payload in _flush_tool_events():
                        yield (tool_name, tool_payload)
                    # Stream the model's text output token-by-token so the final
                    # answer renders progressively and real bytes keep flowing
                    # during long generations.
                    if Agent.is_model_request_node(node):
                        async with node.stream(run.ctx) as request_stream:
                            async for event in request_stream:
                                delta_text = ""
                                if isinstance(event, PartStartEvent) and isinstance(
                                    event.part, TextPart
                                ):
                                    delta_text = event.part.content or ""
                                elif isinstance(event, PartDeltaEvent) and isinstance(
                                    event.delta, TextPartDelta
                                ):
                                    delta_text = event.delta.content_delta or ""
                                if delta_text:
                                    yield ("token", delta_text)
                        for tool_name, tool_payload in _flush_tool_events():
                            yield (tool_name, tool_payload)
                for tool_name, tool_payload in _flush_tool_events():
                    yield (tool_name, tool_payload)
                run_result = run.result
                message_history = run.all_messages()
                attempt_usage = _attempt_usage(run)
        except UnexpectedModelBehavior as exc:
            # Raised when a tool (e.g. query_mview) exhausts its retry budget —
            # typically the model kept issuing invalid SQL (bad column, bad
            # dialect). Surface a graceful fallback instead of the raw
            # "stream interrupted" banner, and allow one more clean attempt.
            if os.getenv("AGENT_DEBUG"):
                print("AGENT_DEBUG tool retry exhausted:", repr(exc), flush=True)
            attempt_duration_ms = int((time.perf_counter() - attempt_start) * 1000)
            attempt_usage = _attempt_usage(run)
            logger.debug(
                "llm attempt %d failed (tool retries exhausted): model_requests=%d tool_calls=%d",
                attempt_number + 1,
                attempt_usage["model_requests"],
                attempt_usage["tool_calls"],
            )
            yield (
                "llm_timing",
                {
                    "kind": "attempt",
                    "attempt": attempt_number + 1,
                    "duration_ms": attempt_duration_ms,
                    "accepted": False,
                    "output_chars": 0,
                    **attempt_usage,
                },
            )
            if attempt_number < max_attempts - 1:
                continue
            final_text = _fallback_message("tool_error")
            break
        except Exception as exc:  # noqa: BLE001
            error_message = str(exc)
            if os.getenv("AGENT_DEBUG"):
                import traceback

                print("AGENT_DEBUG exception:", repr(exc), flush=True)
                traceback.print_exc()
            if _is_upstream_timeout_error(error_message):
                timeout_reached = True
                final_text = (
                    "# Model timeout\n\n"
                    "The model timed out before finishing this response. "
                    "Please retry the same prompt, or narrow the request to a smaller scope."
                )
                attempt_duration_ms = int((time.perf_counter() - attempt_start) * 1000)
                attempt_usage = _attempt_usage(run)
                yield (
                    "llm_timing",
                    {
                        "kind": "attempt",
                        "attempt": attempt_number + 1,
                        "duration_ms": attempt_duration_ms,
                        "accepted": False,
                        "output_chars": 0,
                        **attempt_usage,
                    },
                )
                break
            raise

        if run_result is None:
            continue

        output = run_result.output if isinstance(run_result.output, str) else ""
        final_text = _normalize_answer_style(output)
        previous_attempt = final_text or previous_attempt
        truncated = _last_response_finish_reason(message_history) == "length"
        attempt_duration_ms = int((time.perf_counter() - attempt_start) * 1000)
        accepted = (
            not _is_blank_answer(final_text)
            and not _is_transitional_output(final_text)
            and (not requires_data or had_data_query)
        )
        yield (
            "llm_timing",
            {
                "kind": "attempt",
                "attempt": attempt_number + 1,
                "duration_ms": attempt_duration_ms,
                "accepted": accepted,
                "output_chars": len(final_text),
                **attempt_usage,
            },
        )
        logger.debug(
            "llm attempt %d: model_requests=%d tool_calls=%d input_tokens=%d output_tokens=%d accepted=%s",
            attempt_number + 1,
            attempt_usage["model_requests"],
            attempt_usage["tool_calls"],
            attempt_usage["input_tokens"],
            attempt_usage["output_tokens"],
            accepted,
        )

        if _is_blank_answer(final_text):
            continue
        if _is_transitional_output(final_text):
            continue
        if requires_data and not had_data_query:
            continue
        break

    if _is_blank_answer(final_text):
        if requires_data and not had_data_query:
            final_text = _fallback_message("no_data_queries")
        else:
            final_text = _fallback_message("blank")
    elif _is_transitional_output(final_text):
        final_text = _fallback_message("internal_process")
    elif requires_data and not had_data_query:
        final_text = _fallback_message("no_data_queries")

    if timeout_reached and not final_text:
        final_text = (
            "# Model timeout\n\n"
            "The model timed out before finishing this response. "
            "Please retry the same prompt, or narrow the request to a smaller scope."
        )

    if (
        truncated
        and final_text
        and not final_text.lstrip().startswith("# Context unavailable")
        and not final_text.lstrip().startswith("# Model timeout")
    ):
        final_text = (
            f"{final_text}\n\n"
            "_Note: the response was cut off at the model's output limit. "
            "Ask a narrower question or increase GEMINI_MAX_OUTPUT_TOKENS for the full answer._"
        )

    total_duration_ms = int((time.perf_counter() - total_start) * 1000)
    stripped = final_text.lstrip()
    if timeout_reached or stripped.startswith("# Model timeout"):
        outcome = "timeout"
    elif stripped.startswith("# Context unavailable"):
        outcome = "fallback"
    else:
        outcome = "accepted"
    yield (
        "llm_timing",
        {
            "kind": "summary",
            "duration_ms": total_duration_ms,
            "attempts": attempts_used,
            "had_data_query": had_data_query,
            "output_chars": len(final_text),
            "model_requests": total_requests,
            "tool_calls": total_tool_calls,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "outcome": outcome,
        },
    )

    if final_text:
        yield ("final", final_text)
