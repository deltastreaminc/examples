from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .settings import settings


OPS_MV = "stablecoin_payment_ops_context_mv"
SUPPORT_MV = "support_case_summary_by_invoice_mv"


@dataclass
class ContextBundle:
    ops_rows: list[dict[str, Any]]
    support_rows: list[dict[str, Any]]
    latest_ops_row: dict[str, Any] | None
    latest_ctx_time_ms: int | None
    invoice_id: str | None
    historical_requested: bool


class DeltaStreamMCPService:
    def __init__(self) -> None:
        self._relation_cache: dict[str, str] = {
            OPS_MV: settings.ops_mv_fqn,
            SUPPORT_MV: settings.support_mv_fqn,
        }

    @staticmethod
    def _normalize_relation_name(relation_name: str) -> str:
        trimmed = relation_name.strip()
        if trimmed.startswith('"'):
            return trimmed
        parts = [part.strip() for part in trimmed.split(".") if part.strip()]
        if len(parts) == 3:
            return f'"{parts[0]}"."{parts[1]}"."{parts[2]}"'
        return trimmed

    async def fetch_context(self, user_question: str, api_token: str) -> ContextBundle:
        invoice_id = self._extract_invoice_id(user_question)
        historical_requested = self._is_historical_request(user_question)

        relation_map = await self._resolve_mv_relation_names(api_token)
        ops_fqn = relation_map.get(OPS_MV, OPS_MV)
        support_fqn = relation_map.get(SUPPORT_MV, SUPPORT_MV)

        ops_rows = await self._query_mv_rows(ops_fqn, api_token)
        support_rows = await self._query_mv_rows(support_fqn, api_token)

        ops_rows = self._apply_query_filters(ops_rows, user_question, invoice_id)
        support_rows = self._apply_query_filters(support_rows, user_question, invoice_id)

        latest_ops_row = self._pick_latest_ctx_row(ops_rows)
        latest_ctx_time_ms = None
        if latest_ops_row is not None:
            latest_ctx_time_ms = self._safe_int(latest_ops_row.get("ctx_time_ms"))

        if historical_requested:
            latest_ops_row = latest_ops_row

        return ContextBundle(
            ops_rows=ops_rows,
            support_rows=support_rows,
            latest_ops_row=latest_ops_row,
            latest_ctx_time_ms=latest_ctx_time_ms,
            invoice_id=invoice_id,
            historical_requested=historical_requested,
        )

    async def _resolve_mv_relation_names(self, api_token: str) -> dict[str, str]:
        if self._relation_cache:
            return self._relation_cache

        sql = (
            "SELECT database_name, schema_name, relation_name "
            "FROM deltastream.sys.\"relations\" "
            "WHERE type = 'materialized_view' "
            f"AND relation_name IN ('{OPS_MV}', '{SUPPORT_MV}') "
            "LIMIT 100"
        )
        payload = await self._call_tool("execute_dsql", {"sql": sql}, api_token)
        rows = payload.get("rows", [])

        relation_map: dict[str, str] = {}
        for row in rows:
            relation_name = row.get("relation_name")
            database_name = row.get("database_name")
            schema_name = row.get("schema_name")
            if relation_name and database_name and schema_name:
                relation_map[str(relation_name)] = (
                    f'"{database_name}"."{schema_name}"."{relation_name}"'
                )

        self._relation_cache = relation_map
        return relation_map

    async def _query_mv_rows(self, relation_name: str, api_token: str) -> list[dict[str, Any]]:
        normalized_relation_name = self._normalize_relation_name(relation_name)
        sql = f"SELECT * FROM {normalized_relation_name} LIMIT {settings.query_limit}"
        payload = await self._call_tool("query_mview", {"sql": sql}, api_token)
        rows = payload.get("rows", [])
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                normalized.append(row)
        return normalized

    async def _call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        api_token: str,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        async with streamablehttp_client(settings.deltastream_mcp_url, headers=headers) as transport:
            read_stream, write_stream, *_ = transport
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
        return self._extract_payload(result)

    def _extract_payload(self, tool_result: Any) -> dict[str, Any]:
        if isinstance(tool_result, dict):
            return tool_result

        structured = getattr(tool_result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured

        content = getattr(tool_result, "content", None)
        if isinstance(content, list):
            for item in content:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parsed = self._parse_json_text(text)
                    if isinstance(parsed, dict):
                        return parsed
                    if isinstance(parsed, list):
                        return {"rows": parsed}
        return {}

    @staticmethod
    def _parse_json_text(text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw_text": text}

    @staticmethod
    def _extract_invoice_id(user_question: str) -> str | None:
        match = re.search(r"\b(inv_\d+)\b", user_question.lower())
        return match.group(1) if match else None

    @staticmethod
    def _is_historical_request(user_question: str) -> bool:
        lowered = user_question.lower()
        return any(
            phrase in lowered
            for phrase in [
                "historical",
                "history",
                "previous",
                "earlier",
                "last week",
                "last month",
                "timeline",
            ]
        )

    def _apply_query_filters(
        self,
        rows: list[dict[str, Any]],
        user_question: str,
        invoice_id: str | None,
    ) -> list[dict[str, Any]]:
        lowered = user_question.lower()
        filtered = sorted(rows, key=lambda r: self._safe_int(r.get("ctx_time_ms"), default=-1), reverse=True)

        if "invoice" in lowered and not invoice_id:
            return filtered

        if invoice_id:
            filtered = [r for r in filtered if self._row_contains_value(r, invoice_id)]

        if "wrong chain" in lowered:
            filtered = [r for r in filtered if self._safe_int(r.get("has_wrong_chain")) == 1]

        if "wrong token" in lowered:
            filtered = [r for r in filtered if self._safe_int(r.get("has_wrong_token")) == 1]

        if "underpaid" in lowered or "overpaid" in lowered:
            filtered = [
                r
                for r in filtered
                if self._safe_int(r.get("total_received_minor"))
                != self._safe_int(r.get("expected_amount_minor"))
            ]

        if "exception" in lowered:
            filtered = [
                r
                for r in filtered
                if str(r.get("payment_ops_state", "")) != "VALID_PAYMENT_READY_TO_RELEASE"
            ]

        if "high-priority" in lowered or "high priority" in lowered:
            filtered = [
                r
                for r in filtered
                if str(r.get("action_priority", "")).upper() in {"P0", "P1"}
                or str(r.get("risk_band", "")).upper() in {"HIGH", "CRITICAL"}
            ]

        return filtered

    def _pick_latest_ctx_row(self, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not rows:
            return None
        with_ctx = [r for r in rows if self._safe_int(r.get("ctx_time_ms"), default=-1) >= 0]
        if not with_ctx:
            return rows[0]
        return max(with_ctx, key=lambda r: self._safe_int(r.get("ctx_time_ms"), default=-1))

    @staticmethod
    def _row_contains_value(row: dict[str, Any], needle: str) -> bool:
        lower_needle = needle.lower()
        for value in row.values():
            if lower_needle in str(value).lower():
                return True
        return False

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
