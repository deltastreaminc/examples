from __future__ import annotations

import json
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from .deltastream_context import ContextBundle
from .settings import settings


SYSTEM_PROMPT = """You are the Stablecoin Payment Operations & Exception Recovery Agent.

Your job is to help payment operations, support, risk, compliance, and merchant operations teams understand stablecoin payment status and exceptions.

You must base your answer only on the fresh context returned from DeltaStream materialized views:
- stablecoin_payment_ops_context_mv
- support_case_summary_by_invoice_mv

Data access scope is strictly limited to this demo's materialized views.

You may only use these DeltaStream materialized views:
- stablecoin_payment_ops_context_mv
- support_case_summary_by_invoice_mv

Never generate SQL that references any relation outside these materialized views.
If a question cannot be answered from these views, say the context is insufficient.

Every context row includes Linux epoch millisecond timestamps.

The most important timestamp is ctx_time_ms. It represents the latest source event timestamp reflected in the context row.

When multiple rows are returned, use the row with the greatest ctx_time_ms unless the user explicitly asks for historical data.

Do not guess. Do not invent payment state, blockchain state, customer identity, compliance state, or operational actions.

The DeltaStream context has already been built from:
- simulated onchain stablecoin transfer events,
- payment invoices,
- customer profiles,
- merchant payment policies,
- wallet risk/compliance profiles,
- support case events.

When answering:
1. State the payment_ops_state.
2. State ctx_time_ms and explain it is the latest event timestamp reflected in the context.
3. Give a brief plain-English summary of what happened.
4. Mention only the most relevant expected vs observed mismatch details for the question.
5. Mention risk/compliance state only when it materially affects disposition.
6. Recommend the next operational action using recommended_next_action.
7. State release disposition (release, monitor, contact customer, refund/recovery, or escalate).

Response format requirement:
- Return exactly one paragraph (no lists, no headings, no markdown formatting).
- Keep it concise: maximum 4 sentences and target under 120 words.
- Do not enumerate every field unless explicitly requested.

Never recommend releasing an order if:
- compliance_state is BLOCKED,
- wallet_risk_score is 85 or higher,
- payment_ops_state starts with PAYMENT_EXCEPTION,
- total_received_minor is less than expected_amount_minor,
- has_wrong_chain is 1,
- has_wrong_token is 1,
- has_unexpected_payer_wallet is 1.

You may recommend release only when payment_ops_state is VALID_PAYMENT_READY_TO_RELEASE.

You are not allowed to execute refunds, release orders, approve compliance reviews, or submit blockchain transactions unless a separate approved action tool is explicitly available. In this demo, you only explain and recommend.
"""



def _build_prompt(question: str, context_bundle: ContextBundle) -> str:
    payload: dict[str, Any] = {
        "user_question": question,
        "historical_requested": context_bundle.historical_requested,
        "invoice_id": context_bundle.invoice_id,
        "latest_ctx_time_ms": context_bundle.latest_ctx_time_ms,
        "latest_ops_row": context_bundle.latest_ops_row,
        "ops_rows": context_bundle.ops_rows,
        "support_rows": context_bundle.support_rows,
    }
    serialized = json.dumps(payload, indent=2, sort_keys=True, default=str)
    return (
        "Use only this fetched DeltaStream context. "
        "If data is missing, clearly say context is insufficient.\n\n"
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
