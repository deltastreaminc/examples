from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .settings import settings


PRIMARY_MV = "pm_live_signal_radar_mv"
WALLET_FLOW_MV = "pm_wallet_asset_flow_mv"
WALLET_ACTIVITY_MV = "pm_wallet_activity_mv"
RECENT_FILLS_MV = "pm_recent_fills_mv"
METADATA_MV = "pm_market_asset_metadata_mv"
BALANCES_MV = "pm_user_balances_mv"

RELATION_NAMES = {
    PRIMARY_MV: PRIMARY_MV,
    WALLET_FLOW_MV: WALLET_FLOW_MV,
    WALLET_ACTIVITY_MV: WALLET_ACTIVITY_MV,
    RECENT_FILLS_MV: RECENT_FILLS_MV,
    METADATA_MV: METADATA_MV,
    BALANCES_MV: BALANCES_MV,
}

MODE_BROAD = "broad_summary"
MODE_FRESHEST = "freshest_summary"
MODE_DRIVER = "driver_analysis"
MODE_EVIDENCE = "fill_evidence"
MODE_METADATA = "market_lookup"
MODE_BALANCES = "balance_lookup"


@dataclass
class ContextBundle:
    question_mode: str
    target_asset: str | None
    target_market_title: str | None
    target_outcome_label: str | None
    latest_ctx_time_ms: int | None
    queried_views: list[str]
    primary_rows: list[dict[str, Any]]
    wallet_flow_rows: list[dict[str, Any]]
    wallet_activity_rows: list[dict[str, Any]]
    recent_fill_rows: list[dict[str, Any]]
    metadata_rows: list[dict[str, Any]]
    balance_rows: list[dict[str, Any]]


