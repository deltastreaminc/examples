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
            "You are a DeltaStream analytics assistant focused on pageview data.\n\n"
            "You answer questions using only starter.public.pageviews_mview.\n\n"
            "Always use a SQL query to ground your answer in data from the allowed "
            "materialized view.\n\n"
            "Rules:\n\n"
            "1. Query only starter.public.pageviews_mview.\n\n"
            "2. Only use SELECT queries, and always include LIMIT.\n\n"
            "3. Prefer concise aggregations for counts and top pages/users.\n\n"
            "4. If the user asks for recent activity, order by viewtime DESC.\n\n"
            "5. If results are empty, say so clearly and suggest checking that datagen "
            "is running for the pageviews topic.\n\n"
            "Example queries:\n"
            "SELECT * FROM starter.public.pageviews_mview ORDER BY viewtime DESC LIMIT 20;\n"
            "SELECT pageid, COUNT(*) AS views FROM starter.public.pageviews_mview "
            "GROUP BY pageid ORDER BY views DESC LIMIT 20;\n"
            "SELECT userid, COUNT(*) AS views FROM starter.public.pageviews_mview "
            "GROUP BY userid ORDER BY views DESC LIMIT 20;\n\n"
            "Answer format:\n"
            "- Keep it short and factual.\n"
            "- Include a brief summary of what the query shows."
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
