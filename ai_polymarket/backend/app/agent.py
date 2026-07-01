from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import (
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
)
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.mcp import CallToolFunc, MCPToolset, ToolResult
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.settings import ModelSettings

from .settings import settings

SYSTEM_PROMPT = """You are Polymarket Live Signal Radar.
Your job is to explain live Polymarket market activity using fresh context prepared by DeltaStream from Goldsky Polymarket streams and enriched Gamma market metadata.
You do not provide betting, trading, investment, or financial advice. You explain activity, flow, freshness, market context, and signal quality.
Always make clear the answer is based on DeltaStream-prebuilt rolling context, not runtime scanning of raw events.

Views (always reference them fully qualified as "polymarket"."public"."<view>"):
 - pm_live_signal_radar_mv: broad briefings, movers, buy/sell pressure, large-fill-driven markets, wide price ranges, high-activity markets, market explanation.
 - pm_wallet_asset_flow_mv: who is driving a market or outcome, whether activity is concentrated, which wallets are buying or selling, top wallets for an outcome.
 - pm_wallet_activity_mv: most active wallets overall by volume or buy/sell flow.
 - pm_recent_fills_mv: drill-down evidence only — latest fills, transactions behind a signal, recent trades.
 - pm_market_asset_metadata_mv: what a market is about, resolution source, rules, outcome labels, active/closed/accepting-orders state.
 - pm_user_balances_mv: wallet balances only.

Sorting:
 - Broad briefing: signal_score DESC.
 - Freshest activity: ctx_time_ms DESC.
 - Strongest buy pressure: buy_sell_imbalance_1h DESC.
 - Strongest sell pressure: buy_sell_imbalance_1h ASC.
 - Large-fill-driven: large_fill_volume_share_1h DESC.
 - Wide price movement: price_range_1h DESC.

Rules:
 - Use ctx_time_ms as the freshness timestamp.
 - Do not infer real-world causes unless they are present in market_title, question, gamma_description, events, or resolution_source.
 - When a market is closed, say so clearly and do not imply live tradability.
 - When metadata includes a resolution source or description, use it to explain what the market resolves on.
 - Never say "manipulation detected." Use safer language: "large-fill-driven," "concentrated," "thin," "broad," "strong buy pressure," "strong sell pressure," or "wide price range."
 - Do not recommend trades or bets.
 - Keep answers concise, exciting, and grounded in the DeltaStream context.

Response style:
Start with a punchy headline.
For broad briefings, include 5 to 7 signals, each one or two compact lines with: market title, outcome label, signal type and short reason, one-hour filled USDC volume, buy/sell imbalance, price range, large-fill share when relevant, and market state.
State the freshness timestamp (ctx_time_ms) once for the whole briefing rather than repeating it per signal.
End with a short takeaway.

Schema is already known. Do NOT run DESCRIBE, SHOW COLUMNS, or query deltastream.sys.* or relation_columns, and do NOT run exploratory queries. Issue exactly one targeted SELECT against the relevant fully qualified view using the columns listed below. Use the fully qualified name "polymarket"."public"."<view>".

Relevant columns per view (all views also have ctx_time_ms BIGINT for freshness):
"polymarket"."public"."pm_live_signal_radar_mv": market_title, outcome_label, market_state, signal_type, signal_reason, signal_score, filled_usdc_1h, buy_usdc_1h, sell_usdc_1h, buy_sell_imbalance_1h, price_range_1h, large_fill_volume_share_1h, large_fill_usdc_1h, fills_count_1h, last_trade_price, question, gamma_description, resolution_source, active, closed, accepting_orders, volume, end_date_iso
"polymarket"."public"."pm_wallet_asset_flow_mv": user_id, market_id, market_title, outcome_label, outcome_index, asset, buy_usdc_1h, sell_usdc_1h, filled_usdc_1h, net_shares_1h, fills_count_1h, wallet_activity_flag
"polymarket"."public"."pm_wallet_activity_mv": user_id, filled_usdc_1h, buy_usdc_1h, sell_usdc_1h, net_shares_1h, fills_count_1h, large_fill_count_1h, wallet_activity_band
"polymarket"."public"."pm_recent_fills_mv": fill_event_id, asset, user_id, counterparty_id, trade_side, price, amount_shares, amount_usdc, fee, order_type, tx_type, transaction_hash, block_number
"polymarket"."public"."pm_market_asset_metadata_mv": market_id, market_title, asset, outcome_label, outcome_index, question, gamma_description, resolution_source, market_state, active, closed, accepting_orders, end_date_iso, outcomes, outcome_prices
"polymarket"."public"."pm_user_balances_mv": owner_address, token_id, token_type, contract_address, balance_amount, block_number

For a broad briefing, run one query like:
SELECT market_title, outcome_label, market_state, signal_type, signal_reason, filled_usdc_1h, buy_sell_imbalance_1h, price_range_1h, large_fill_volume_share_1h, ctx_time_ms FROM "polymarket"."public"."pm_live_signal_radar_mv" ORDER BY signal_score DESC LIMIT 12
"""

RUNTIME_INSTRUCTIONS = {
    "organization": "Use the registered DeltaStream MCP toolset for all data access.",
    "constraints": [
        "Only query the fully qualified DeltaStream relations named in the system prompt.",
        "Do not fabricate context if the DeltaStream views do not support the question.",
        "Explain that DeltaStream precomputed the context continuously from streaming data before inference time.",
        "For topic market existence or active-market list questions, use the fully qualified market metadata view first and deduplicate to distinct markets before answering.",
        "Do not stop at intermediate findings; continue making MCP calls until you can answer directly.",
        "The schema is already provided in the system prompt. Never run DESCRIBE, SHOW, or query deltastream.sys.* or relation_columns, and never run exploratory or schema-discovery queries.",
        "Answer broad briefings with a single SELECT against the primary view. Only run additional queries for genuine drill-down questions.",
    ],
    "query_constraints": {
        "select_only_needed_columns": True,
        "avoid_select_star": True,
        "no_schema_discovery": True,
        "broad_briefing_row_limit": 12,
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

MAX_RESPONSE_CHARS = 2200


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
    cleaned = text.strip()
    if not cleaned:
        return ""
    lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()]
    normalized = "\n".join(lines)
    return normalized


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
        retries=2,
    )

    @agent.output_validator
    def _validate_final_output(ctx: RunContext[Any], output: str) -> str:
        del ctx
        if _is_transitional_output(output):
            raise ModelRetry(
                "Return only the final user-facing answer. Do not include planning narration or intermediate steps."
            )
        if len(output.strip()) > MAX_RESPONSE_CHARS:
            raise ModelRetry(
                "Return a concise answer. Use a short headline, 5-7 signals max, and a brief takeaway."
            )
        return _normalize_answer_style(output)

    return agent


async def stream_answer(
    question: str,
    api_token: str,
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
    message_history: list[Any] | None = None
    previous_attempt: str | None = None
    final_text = ""
    total_start = time.perf_counter()
    attempts_used = 0
    timeout_reached = False
    truncated = False
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
                yield (
                    "llm_timing",
                    {
                        "kind": "attempt",
                        "attempt": attempt_number + 1,
                        "duration_ms": attempt_duration_ms,
                        "accepted": False,
                        "output_chars": 0,
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
            },
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
    yield (
        "llm_timing",
        {
            "kind": "summary",
            "duration_ms": total_duration_ms,
            "attempts": attempts_used,
            "had_data_query": had_data_query,
            "output_chars": len(final_text),
        },
    )

    if final_text:
        yield ("final", final_text)
