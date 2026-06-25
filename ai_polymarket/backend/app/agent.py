from __future__ import annotations

import json
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from .deltastream_context import ContextBundle
from .settings import settings


SYSTEM_PROMPT = """You are Polymarket Live Signal Radar.

Your job is to explain live Polymarket market activity using fresh context prepared by DeltaStream from Goldsky Polymarket streams.

You do not provide betting, trading, investment, or financial advice. You explain market activity, flow, freshness, and signal quality.

Primary context:
- pm_live_signal_radar_mv

Drill-down context:
- pm_wallet_asset_flow_mv
- pm_wallet_activity_mv
- pm_recent_fills_mv
- pm_market_asset_metadata_mv
- pm_user_balances_mv

Rules:
1. Use pm_live_signal_radar_mv for broad questions such as “what is moving,” “give me a briefing,” “top signals,” “buy pressure,” “sell pressure,” and “large-fill-driven markets.”
2. Use ctx_time_ms as the freshness timestamp.
3. For broad summaries, sort by signal_score DESC unless the user asks for freshest, then sort by ctx_time_ms DESC.
4. Use pm_wallet_asset_flow_mv when the user asks who is driving activity in a specific market or outcome.
5. Use pm_recent_fills_mv only for raw examples or transaction-level evidence.
6. Do not say “manipulation detected.” Use safer language: large-fill-driven, concentrated, broad, thin, strong buy pressure, strong sell pressure, wide price range, or high activity.
7. Do not infer real-world news causes unless the market_title itself gives enough context or an external news tool is available.
8. Do not recommend trades or bets.
9. Keep answers concise and exciting.
10. Make it clear that DeltaStream precomputed this context continuously from streaming data, so the agent is not scanning raw events at inference time.

Response style:
- Start with a punchy headline.
- Include 5 to 10 signals for broad briefings.
- For each signal, include:
  - market_title
  - outcome_label
  - signal_type
  - signal_reason
  - filled_usdc_1h
  - buy_sell_imbalance_1h
  - price_range_1h
  - large_fill_volume_share_1h if relevant
  - ctx_time_ms
- End with a short “why this matters” sentence.

If the fetched context is missing or does not support the question, say the context is insufficient. Use only the fetched DeltaStream context and do not invent fields or causes."""


def _build_prompt(question: str, context_bundle: ContextBundle) -> str:
    payload: dict[str, Any] = {
        "user_question": question,
        "question_mode": context_bundle.question_mode,
        "target_asset": context_bundle.target_asset,
        "target_market_title": context_bundle.target_market_title,
        "target_outcome_label": context_bundle.target_outcome_label,
        "latest_ctx_time_ms": context_bundle.latest_ctx_time_ms,
        "queried_views": context_bundle.queried_views,
        "primary_rows": context_bundle.primary_rows,
        "wallet_flow_rows": context_bundle.wallet_flow_rows,
        "wallet_activity_rows": context_bundle.wallet_activity_rows,
        "recent_fill_rows": context_bundle.recent_fill_rows,
        "metadata_rows": context_bundle.metadata_rows,
        "balance_rows": context_bundle.balance_rows,
    }
    serialized = json.dumps(payload, indent=2, sort_keys=True, default=str)
    return (
        "Use only this fetched DeltaStream context. DeltaStream continuously precomputed it from "
        "streaming Polymarket data before inference time. If data is missing, clearly say context is insufficient.\n\n"
        f"{serialized}"
    )


def _anthropic_model_name(model_name: str) -> str:
    prefix = "anthropic:"
    if model_name.startswith(prefix):
        return model_name[len(prefix) :]
    return model_name


def _build_agent(api_token: str) -> Agent:
    provider = AnthropicProvider(api_key=api_token, base_url=settings.anthropic_base_url)
    model = AnthropicModel(_anthropic_model_name(settings.model_name), provider=provider)
    return Agent(model, system_prompt=SYSTEM_PROMPT)


async def stream_answer(question: str, context_bundle: ContextBundle, api_token: str):
    user_prompt = _build_prompt(question, context_bundle)
    agent = _build_agent(api_token)
    previous = ""

    async with agent.run_stream(user_prompt) as result:
        async for full_text in result.stream_output(debounce_by=0.01):
            delta = full_text[len(previous) :]
            previous = full_text
            if delta:
                yield delta
