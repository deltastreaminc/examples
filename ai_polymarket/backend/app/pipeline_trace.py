from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


SYSTEM_PAGE_SIZE = 100
RELATION_COLUMN_LIMIT = 500
DEFAULT_MAX_DEPTH = 20
DEFAULT_EVENT_HOURS = 24
DEFAULT_RECENT_MINUTES = 30
PRINT_SAMPLE_LIMIT = 10
PRINT_FLOW_TIMEOUT_SECONDS = 30

TIME_COLUMN_PREFERENCES = (
    "ctx_time_ms",
    "snapshot_time_ms",
    "latest_event_time_ms",
    "transition_time_ms",
    "last_seen_ms",
    "updated_at",
    "window_end",
)

RUNNING_STATES = {"running", "starting"}


class TraceError(RuntimeError):
    pass


@dataclass
class RelationRef:
    database: str
    schema: str
    name: str
    relation_type: str | None = None
    state: str | None = None
    store_name: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    @property
    def fqn(self) -> str:
        return quote_relation_fqn(self.database, self.schema, self.name)

    @property
    def short_name(self) -> str:
        return f"{self.database}.{self.schema}.{self.name}"


@dataclass
class QueryEvent:
    timestamp: str | None
    event_type: str | None
    actor: str | None
    messages: str | None


@dataclass
class QueryInfo:
    query_id: str
    current_state: str | None
    intended_state: str | None
    updated_at: str | None
    sql: str | None
    sources: list[RelationRef] = field(default_factory=list)
    sink: RelationRef | None = None


@dataclass
class RelationProbe:
    status: str
    latest_value: str | None = None
    latest_at: str | None = None
    checked_field: str | None = None
    observed_rows: int | None = None
    details: str | None = None


@dataclass
class QueryProbe:
    status: str
    recent_events: list[QueryEvent] = field(default_factory=list)
    restart_reasons: list[str] = field(default_factory=list)
    restart_count: int = 0
    error_count: int = 0


@dataclass
class TraceNode:
    relation: RelationRef
    relation_probe: RelationProbe
    upstream_query: QueryInfo | None = None
    query_probe: QueryProbe | None = None
    source_nodes: list["TraceNode"] = field(default_factory=list)