class DeltaStreamMCPService:
    def __init__(self) -> None:
        self._relation_cache: dict[str, str] = {}

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
        relation_map = await self._resolve_mv_relation_names(api_token)
        question_mode = self._determine_mode(user_question)
        target_asset = self._extract_asset(user_question)

        metadata_fqn = relation_map.get(METADATA_MV, METADATA_MV)
        metadata_lookup_rows = await self._query_mv_rows(
            metadata_fqn,
            settings.query_limit,
            api_token,
            order_by="updated_at DESC",
        )
        target_market_title, target_outcome_label = self._extract_targets_from_metadata(
            user_question, metadata_lookup_rows, target_asset
        )
        metadata_rows: list[dict[str, Any]] = []

        queried_views: list[str] = []
        primary_rows: list[dict[str, Any]] = []
        wallet_flow_rows: list[dict[str, Any]] = []
        wallet_activity_rows: list[dict[str, Any]] = []
        recent_fill_rows: list[dict[str, Any]] = []
        balance_rows: list[dict[str, Any]] = []

        if question_mode in {MODE_BROAD, MODE_FRESHEST}:
            primary_rows = await self._fetch_primary_rows(user_question, relation_map, api_token)
            queried_views.append(PRIMARY_MV)

        elif question_mode == MODE_DRIVER:
            wallet_flow_rows = await self._fetch_wallet_flow_rows(
                user_question,
                relation_map,
                api_token,
                target_asset,
                target_market_title,
                target_outcome_label,
            )
            queried_views.append(WALLET_FLOW_MV)

            user_ids = [str(row.get("user_id")) for row in wallet_flow_rows if row.get("user_id")]
            if user_ids:
                wallet_activity_rows = await self._fetch_wallet_activity_rows(
                    relation_map,
                    api_token,
                    user_ids,
                )
                queried_views.append(WALLET_ACTIVITY_MV)

        elif question_mode == MODE_EVIDENCE:
            recent_fill_rows = await self._fetch_recent_fill_rows(
                relation_map,
                api_token,
                target_asset,
                target_market_title,
                target_outcome_label,
            )
            queried_views.extend([RECENT_FILLS_MV, METADATA_MV])

        elif question_mode == MODE_METADATA:
            metadata_rows = self._filter_metadata_rows(
                metadata_lookup_rows,
                user_question,
                target_asset,
                target_market_title,
                target_outcome_label,
            )
            queried_views.append(METADATA_MV)

        elif question_mode == MODE_BALANCES:
            balance_rows = await self._fetch_balance_rows(relation_map, api_token, user_question, target_asset)
            queried_views.append(BALANCES_MV)

        latest_ctx_time_ms = self._latest_ctx_time(
            primary_rows,
            wallet_flow_rows,
            wallet_activity_rows,
            recent_fill_rows,
            metadata_rows,
            balance_rows,
        )

        return ContextBundle(
            question_mode=question_mode,
            target_asset=target_asset,
            target_market_title=target_market_title,
            target_outcome_label=target_outcome_label,
            latest_ctx_time_ms=latest_ctx_time_ms,
            queried_views=queried_views,
            primary_rows=primary_rows,
            wallet_flow_rows=wallet_flow_rows,
            wallet_activity_rows=wallet_activity_rows,
            recent_fill_rows=recent_fill_rows,
            metadata_rows=metadata_rows,
            balance_rows=balance_rows,
        )

    async def _fetch_primary_rows(
        self,
        user_question: str,
        relation_map: dict[str, str],
        api_token: str,
    ) -> list[dict[str, Any]]:
        relation_name = relation_map.get(PRIMARY_MV, PRIMARY_MV)
        rows = await self._query_mv_rows(
            relation_name,
            settings.primary_query_limit,
            api_token,
            order_by="ctx_time_ms DESC",
        )
        latest_per_asset = self._latest_row_per_asset(rows)
        filtered = self._filter_primary_rows(latest_per_asset, user_question)
        if self._is_freshest_request(user_question):
            return sorted(filtered, key=lambda row: self._safe_int(row.get("ctx_time_ms")), reverse=True)[:10]
        return sorted(filtered, key=lambda row: self._safe_float(row.get("signal_score")), reverse=True)[:10]

    async def _fetch_wallet_flow_rows(
        self,
        user_question: str,
        relation_map: dict[str, str],
        api_token: str,
        target_asset: str | None,
        target_market_title: str | None,
        target_outcome_label: str | None,
    ) -> list[dict[str, Any]]:
        relation_name = relation_map.get(WALLET_FLOW_MV, WALLET_FLOW_MV)
        rows = await self._query_mv_rows(
            relation_name,
            settings.query_limit,
            api_token,
            order_by="ctx_time_ms DESC",
        )
        filtered = self._filter_wallet_flow_rows(
            rows,
            user_question,
            target_asset,
            target_market_title,
            target_outcome_label,
        )
        latest_per_wallet = self._latest_row_per_key(filtered, "user_asset_key")
        return sorted(latest_per_wallet, key=lambda row: self._safe_float(row.get("filled_usdc_1h")), reverse=True)[:10]

    async def _fetch_wallet_activity_rows(
        self,
        relation_map: dict[str, str],
        api_token: str,
        user_ids: list[str],
    ) -> list[dict[str, Any]]:
        relation_name = relation_map.get(WALLET_ACTIVITY_MV, WALLET_ACTIVITY_MV)
        rows = await self._query_mv_rows(
            relation_name,
            settings.query_limit,
            api_token,
            order_by="ctx_time_ms DESC",
        )
        latest_per_wallet = self._latest_row_per_key(rows, "user_id")
        wanted = {user_id.lower() for user_id in user_ids}
        filtered = [row for row in latest_per_wallet if str(row.get("user_id", "")).lower() in wanted]
        return sorted(filtered, key=lambda row: self._safe_float(row.get("filled_usdc_1h")), reverse=True)[:10]

    async def _fetch_recent_fill_rows(
        self,
        relation_map: dict[str, str],
        api_token: str,
        target_asset: str | None,
        target_market_title: str | None,
        target_outcome_label: str | None,
    ) -> list[dict[str, Any]]:
        relation_name = relation_map.get(RECENT_FILLS_MV, RECENT_FILLS_MV)
        rows = await self._query_mv_rows(
            relation_name,
            settings.query_limit,
            api_token,
            order_by="ctx_time_ms DESC",
        )
        filtered = rows
        if target_asset:
            filtered = [row for row in filtered if str(row.get("asset")) == target_asset]
        if not target_asset and (target_market_title or target_outcome_label):
            asset_ids = await self._lookup_assets_for_market(relation_map, api_token, target_market_title, target_outcome_label)
            if asset_ids:
                wanted = {asset.lower() for asset in asset_ids}
                filtered = [row for row in filtered if str(row.get("asset", "")).lower() in wanted]
        return sorted(filtered, key=lambda row: self._safe_int(row.get("ctx_time_ms")), reverse=True)[:15]

    async def _fetch_balance_rows(
        self,
        relation_map: dict[str, str],
        api_token: str,
        user_question: str,
        target_asset: str | None,
    ) -> list[dict[str, Any]]:
        relation_name = relation_map.get(BALANCES_MV, BALANCES_MV)
        rows = await self._query_mv_rows(
            relation_name,
            settings.query_limit,
            api_token,
            order_by="ctx_time_ms DESC",
        )
        lowered = user_question.lower()
        filtered = rows
        if target_asset:
            filtered = [row for row in filtered if str(row.get("token_id")) == target_asset]
        if "owner" in lowered or "address" in lowered:
            owner_match = re.search(r"\b0x[a-fA-F0-9]{6,}\b", user_question)
            if owner_match:
                owner = owner_match.group(0).lower()
                filtered = [
                    row for row in filtered if str(row.get("owner_address", "")).lower() == owner
                ]
        latest_per_id = self._latest_row_per_key(filtered, "id")
        return sorted(latest_per_id, key=lambda row: self._safe_int(row.get("ctx_time_ms")), reverse=True)[:20]

    async def _lookup_assets_for_market(
        self,
        relation_map: dict[str, str],
        api_token: str,
        target_market_title: str | None,
        target_outcome_label: str | None,
    ) -> list[str]:
        relation_name = relation_map.get(METADATA_MV, METADATA_MV)
        rows = await self._query_mv_rows(relation_name, settings.query_limit, api_token)
        filtered = self._filter_metadata_rows(rows, "", None, target_market_title, target_outcome_label)
        return [str(row.get("asset")) for row in filtered if row.get("asset")]

    async def _resolve_mv_relation_names(self, api_token: str) -> dict[str, str]:
        if self._relation_cache:
            return self._relation_cache

        mv_names = ", ".join(f"'{name}'" for name in RELATION_NAMES)
        sql = (
            "SELECT database_name, schema_name, relation_name "
            "FROM deltastream.sys.\"relations\" "
            "WHERE type = 'materialized_view' "
            f"AND relation_name IN ({mv_names}) "
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
                relation_map[str(relation_name)] = f'"{database_name}"."{schema_name}"."{relation_name}"'

        self._relation_cache = relation_map or dict(RELATION_NAMES)
        return self._relation_cache

    async def _query_mv_rows(
        self,
        relation_name: str,
        limit: int,
        api_token: str,
        order_by: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_relation_name = self._normalize_relation_name(relation_name)
        sql = f"SELECT * FROM {normalized_relation_name}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        sql += f" LIMIT {limit}"
        payload = await self._call_tool("query_mview", {"sql": sql}, api_token)
        rows = payload.get("rows", [])
        return [row for row in rows if isinstance(row, dict)]

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
    def _determine_mode(user_question: str) -> str:
        lowered = user_question.lower()
        if any(phrase in lowered for phrase in ["who is driving", "who's driving", "which wallets", "who bought", "who sold"]):
            return MODE_DRIVER
        if any(phrase in lowered for phrase in ["raw fills", "recent fills", "examples", "transactions", "evidence"]):
            return MODE_EVIDENCE
        if any(phrase in lowered for phrase in ["metadata", "market url", "category", "slug"]):
            return MODE_METADATA
        if any(phrase in lowered for phrase in ["balance", "balances", "owner address", "wallet balance"]):
            return MODE_BALANCES
        if any(phrase in lowered for phrase in ["freshest", "latest activity", "most recent"]):
            return MODE_FRESHEST
        return MODE_BROAD

    @staticmethod
    def _extract_asset(user_question: str) -> str | None:
        match = re.search(r"\b\d{4,}\b", user_question)
        return match.group(0) if match else None

    def _extract_targets_from_metadata(
        self,
        user_question: str,
        metadata_rows: list[dict[str, Any]],
        target_asset: str | None,
    ) -> tuple[str | None, str | None]:
        filtered = self._filter_metadata_rows(metadata_rows, user_question, target_asset, None, None)
        if not filtered:
            return None, None
        row = filtered[0]
        market_title = row.get("market_title")
        outcome_label = row.get("outcome_label")
        return (
            str(market_title) if isinstance(market_title, str) else None,
            str(outcome_label) if isinstance(outcome_label, str) else None,
        )

    def _filter_primary_rows(self, rows: list[dict[str, Any]], user_question: str) -> list[dict[str, Any]]:
        lowered = user_question.lower()
        filtered = rows
        if "buy pressure" in lowered:
            filtered = [row for row in filtered if self._safe_float(row.get("buy_sell_imbalance_1h")) > 0]
        if "sell pressure" in lowered:
            filtered = [row for row in filtered if self._safe_float(row.get("buy_sell_imbalance_1h")) < 0]
        if "large-fill-driven" in lowered or "large fill driven" in lowered:
            filtered = [
                row for row in filtered if str(row.get("signal_type", "")).upper() == "LARGE_FILL_DRIVEN"
            ]
        return filtered

    def _filter_wallet_flow_rows(
        self,
        rows: list[dict[str, Any]],
        user_question: str,
        target_asset: str | None,
        target_market_title: str | None,
        target_outcome_label: str | None,
    ) -> list[dict[str, Any]]:
        lowered = user_question.lower()
        filtered = rows
        if target_asset:
            filtered = [row for row in filtered if str(row.get("asset")) == target_asset]
        if target_market_title:
            filtered = [
                row
                for row in filtered
                if str(row.get("market_title", "")).lower() == target_market_title.lower()
            ]
        if target_outcome_label:
            filtered = [
                row
                for row in filtered
                if str(row.get("outcome_label", "")).lower() == target_outcome_label.lower()
            ]
        if "buy" in lowered and "sell" not in lowered:
            filtered = [row for row in filtered if self._safe_float(row.get("buy_usdc_1h")) > 0]
        if "sell" in lowered and "buy" not in lowered:
            filtered = [row for row in filtered if self._safe_float(row.get("sell_usdc_1h")) > 0]
        return filtered

    def _filter_metadata_rows(
        self,
        rows: list[dict[str, Any]],
        user_question: str,
        target_asset: str | None,
        target_market_title: str | None,
        target_outcome_label: str | None,
    ) -> list[dict[str, Any]]:
        lowered = user_question.lower()
        filtered = rows
        if target_asset:
            filtered = [row for row in filtered if str(row.get("asset")) == target_asset]
        if target_market_title:
            filtered = [
                row
                for row in filtered
                if str(row.get("market_title", "")).lower() == target_market_title.lower()
            ]
        if target_outcome_label:
            filtered = [
                row
                for row in filtered
                if str(row.get("outcome_label", "")).lower() == target_outcome_label.lower()
            ]
        if filtered:
            return filtered
        if not lowered:
            return rows
        ranked = sorted(
            rows,
            key=lambda row: self._metadata_match_score(row, lowered),
            reverse=True,
        )
        best_score = self._metadata_match_score(ranked[0], lowered) if ranked else 0
        if best_score <= 0:
            return rows[:10]
        return [row for row in ranked if self._metadata_match_score(row, lowered) == best_score][:10]

    @staticmethod
    def _metadata_match_score(row: dict[str, Any], lowered_question: str) -> int:
        haystacks = [
            str(row.get("market_title", "")).lower(),
            str(row.get("outcome_label", "")).lower(),
            str(row.get("slug", "")).lower(),
            str(row.get("market_id", "")).lower(),
            str(row.get("condition_id", "")).lower(),
            str(row.get("asset", "")).lower(),
        ]
        score = 0
        for haystack in haystacks:
            if haystack and haystack in lowered_question:
                score += len(haystack)
        return score

    @staticmethod
    def _latest_row_per_asset(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            asset = str(row.get("asset", ""))
            if not asset:
                continue
            current = latest.get(asset)
            if current is None or DeltaStreamMCPService._safe_int(row.get("ctx_time_ms")) > DeltaStreamMCPService._safe_int(current.get("ctx_time_ms")):
                latest[asset] = row
        return list(latest.values())

    @staticmethod
    def _latest_row_per_key(rows: list[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.get(key_name, ""))
            if not key:
                continue
            current = latest.get(key)
            if current is None or DeltaStreamMCPService._safe_int(row.get("ctx_time_ms")) > DeltaStreamMCPService._safe_int(current.get("ctx_time_ms")):
                latest[key] = row
        return list(latest.values())

    @staticmethod
    def _is_freshest_request(user_question: str) -> bool:
        lowered = user_question.lower()
        return any(phrase in lowered for phrase in ["freshest", "most recent", "latest activity"])

    @staticmethod
    def _latest_ctx_time(*row_groups: list[dict[str, Any]]) -> int | None:
        values = [
            DeltaStreamMCPService._safe_int(row.get("ctx_time_ms"), default=-1)
            for rows in row_groups
            for row in rows
        ]
        values = [value for value in values if value >= 0]
        return max(values) if values else None

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
