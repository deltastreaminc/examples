"""Chat backend with pydantic-ai and DeltaStream MCP integration."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from .config import AppConfig
from .constants import ALLOWED_MVIEW_FQNS

_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|merge|replace)\b",
    re.IGNORECASE,
)
_FROM_JOIN_PATTERN = re.compile(r"\b(?:from|join)\s+([^\s,;]+)", re.IGNORECASE)
_CTE_PATTERN = re.compile(r"\bwith\b", re.IGNORECASE)


class AgentAnswer(BaseModel):
    """Structured answer for reliable Streamlit rendering."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(description="Natural language answer for the user")
    generated_sql: str = Field(description="SQL used to answer the question")
    evidence_relations: list[str] = Field(default_factory=list)


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatResult:
    answer: str
    generated_sql: str
    evidence_relations: list[str]
    tool_calls: int
    tool_failures: list[str]


class QueryPolicyError(RuntimeError):
    """Raised when the generated SQL violates safety policy."""


class MCPConnectionError(RuntimeError):
    """Raised when MCP initialization fails."""


class ChatBackend:
    """Small interface so the UI can swap chat providers later."""

    def ask(self, prompt: str, history: list[ChatMessage]) -> ChatResult:  # pragma: no cover - interface
        raise NotImplementedError


class PydanticAIDemoBackend(ChatBackend):
    """pydantic-ai backend configured for Anthropic and DeltaStream MCP."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._last_tool_failures: list[str] = []

    def _system_prompt(self) -> str:
        return (
            "You are a Checkout Save Agent for an e-commerce business.\n\n"
            "Your job is to recover revenue while customers are still in checkout.\n\n"
            "You use fresh DeltaStream checkout context to decide whether the business "
            "should offer free shipping, prompt for a backup payment method, offer a "
            "policy-approved discount, send a checkout assistance message, escalate "
            "inventory issues, or continue monitoring.\n\n"
            "You are not a generic customer support chatbot. You are an operations "
            "decision agent focused on saving carts and increasing conversion while "
            "respecting incentive policy and payment state.\n\n"
            "Always use the DeltaStream context tool before making any cart-specific "
            "recommendation.\n\n"
            "Tool guidance:\n"
            "Use the DeltaStream context tool to retrieve the latest checkout-save "
            "context for a cart.\n"
            "The context comes from checkout.public.checkout_save_agent_context_mv and "
            "is continuously computed from customer profile, cart state, checkout "
            "activity, payment attempts, and incentive policy.\n"
            "Always query by cart_id.\n"
            "The tool may return multiple rows. Sort by context_event_ts_ms descending "
            "and use only the latest row.\n"
            "Recommended query:\n"
            "SELECT * FROM checkout.public.checkout_save_agent_context_mv "
            "WHERE cart_id = '<cart_id>' "
            "ORDER BY context_event_ts_ms DESC LIMIT 1;\n"
            "The latest context row contains fields such as abandonment_risk, "
            "recommended_recovery_action, safe_next_best_action, "
            "checkout_still_recoverable, checkout_already_converted, "
            "payment_failure_count, soft_decline_count, hard_decline_count, "
            "backup_payment_available, shipping_cost_usd, "
            "free_shipping_incentive_eligible, discount_incentive_eligible, "
            "proactive_message_recommended, and context_event_ts_ms.\n"
            "Do not make a cart-specific recommendation until the latest context row "
            "has been retrieved.\n\n"
            "The DeltaStream context is the source of truth. It is prebuilt from "
            "customer profile, cart state, checkout activity, payment attempts, and "
            "incentive policy.\n\n"
            "Rules:\n\n"
            "1. Always query by cart_id when a cart_id is available.\n\n"
            "2. The context tool can return multiple rows for a cart_id. Sort rows by "
            "context_event_ts_ms descending and use only the latest row.\n\n"
            "3. Do not recommend an action from stale context if a newer row exists.\n\n"
            "4. If checkout_already_converted = 1, do not recommend a recovery action. "
            "Say no action is needed.\n\n"
            "5. If checkout_still_recoverable = 0, do not offer an incentive. Explain "
            "why the checkout is not recoverable.\n\n"
            "6. If inventory_available = false, do not offer free shipping or discounts. "
            "Recommend inventory escalation or a replacement item flow.\n\n"
            "7. If hard_decline_count > 0, recommend a new payment method. Do not offer "
            "discounts before payment is recoverable.\n\n"
            "8. If recommended_recovery_action is available, treat it as the primary "
            "recommendation.\n\n"
            "9. Use safe_next_best_action as the basis for the explanation. You may "
            "rephrase it, but do not contradict it.\n\n"
            "10. Keep answers concise and action-oriented.\n\n"
            "Default answer format:\n\n"
            "Decision:\n"
            "<one sentence decision>\n\n"
            "Why:\n"
            "<brief explanation using the latest DeltaStream context fields>\n\n"
            "Recommended action:\n"
            "<what the business should do next>\n\n"
            "Customer message:\n"
            "<include only if the user asks for a customer-facing message or "
            "proactive_message_recommended = 1>"
        )

    async def _process_tool_call(
        self,
        _ctx: Any,
        call_tool: Any,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        violations: list[str] = []
        for text in _extract_string_values(arguments):
            if _looks_like_sql(text):
                try:
                    _validate_sql_policy(text)
                except QueryPolicyError as exc:
                    violations.append(str(exc))
        if violations:
            self._last_tool_failures.extend(f"{tool_name}: {item}" for item in violations)
            return {
                "error": "Query blocked by policy",
                "details": violations,
                "allowed_relations": list(ALLOWED_MVIEW_FQNS),
            }
        try:
            response = await call_tool(tool_name, arguments)
        except Exception as exc:  # noqa: BLE001
            self._last_tool_failures.append(f"{tool_name}: {exc}")
            raise

        tool_error = _extract_tool_error(response)
        if tool_error:
            self._last_tool_failures.append(f"{tool_name}: {tool_error}")
        return response

    async def _run_async(self, prompt: str, history: list[ChatMessage]) -> ChatResult:
        self._last_tool_failures = []
        api_token = self._config.api_token.get_secret_value()
        anthropic_client = httpx.AsyncClient(
            headers={
                # demo Anthropic gateway expects bearer auth.
                "Authorization": f"Bearer {api_token}",
                # keep x-api-key for compatibility with Anthropic-compatible proxies.
                "x-api-key": api_token,
            },
            verify=not self._config.insecure_tls,
            timeout=120.0,
        )
        provider = AnthropicProvider(
            api_key=api_token,
            base_url=self._config.anthropic_base_url,
            http_client=anthropic_client,
        )
        model = AnthropicModel(self._config.anthropic_model, provider=provider)

        mcp_http_client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_token}"},
            verify=not self._config.insecure_tls,
            timeout=120.0,
        )
        server = MCPServerStreamableHTTP(
            self._config.deltastream_mcp_url,
            http_client=mcp_http_client,
            include_instructions=True,
            max_retries=2,
            process_tool_call=self._process_tool_call,
        )

        agent = Agent(
            model,
            instructions=self._system_prompt(),
            output_type=AgentAnswer,
            toolsets=[server],
            tool_retries=1,
        )

        history_text = "\n".join(f"{msg.role.upper()}: {msg.content}" for msg in history[-10:])
        full_prompt = (
            "Conversation history:\n"
            f"{history_text}\n\n"
            "User question:\n"
            f"{prompt}"
        )

        try:
            async with agent:
                try:
                    result = await agent.run(full_prompt)
                except ExceptionGroup as exc:
                    raise MCPConnectionError(
                        _format_exception_group(exc, self._last_tool_failures)
                    ) from exc
                except Exception as exc:  # noqa: BLE001
                    raise MCPConnectionError(
                        _format_single_exception(exc, self._last_tool_failures)
                    ) from exc
        finally:
            await mcp_http_client.aclose()
            await anthropic_client.aclose()

        output = result.output
        _validate_sql_policy(output.generated_sql)
        usage = result.usage()
        return ChatResult(
            answer=output.answer,
            generated_sql=output.generated_sql,
            evidence_relations=output.evidence_relations,
            tool_calls=int(getattr(usage, "tool_calls", 0) or 0),
            tool_failures=_unique_non_empty(self._last_tool_failures),
        )

    def ask(self, prompt: str, history: list[ChatMessage]) -> ChatResult:
        return asyncio.run(self._run_async(prompt=prompt, history=history))


def _extract_string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        items: list[str] = []
        for entry in value:
            items.extend(_extract_string_values(entry))
        return items
    if isinstance(value, dict):
        items = []
        for entry in value.values():
            items.extend(_extract_string_values(entry))
        return items
    return []


def _looks_like_sql(text: str) -> bool:
    compact = text.strip().lower()
    return compact.startswith("select") or ("select" in compact and "from" in compact)


def _normalize_relation_name(raw_name: str) -> str:
    cleaned = raw_name.strip().rstrip(",;")
    for bracket in ("`", '"'):
        cleaned = cleaned.replace(bracket, "")
    return cleaned.lower()


def _validate_sql_policy(sql: str) -> None:
    normalized_sql = sql.strip()
    if not normalized_sql:
        raise QueryPolicyError("Agent did not generate SQL.")
    if not normalized_sql.lower().startswith("select"):
        raise QueryPolicyError("Only SELECT statements are allowed.")
    if _FORBIDDEN_SQL.search(normalized_sql):
        raise QueryPolicyError("Mutation SQL is not allowed in this starter.")
    if _CTE_PATTERN.search(normalized_sql):
        raise QueryPolicyError("CTE queries are disabled in this starter for simplicity.")
    if re.search(r"\blimit\s+\d+\b", normalized_sql, re.IGNORECASE) is None:
        raise QueryPolicyError("Queries must include a LIMIT clause.")

    relation_names = [
        _normalize_relation_name(match.group(1)) for match in _FROM_JOIN_PATTERN.finditer(normalized_sql)
    ]
    if not relation_names:
        raise QueryPolicyError(
            "Query must include FROM on one of: " + ", ".join(ALLOWED_MVIEW_FQNS)
        )

    allowed = {name.lower() for name in ALLOWED_MVIEW_FQNS}
    for relation in relation_names:
        if relation not in allowed:
            raise QueryPolicyError(
                "Only allowed relations can be queried. "
                f"Found relation: {relation}. Allowed: {', '.join(ALLOWED_MVIEW_FQNS)}"
            )


def _format_exception_group(exc: ExceptionGroup, tool_failures: list[str]) -> str:
    details: list[str] = []

    def collect(group: ExceptionGroup) -> None:
        for item in group.exceptions:
            if isinstance(item, ExceptionGroup):
                collect(item)
            else:
                details.append(str(item))

    collect(exc)
    unique = [msg for msg in dict.fromkeys(msg.strip() for msg in details if msg.strip())]
    return _combine_error_text(unique, tool_failures, str(exc))


def _format_single_exception(exc: Exception, tool_failures: list[str]) -> str:
    return _combine_error_text([str(exc)], tool_failures, str(exc))


def _extract_tool_error(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("error", "message", "detail"):
            maybe = value.get(key)
            if isinstance(maybe, str) and maybe.strip():
                return maybe.strip()
        details = value.get("details")
        if isinstance(details, list):
            text_details = [str(item).strip() for item in details if str(item).strip()]
            if text_details:
                return "; ".join(text_details)
    return None


def _unique_non_empty(values: list[str]) -> list[str]:
    return [msg for msg in dict.fromkeys(msg.strip() for msg in values if msg and msg.strip())]


def _combine_error_text(primary_errors: list[str], tool_failures: list[str], fallback: str) -> str:
    primary = _unique_non_empty(primary_errors)
    failures = _unique_non_empty(tool_failures)
    parts: list[str] = []
    if primary:
        parts.append("; ".join(primary))
    if failures:
        parts.append("Tool failures: " + " | ".join(failures))
    if parts:
        return " | ".join(parts)
    return fallback