class DeltaStreamMCPClient:
    def __init__(
        self,
        *,
        mcp_url: str,
        api_token: str,
        database: str | None,
        schema: str | None,
        store: str | None,
    ) -> None:
        self._mcp_url = mcp_url
        self._api_token = api_token
        self._database = database
        self._schema = schema
        self._store = store
        self._transport_cm: Any | None = None
        self._session_cm: Any | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "DeltaStreamMCPClient":
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }
        self._transport_cm = streamablehttp_client(self._mcp_url, headers=headers)
        transport = await self._transport_cm.__aenter__()
        read_stream, write_stream, *_ = transport
        self._session_cm = ClientSession(read_stream, write_stream)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(exc_type, exc, tb)
        if self._transport_cm is not None:
            await self._transport_cm.__aexit__(exc_type, exc, tb)

    async def execute_dsql(
        self,
        sql: str,
        *,
        database: str | None = None,
        schema: str | None = None,
        store: str | None = None,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {"sql": sql}
        if database or self._database:
            arguments["database"] = database or self._database
        if schema or self._schema:
            arguments["schema"] = schema or self._schema
        if store or self._store:
            arguments["store"] = store or self._store
        return await self._call_tool("execute_dsql", arguments)

    async def query_mview(self, sql: str) -> list[dict[str, Any]]:
        payload = await self._call_tool("query_mview", {"sql": sql})
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        rows = payload.get("rows", [])
        return [row for row in rows if isinstance(row, dict)]

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | list[Any]:
        if self._session is None:
            raise TraceError("MCP session is not initialized")
        result = await self._session.call_tool(tool_name, arguments)
        return extract_tool_payload(result)


class PipelineTracer:
    def __init__(
        self,
        client: DeltaStreamMCPClient,
        *,
        database_hint: str | None,
        schema_hint: str | None,
        store_hint: str | None,
        max_depth: int,
        recent_minutes: int,
        event_hours: int,
        verbose: bool,
    ) -> None:
        self._client = client
        self._database_hint = database_hint
        self._schema_hint = schema_hint
        self._store_hint = store_hint
        self._max_depth = max_depth
        self._recent_cutoff = datetime.now(UTC) - timedelta(minutes=recent_minutes)
        self._event_cutoff = datetime.now(UTC) - timedelta(hours=event_hours)
        self._verbose = verbose
        self._relations_by_fqn: dict[str, RelationRef] = {}
        self._queries_by_id: dict[str, QueryInfo] = {}
        self._sink_to_queries: dict[str, list[QueryInfo]] = {}
        self._relation_columns: dict[str, list[dict[str, str]]] = {}
        self._query_probes: dict[str, QueryProbe] = {}
        self._relation_probes: dict[str, RelationProbe] = {}
        self._describe_failures: dict[str, str] = {}

    async def build_graph(self) -> None:
        await self._load_relations()
        await self._load_queries()
        await self._describe_queries()

    async def trace(self, start_name: str) -> TraceNode:
        start_relation = await self._resolve_start_relation(start_name)
        return await self._trace_relation(start_relation, depth=0, visited_queries=set())

    async def _load_relations(self) -> None:
        base_sql = (
            'SELECT database_name, schema_name, name, relation_type, state, store_name, "properties" '
            'FROM deltastream.sys."relations"'
        )
        rows = await self._paged_rows(base_sql)
        for row in rows:
            database = as_str(row.get("database_name"))
            schema = as_str(row.get("schema_name"))
            name = as_str(row.get("name"))
            if not database or not schema or not name:
                continue
            relation = RelationRef(
                database=database,
                schema=schema,
                name=name,
                relation_type=as_str(row.get("relation_type")),
                state=as_str(row.get("state")),
                store_name=as_str(row.get("store_name")),
                properties=parse_json_object(as_str(row.get("properties"))),
            )
            self._relations_by_fqn[relation.fqn] = relation

    async def _load_queries(self) -> None:
        base_sql = (
            'SELECT id, current_state, intended_state, updated_at, sql '
            'FROM deltastream.sys."queries" '
            "WHERE intended_state = 'running'"
        )
        rows = await self._paged_rows(base_sql)
        for row in rows:
            query_id = as_str(row.get("id"))
            if not query_id:
                continue
            self._queries_by_id[query_id] = QueryInfo(
                query_id=query_id,
                current_state=as_str(row.get("current_state")),
                intended_state=as_str(row.get("intended_state")),
                updated_at=as_str(row.get("updated_at")),
                sql=as_str(row.get("sql")),
            )

    async def _describe_queries(self) -> None:
        for query in self._queries_by_id.values():
            try:
                payload = await self._client.execute_dsql(
                    f"DESCRIBE QUERY {query.query_id}",
                    database=self._database_hint,
                    schema=self._schema_hint,
                    store=self._store_hint,
                )
            except Exception as exc:  # noqa: BLE001
                self._describe_failures[query.query_id] = str(exc)
                self._index_query_from_sql_text(query)
                continue
            rows = rows_from_payload(payload)
            query.sources = []
            query.sink = None
            for row in rows:
                if not isinstance(row, dict):
                    continue
                prop = as_str(row.get("Property"))
                if prop not in {"source", "sink"}:
                    continue
                relation = self._relation_from_describe_row(row)
                if relation is None:
                    continue
                if prop == "source":
                    query.sources.append(self._enrich_relation(relation))
                else:
                    query.sink = self._enrich_relation(relation)
            if query.sink is not None:
                self._sink_to_queries.setdefault(query.sink.fqn, []).append(query)
            elif query.sql:
                self._index_query_from_sql_text(query)

    async def _resolve_start_relation(self, start_name: str) -> RelationRef:
        database, schema, name = parse_start_name(start_name)
        matches: list[RelationRef] = []
        for relation in self._relations_by_fqn.values():
            if relation.name != name:
                continue
            if schema and relation.schema != schema:
                continue
            if database and relation.database != database:
                continue
            matches.append(relation)

        if len(matches) > 1 and self._schema_hint and not schema:
            narrowed = [relation for relation in matches if relation.schema == self._schema_hint]
            if narrowed:
                matches = narrowed
        if len(matches) > 1 and self._database_hint and not database:
            narrowed = [relation for relation in matches if relation.database == self._database_hint]
            if narrowed:
                matches = narrowed

        if not matches:
            raise TraceError(f"Could not find relation `{start_name}` in deltastream.sys.\"relations\"")
        if len(matches) > 1:
            candidates = "\n".join(f"- {match.short_name} ({match.relation_type})" for match in matches)
            raise TraceError(
                f"Relation `{start_name}` is ambiguous. Narrow it with --database/--schema or a fully qualified name.\n{candidates}"
            )
        return matches[0]

    async def _trace_relation(
        self,
        relation: RelationRef,
        *,
        depth: int,
        visited_queries: set[str],
    ) -> TraceNode:
        relation = self._enrich_relation(relation)
        relation_probe = await self._probe_relation(relation)
        trace_node = TraceNode(relation=relation, relation_probe=relation_probe)
        if depth >= self._max_depth:
            return trace_node

        upstream_query = self._pick_query_for_sink(relation)
        if upstream_query is None:
            return trace_node
        if upstream_query.query_id in visited_queries:
            return trace_node

        query_probe = await self._probe_query(upstream_query)
        trace_node.upstream_query = upstream_query
        trace_node.query_probe = query_probe

        next_visited = set(visited_queries)
        next_visited.add(upstream_query.query_id)
        for source in upstream_query.sources:
            trace_node.source_nodes.append(
                await self._trace_relation(source, depth=depth + 1, visited_queries=next_visited)
            )
        return trace_node

    async def _probe_relation(self, relation: RelationRef) -> RelationProbe:
        cached = self._relation_probes.get(relation.fqn)
        if cached is not None:
            return cached
        if relation.relation_type == "materialized_view":
            probe = await self._probe_materialized_view(relation)
        else:
            probe = await self._probe_entity_relation(relation)
        self._relation_probes[relation.fqn] = probe
        return probe

    async def _probe_materialized_view(self, relation: RelationRef) -> RelationProbe:
        columns = await self._relation_columns_for(relation)
        available = {column["name"]: column["type"] for column in columns}
        time_fields = [field for field in TIME_COLUMN_PREFERENCES if field in available]
        if time_fields:
            selects = []
            for field in time_fields:
                selects.append(f"max({quote_identifier(field)}) AS {quote_identifier('max_' + field)}")
            sql = f"SELECT {', '.join(selects)} FROM {relation.fqn} LIMIT 1"
            rows = await self._client.query_mview(sql)
            row = rows[0] if rows else {}
            for field in time_fields:
                alias = f"max_{field}"
                if alias not in row or row.get(alias) is None:
                    continue
                latest_at = normalize_time_value(field, row.get(alias), available[field])
                status = classify_freshness(latest_at, self._recent_cutoff)
                return RelationProbe(
                    status=status,
                    latest_value=str(row.get(alias)),
                    latest_at=latest_at,
                    checked_field=field,
                    details=f"Probed materialized view freshness via `{field}`",
                )

        count_rows = await self._client.query_mview(f"SELECT count(*) AS row_count FROM {relation.fqn} LIMIT 1")
        row_count = safe_int(count_rows[0].get("row_count")) if count_rows else 0
        return RelationProbe(
            status="unknown" if row_count else "empty",
            observed_rows=row_count,
            details="No timestamp-like columns found on materialized view",
        )

    async def _probe_entity_relation(self, relation: RelationRef) -> RelationProbe:
        store_name = relation.store_name or self._store_hint
        attempted_topics = candidate_entity_names(relation)
        errors: list[str] = []
        for topic_name in attempted_topics:
            try:
                payload = await self._client.execute_dsql(
                    f"PRINT ENTITY {quote_identifier(topic_name)}",
                    database=relation.database,
                    schema=relation.schema,
                    store=store_name,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{topic_name}: {exc}")
                continue
            rows = rows_from_payload(payload)
            observed = len(rows)
            if observed:
                return RelationProbe(
                    status="flowing",
                    observed_rows=observed,
                    details=(
                        f"Observed rows via PRINT ENTITY on topic `{topic_name}` "
                        f"(sample window up to {PRINT_FLOW_TIMEOUT_SECONDS}s)"
                    ),
                )
            return RelationProbe(
                status="no_data_observed",
                observed_rows=0,
                details=(
                    f"No rows observed via PRINT ENTITY on topic `{topic_name}` "
                    f"(sample window up to {PRINT_FLOW_TIMEOUT_SECONDS}s)"
                ),
            )
        return RelationProbe(
            status="probe_failed",
            details="; ".join(errors) if errors else "Unable to infer backing entity name",
        )

    async def _probe_query(self, query: QueryInfo) -> QueryProbe:
        cached = self._query_probes.get(query.query_id)
        if cached is not None:
            return cached
        cutoff = self._event_cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        sql = (
            'SELECT timestamp, type, actor, messages '
            'FROM deltastream.sys."query_events" '
            f"WHERE query_id = {quote_literal(query.query_id)} "
            f"AND timestamp >= {quote_literal(cutoff)} "
            'ORDER BY timestamp DESC LIMIT 100'
        )
        payload = await self._client.execute_dsql(sql)
        rows = rows_from_payload(payload)
        recent_events: list[QueryEvent] = []
        restart_reasons: list[str] = []
        restart_count = 0
        error_count = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            event = QueryEvent(
                timestamp=as_str(row.get("timestamp")),
                event_type=as_str(row.get("type")),
                actor=as_str(row.get("actor")),
                messages=as_str(row.get("messages")),
            )
            recent_events.append(event)
            if event.event_type == "rescheduled":
                restart_count += 1
                if event.messages:
                    restart_reasons.append(event.messages)
            if event.event_type == "errored":
                error_count += 1

        if query.current_state in RUNNING_STATES:
            status = "running"
        elif query.current_state == "errored":
            status = "errored"
        else:
            status = query.current_state or "unknown"
        if restart_count:
            status = f"{status}/restarting"

        probe = QueryProbe(
            status=status,
            recent_events=recent_events,
            restart_reasons=dedupe_preserve_order(restart_reasons),
            restart_count=restart_count,
            error_count=error_count,
        )
        self._query_probes[query.query_id] = probe
        return probe

    async def _relation_columns_for(self, relation: RelationRef) -> list[dict[str, str]]:
        cached = self._relation_columns.get(relation.fqn)
        if cached is not None:
            return cached
        sql = (
            'SELECT name, type '
            'FROM deltastream.sys."relation_columns" '
            f"WHERE relation_name = {quote_literal(relation.name)} "
            f"AND schema_name = {quote_literal(relation.schema)} "
            f"AND database_name = {quote_literal(relation.database)} "
            f"LIMIT {RELATION_COLUMN_LIMIT}"
        )
        payload = await self._client.execute_dsql(sql)
        rows = rows_from_payload(payload)
        normalized: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = as_str(row.get("name"))
            column_type = as_str(row.get("type"))
            if name and column_type:
                normalized.append({"name": name, "type": column_type})
        self._relation_columns[relation.fqn] = normalized
        return normalized

    async def _paged_rows(self, base_sql: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            sql = f"{base_sql} LIMIT {SYSTEM_PAGE_SIZE} OFFSET {offset}"
            payload = await self._client.execute_dsql(sql)
            page = [row for row in rows_from_payload(payload) if isinstance(row, dict)]
            rows.extend(page)
            if len(page) < SYSTEM_PAGE_SIZE:
                break
            offset += SYSTEM_PAGE_SIZE
        return rows

    def _relation_from_describe_row(self, row: dict[str, Any]) -> RelationRef | None:
        path = as_str(row.get("Path"))
        if path:
            try:
                parts = json.loads(path)
            except json.JSONDecodeError:
                parts = None
            if isinstance(parts, list) and len(parts) == 3:
                database, schema, name = (as_str(parts[0]), as_str(parts[1]), as_str(parts[2]))
                if database and schema and name:
                    return RelationRef(database=database, schema=schema, name=name)

        value = as_str(row.get("Value"))
        if not value:
            return None
        match = re.search(r"([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)$", value)
        if match is None:
            return None
        return RelationRef(database=match.group(1), schema=match.group(2), name=match.group(3))

    def _enrich_relation(self, relation: RelationRef) -> RelationRef:
        return self._relations_by_fqn.get(relation.fqn, relation)

    def _pick_query_for_sink(self, relation: RelationRef) -> QueryInfo | None:
        candidates = self._sink_to_queries.get(relation.fqn, [])
        if not candidates:
            return None
        ranked = sorted(candidates, key=query_sort_key)
        return ranked[0]

    def _index_query_from_sql_text(self, query: QueryInfo) -> None:
        if not query.sql:
            return
        sink = infer_sink_from_sql(query.sql, self._relations_by_fqn)
        if sink is None:
            return
        query.sink = sink
        self._sink_to_queries.setdefault(sink.fqn, []).append(query)


def query_sort_key(query: QueryInfo) -> tuple[int, int, str]:
    running = 0 if query.current_state in RUNNING_STATES else 1
    intended = 0 if query.intended_state == "running" else 1
    updated_at = query.updated_at or ""
    return (running, intended, updated_at)


def parse_start_name(start_name: str) -> tuple[str | None, str | None, str]:
    parts = [strip_identifier_quotes(part) for part in start_name.split(".") if part.strip()]
    if len(parts) == 1:
        return None, None, parts[0]
    if len(parts) == 2:
        return None, parts[0], parts[1]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    raise TraceError(f"Unsupported relation name `{start_name}`")


def strip_identifier_quotes(value: str) -> str:
    trimmed = value.strip()
    if trimmed.startswith('"') and trimmed.endswith('"') and len(trimmed) >= 2:
        return trimmed[1:-1]
    return trimmed


def quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def quote_relation_fqn(database: str, schema: str, name: str) -> str:
    return ".".join((quote_identifier(database), quote_identifier(schema), quote_identifier(name)))


def quote_literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def candidate_entity_names(relation: RelationRef) -> list[str]:
    candidates = [relation.name]
    prefixes = [
        "demo_context_pm_intel_v3_",
        "demo_pm_",
    ]
    base_name = relation.name
    for suffix in ("_s", "_c", "_mv"):
        if base_name.endswith(suffix):
            base_name = base_name[: -len(suffix)]
            break
    snake = base_name
    for prefix in prefixes:
        candidates.append(prefix + snake.removeprefix("pm_"))
        candidates.append(prefix + snake)
    return dedupe_preserve_order(candidates)


def infer_sink_from_sql(sql: str, relations_by_fqn: dict[str, RelationRef]) -> RelationRef | None:
    lowered = sql.lower()
    for relation in relations_by_fqn.values():
        tokens = sink_match_tokens(relation)
        if not any(token in lowered for token in tokens):
            continue
        create_patterns = (
            f"create materialized view {relation.name.lower()}",
            f"create stream {relation.name.lower()}",
            f"create changelog {relation.name.lower()}",
            f"create table {relation.name.lower()}",
            f"insert into {relation.name.lower()}",
        )
        if any(pattern in lowered for pattern in create_patterns):
            return relation
        qualified_patterns = (
            f"create materialized view {relation.short_name.lower()}",
            f"create stream {relation.short_name.lower()}",
            f"create changelog {relation.short_name.lower()}",
            f"create table {relation.short_name.lower()}",
            f"insert into {relation.short_name.lower()}",
            f"create materialized view {relation.fqn.lower()}",
            f"create stream {relation.fqn.lower()}",
            f"create changelog {relation.fqn.lower()}",
            f"create table {relation.fqn.lower()}",
            f"insert into {relation.fqn.lower()}",
        )
        if any(pattern in lowered for pattern in qualified_patterns):
            return relation
    return None


def sink_match_tokens(relation: RelationRef) -> tuple[str, ...]:
    return (
        relation.name.lower(),
        relation.short_name.lower(),
        relation.fqn.lower(),
    )


def extract_tool_payload(tool_result: Any) -> dict[str, Any] | list[Any]:
    if isinstance(tool_result, (dict, list)):
        return tool_result

    structured = getattr(tool_result, "structuredContent", None)
    if isinstance(structured, (dict, list)):
        return structured

    content = getattr(tool_result, "content", None)
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if not isinstance(text, str):
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw_text": text}
    return {}


def rows_from_payload(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return rows
    return []


def normalize_time_value(field_name: str, value: Any, value_type: str) -> str | None:
    if value is None:
        return None
    upper_type = value_type.upper()
    normalized_field = field_name.lower()
    if upper_type.startswith("BIGINT"):
        if not looks_like_epoch_millis_field(normalized_field):
            return str(value)
        dt = datetime.fromtimestamp(int(value) / 1000, tz=UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(value).replace(" ", "T")
    if text.endswith("Z"):
        return text
    if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$", text):
        return f"{text}Z"
    return text


def looks_like_epoch_millis_field(field_name: str) -> bool:
    return field_name.endswith("_ms") or field_name.endswith("time_ms") or field_name in {
        "updated_at",
    }


def classify_freshness(latest_at: str | None, cutoff: datetime) -> str:
    if latest_at is None:
        return "unknown"
    parsed = parse_datetime(latest_at)
    if parsed is None:
        return "unknown"
    if parsed >= cutoff:
        return "fresh"
    return "stale"


def parse_datetime(value: str) -> datetime | None:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def collect_findings(node: TraceNode, findings: list[str], *, indent: str = "") -> None:
    relation = node.relation
    probe = node.relation_probe
    if probe.status in {"stale", "no_data_observed", "probe_failed", "empty"}:
        findings.append(f"{relation.short_name}: relation probe status is {probe.status}")
    if node.upstream_query is None and probe.status in {"no_data_observed", "empty"}:
        findings.append(
            f"{relation.short_name}: no upstream running query sinks into this relation and its backing topic has no observed data"
        )
    if node.upstream_query and node.query_probe:
        query = node.upstream_query
        query_probe = node.query_probe
        if query.current_state not in RUNNING_STATES:
            findings.append(
                f"query {query.query_id} -> {relation.short_name}: current state is {query.current_state or 'unknown'}"
            )
        if query_probe.restart_count:
            findings.append(
                f"query {query.query_id} -> {relation.short_name}: {query_probe.restart_count} rescheduled events in window"
            )
        if query_probe.error_count:
            findings.append(
                f"query {query.query_id} -> {relation.short_name}: {query_probe.error_count} errored events in window"
            )
    for source in node.source_nodes:
        collect_findings(source, findings, indent=indent + "  ")


def render_text(node: TraceNode) -> str:
    lines: list[str] = []
    findings: list[str] = []
    _render_text_node(node, lines, depth=0)
    collect_findings(node, findings)
    if findings:
        lines.append("")
        lines.append("Potential Issues:")
        for finding in dedupe_preserve_order(findings):
            lines.append(f"- {finding}")
    return "\n".join(lines)


def _render_text_node(node: TraceNode, lines: list[str], *, depth: int) -> None:
    indent = "  " * depth
    relation = node.relation
    probe = node.relation_probe
    relation_line = (
        f"{indent}{relation.short_name} [{relation.relation_type or 'unknown'}] "
        f"status={probe.status}"
    )
    details: list[str] = []
    if probe.checked_field and probe.latest_at:
        details.append(f"{probe.checked_field}={probe.latest_at}")
    elif probe.latest_at:
        details.append(f"latest={probe.latest_at}")
    if probe.observed_rows is not None:
        details.append(f"rows={probe.observed_rows}")
    if probe.details:
        details.append(probe.details)
    if details:
        relation_line += " | " + "; ".join(details)
    lines.append(relation_line)

    if node.upstream_query is None:
        return

    query = node.upstream_query
    query_probe = node.query_probe
    query_line = (
        f"{indent}<- query {query.query_id} "
        f"[current={query.current_state or 'unknown'}, intended={query.intended_state or 'unknown'}"
    )
    if query_probe is not None:
        query_line += f", events={query_probe.status}, restarts={query_probe.restart_count}, errors={query_probe.error_count}"
    query_line += "]"
    lines.append(query_line)
    if query_probe and query_probe.restart_reasons:
        for reason in query_probe.restart_reasons:
            lines.append(f"{indent}   reason: {reason}")
    for source_node in node.source_nodes:
        _render_text_node(source_node, lines, depth=depth + 1)


def trace_node_to_dict(node: TraceNode) -> dict[str, Any]:
    return {
        "relation": {
            "database": node.relation.database,
            "schema": node.relation.schema,
            "name": node.relation.name,
            "fqn": node.relation.short_name,
            "relation_type": node.relation.relation_type,
            "state": node.relation.state,
            "store_name": node.relation.store_name,
        },
        "relation_probe": {
            "status": node.relation_probe.status,
            "latest_value": node.relation_probe.latest_value,
            "latest_at": node.relation_probe.latest_at,
            "checked_field": node.relation_probe.checked_field,
            "observed_rows": node.relation_probe.observed_rows,
            "details": node.relation_probe.details,
        },
        "upstream_query": None
        if node.upstream_query is None
        else {
            "query_id": node.upstream_query.query_id,
            "current_state": node.upstream_query.current_state,
            "intended_state": node.upstream_query.intended_state,
            "updated_at": node.upstream_query.updated_at,
            "query_probe": None
            if node.query_probe is None
            else {
                "status": node.query_probe.status,
                "restart_count": node.query_probe.restart_count,
                "error_count": node.query_probe.error_count,
                "restart_reasons": node.query_probe.restart_reasons,
                "recent_events": [
                    {
                        "timestamp": event.timestamp,
                        "type": event.event_type,
                        "actor": event.actor,
                        "messages": event.messages,
                    }
                    for event in node.query_probe.recent_events
                ],
            },
        },
        "sources": [trace_node_to_dict(source) for source in node.source_nodes],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Trace a DeltaStream pipeline backward from a relation, using DESCRIBE QUERY for "
            "lineage, query_events for instability, materialized-view probes for freshness, "
            "and PRINT ENTITY for backing-topic flow checks."
        )
    )
    parser.add_argument("--mcp-url", required=True, help="DeltaStream MCP URL")
    parser.add_argument("--token", required=True, help="DeltaStream bearer token")
    parser.add_argument("--start", required=True, help="Start relation: name, schema.name, or database.schema.name")
    parser.add_argument("--database", help="Optional default/narrowing database")
    parser.add_argument("--schema", help="Optional default/narrowing schema")
    parser.add_argument("--store", help="Optional default store for PRINT ENTITY and DSQL context")
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--recent-minutes", type=int, default=DEFAULT_RECENT_MINUTES)
    parser.add_argument("--event-hours", type=int, default=DEFAULT_EVENT_HOURS)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--verbose", action="store_true")
    return parser


async def run(args: argparse.Namespace) -> int:
    async with DeltaStreamMCPClient(
        mcp_url=args.mcp_url,
        api_token=args.token,
        database=args.database,
        schema=args.schema,
        store=args.store,
    ) as client:
        tracer = PipelineTracer(
            client,
            database_hint=args.database,
            schema_hint=args.schema,
            store_hint=args.store,
            max_depth=args.max_depth,
            recent_minutes=args.recent_minutes,
            event_hours=args.event_hours,
            verbose=args.verbose,
        )
        await tracer.build_graph()
        trace = await tracer.trace(args.start)

    if args.format == "json":
        print(json.dumps(trace_node_to_dict(trace), indent=2, sort_keys=True))
    else:
        print(render_text(trace))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except TraceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
