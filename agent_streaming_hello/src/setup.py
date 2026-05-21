"""Setup and validation helpers for Kafka and DeltaStream."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
from kafka import KafkaAdminClient, KafkaProducer
from kafka.admin import NewTopic
from kafka.errors import TopicAlreadyExistsError

from .config import AppConfig, CleanupResult, PipelineStatusResult, SetupResult, ValidationResult
from .constants import (
    DEFAULT_STORE_NAME,
    MV_PAGEVIEW_COUNTS,
    QUERY_PAGEVIEW_COUNTS,
    STREAM_PAGEVIEWS,
    TOPIC_PAGEVIEWS,
)

DEMO_DATABASE = "hello_world_demo"
DEMO_SCHEMA = "public"
DEMO_STORE = DEFAULT_STORE_NAME


def _normalize_statements_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v2"):
        return f"{root}/statements"
    return f"{root}/v2/statements"


def _split_sql_statements(text: str) -> list[str]:
    statements: list[str] = []
    buff: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double

        if char == ";" and not in_single and not in_double:
            stmt = "".join(buff).strip()
            if stmt:
                statements.append(stmt)
            buff = []
            i += 1
            continue

        buff.append(char)
        i += 1

    tail = "".join(buff).strip()
    if tail:
        statements.append(tail)
    return statements


def _kafka_common(config: AppConfig) -> dict[str, object]:
    return {
        "bootstrap_servers": config.bootstrap_servers(),
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": "PLAIN",
        "sasl_plain_username": config.kafka_username,
        "sasl_plain_password": config.kafka_password.get_secret_value(),
    }


def validate_kafka(config: AppConfig) -> tuple[bool, str]:
    try:
        producer = KafkaProducer(
            **_kafka_common(config),
            value_serializer=lambda payload: json.dumps(payload).encode("utf-8"),
            request_timeout_ms=15000,
            retries=1,
        )
        connected = producer.bootstrap_connected()
        producer.close(timeout=3)
        if not connected:
            return False, "Kafka validation failed: broker connection not established"
        return True, "Kafka connection successful"
    except Exception as exc:  # noqa: BLE001
        return False, f"Kafka validation failed: {type(exc).__name__}: {exc}"


def validate_anthropic(config: AppConfig) -> tuple[bool, str]:
    headers = {
        "x-api-key": config.anthropic_api_key.get_secret_value(),
        "anthropic-version": "2023-06-01",
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get("https://api.anthropic.com/v1/models", headers=headers)
        if response.status_code == 200:
            return True, "Anthropic API key is valid"
        return False, f"Anthropic validation failed: HTTP {response.status_code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Anthropic validation failed: {type(exc).__name__}: {exc}"


def _deltastream_request(
    config: AppConfig,
    statement: str,
    *,
    database: str | None = None,
    schema: str | None = None,
    store: str | None = None,
) -> dict:
    payload: dict[str, str] = {"statement": statement.strip().rstrip(";") + ";"}
    if database:
        payload["database"] = database
    if schema:
        payload["schema"] = schema
    if store:
        payload["store"] = store

    headers = {
        "Authorization": f"Bearer {config.deltastream_api_token.get_secret_value()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = _normalize_statements_url(config.deltastream_api_url)
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=payload)
    response.raise_for_status()
    body = response.json()
    sql_state = (body.get("sqlState") or "").upper()
    if sql_state and sql_state not in {"00000", "SUCCESS", "OK"}:
        message = body.get("message") or "unknown error"
        raise RuntimeError(f"sqlState={sql_state} message={message}")
    return body


def _deltastream_request_tolerant(
    config: AppConfig,
    statement: str,
    *,
    database: str | None = None,
    schema: str | None = None,
    store: str | None = None,
) -> tuple[bool, str]:
    try:
        _deltastream_request(
            config,
            statement,
            database=database,
            schema=schema,
            store=store,
        )
        return True, "applied"
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        if "already exists" in message:
            return True, "already exists"
        if "does not exist" in message or "not found" in message:
            return True, "not found"
        raise


def _relation_exists(config: AppConfig, relation_name: str) -> bool:
    stmt = (
        'SELECT name FROM deltastream.sys."relations" '
        f"WHERE database_name = '{DEMO_DATABASE}' "
        f"AND schema_name = '{DEMO_SCHEMA}' "
        f"AND name = '{relation_name}' LIMIT 1"
    )
    response = _deltastream_request(config, stmt)
    rows = response.get("data") or []
    return len(rows) > 0


def _pipeline_query_running(config: AppConfig) -> bool:
    response = _deltastream_request(config, "SHOW QUERIES")
    rows = response.get("data") or []
    for row in rows:
        name = (row[1] or "").strip().lower()
        actual_state = (row[4] or "").strip().lower()
        query_sql = (row[5] or "").strip().lower()
        if actual_state != "running":
            continue
        if (
            QUERY_PAGEVIEW_COUNTS.lower() == name
            or QUERY_PAGEVIEW_COUNTS.lower() in query_sql
            or MV_PAGEVIEW_COUNTS.lower() in query_sql
        ):
            return True
    return False


def get_pipeline_status(config: AppConfig) -> PipelineStatusResult:
    details: list[str] = []
    try:
        stream_exists = _relation_exists(config, STREAM_PAGEVIEWS)
        mv_exists = _relation_exists(config, MV_PAGEVIEW_COUNTS)

        details.append(
            f"Stream `{STREAM_PAGEVIEWS}`: {'ready' if stream_exists else 'missing'}"
        )
        details.append(f"Materialized view `{MV_PAGEVIEW_COUNTS}`: {'ready' if mv_exists else 'missing'}")

        query_running = _pipeline_query_running(config)
        details.append(
            "Pipeline query actual_state: "
            f"{'running' if query_running else 'not running'}"
        )

        ready = stream_exists and mv_exists and query_running
        details.append(f"Overall pipeline status: {'ready' if ready else 'not ready'}")
        return PipelineStatusResult(ok=True, ready=ready, details=details)
    except Exception as exc:  # noqa: BLE001
        details.append(f"Pipeline status check failed: {type(exc).__name__}: {exc}")
        return PipelineStatusResult(ok=False, ready=False, details=details)


def wait_for_pipeline_ready(
    config: AppConfig,
    *,
    timeout_seconds: int = 45,
    poll_interval_seconds: int = 3,
) -> PipelineStatusResult:
    attempts = max(1, timeout_seconds // max(1, poll_interval_seconds))
    final: PipelineStatusResult | None = None
    for _ in range(attempts):
        final = get_pipeline_status(config)
        if final.ok and final.ready:
            return final
        time.sleep(poll_interval_seconds)
    if final is None:
        return PipelineStatusResult(ok=False, ready=False, details=["Pipeline status unavailable"])
    return final


def validate_deltastream(config: AppConfig) -> tuple[bool, str]:
    try:
        _deltastream_request(
            config,
            'SELECT name FROM deltastream.sys."stores" LIMIT 1',
        )
        return True, "DeltaStream token validated"
    except Exception as exc:  # noqa: BLE001
        return False, f"DeltaStream validation failed: {type(exc).__name__}: {exc}"


def validate_connections(config: AppConfig) -> ValidationResult:
    kafka_ok, kafka_msg = validate_kafka(config)
    anthropic_ok, anthropic_msg = validate_anthropic(config)
    deltastream_ok, deltastream_msg = validate_deltastream(config)
    return ValidationResult(
        kafka_ok=kafka_ok,
        anthropic_ok=anthropic_ok,
        deltastream_ok=deltastream_ok,
        details=[kafka_msg, anthropic_msg, deltastream_msg],
    )


def ensure_topic(config: AppConfig) -> tuple[bool, str]:
    try:
        admin = KafkaAdminClient(
            **_kafka_common(config),
            request_timeout_ms=15000,
        )
        topic = NewTopic(name=TOPIC_PAGEVIEWS, num_partitions=3, replication_factor=3)
        admin.create_topics([topic], validate_only=False)
        admin.close()
        return True, f"Created Kafka topic `{TOPIC_PAGEVIEWS}` (partitions=3, replication_factor=3)"
    except TopicAlreadyExistsError:
        return True, f"Kafka topic `{TOPIC_PAGEVIEWS}` already exists"
    except Exception as exc:  # noqa: BLE001
        return (
            False,
            "Kafka topic creation failed. Create it manually: "
            f"topic={TOPIC_PAGEVIEWS}, partitions=3, replication_factor=3. "
            f"Details: {type(exc).__name__}: {exc}",
        )


def _store_ddl(config: AppConfig) -> str:
    brokers = ",".join(config.bootstrap_servers())
    username = config.kafka_username.replace("'", "''")
    password = config.kafka_password.get_secret_value().replace("'", "''")
    return (
        f"CREATE STORE {DEMO_STORE} WITH ("
        "'type' = KAFKA, "
        f"'uris' = '{brokers}', "
        "'kafka.sasl.hash_function' = PLAIN, "
        f"'kafka.sasl.username' = '{username}', "
        f"'kafka.sasl.password' = '{password}'"
        ")"
    )


def _store_exists(config: AppConfig) -> bool:
    check_stmt = (
        'SELECT name FROM deltastream.sys."stores" '
        f"WHERE name = '{DEMO_STORE}' LIMIT 1"
    )
    response = _deltastream_request(config, check_stmt)
    rows = response.get("data") or []
    return len(rows) > 0


def _load_sql(config: AppConfig) -> list[str]:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "pageviews.sql"
    raw = sql_path.read_text(encoding="utf-8")
    rendered = raw.format(
        database=DEMO_DATABASE,
        schema=DEMO_SCHEMA,
        store=DEMO_STORE,
        stream_name=STREAM_PAGEVIEWS,
        topic_name=TOPIC_PAGEVIEWS,
        mv_name=MV_PAGEVIEW_COUNTS,
        query_name=QUERY_PAGEVIEW_COUNTS,
    )
    return _split_sql_statements(rendered)


def run_setup(config: AppConfig) -> SetupResult:
    steps: list[str] = []
    statements_run: list[str] = []

    topic_ok, topic_message = ensure_topic(config)
    steps.append(topic_message)

    try:
        db_stmt = f"CREATE DATABASE {DEMO_DATABASE}"
        statements_run.append(db_stmt)
        _, db_status = _deltastream_request_tolerant(
            config,
            db_stmt,
        )
        steps.append(f"Database `{DEMO_DATABASE}`: {db_status}")

        store_check_stmt = (
            'SELECT name FROM deltastream.sys."stores" '
            f"WHERE name = '{DEMO_STORE}' LIMIT 1"
        )
        statements_run.append(store_check_stmt)
        if _store_exists(config):
            steps.append(f"Store `{DEMO_STORE}`: already exists")
        else:
            store_stmt = _store_ddl(config)
            statements_run.append(store_stmt)
            _, store_status = _deltastream_request_tolerant(config, store_stmt)
            steps.append(f"Store `{DEMO_STORE}`: {store_status}")

        for stmt in _load_sql(config):
            statements_run.append(stmt)
            try:
                _deltastream_request(
                    config,
                    stmt,
                    database=DEMO_DATABASE,
                    schema=DEMO_SCHEMA,
                    store=DEMO_STORE,
                )
                head = " ".join(stmt.split())[:90]
                steps.append(f"Applied: {head}")
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).lower()
                if "already exists" in msg:
                    steps.append("Skipped existing object")
                else:
                    raise

        return SetupResult(ok=True, steps=steps, statements=statements_run)
    except Exception as exc:  # noqa: BLE001
        steps.append(f"Setup failed: {type(exc).__name__}: {exc}")
        return SetupResult(ok=False, steps=steps, statements=statements_run)


def _terminate_queries_referencing_demo(config: AppConfig) -> tuple[int, list[str]]:
    response = _deltastream_request(config, "SHOW QUERIES")
    rows = response.get("data") or []
    terminated: list[str] = []
    for row in rows:
        query_id = row[0]
        actual_state = (row[4] or "").lower().strip()
        query_sql = (row[5] or "").lower()
        if actual_state != "running":
            continue
        if (
            QUERY_PAGEVIEW_COUNTS in query_sql
            or MV_PAGEVIEW_COUNTS in query_sql
            or STREAM_PAGEVIEWS in query_sql
            or DEMO_DATABASE in query_sql
        ):
            _deltastream_request(config, f"TERMINATE QUERY {query_id}")
            terminated.append(query_id)
    return len(terminated), terminated


def _has_active_demo_queries(config: AppConfig) -> bool:
    response = _deltastream_request(config, "SHOW QUERIES")
    rows = response.get("data") or []
    for row in rows:
        name = (row[1] or "").lower().strip()
        actual_state = (row[4] or "").lower().strip()
        query_sql = (row[5] or "").lower()
        if actual_state not in {"running", "terminate_requested"}:
            continue
        if (
            QUERY_PAGEVIEW_COUNTS in name
            or QUERY_PAGEVIEW_COUNTS in query_sql
            or MV_PAGEVIEW_COUNTS in query_sql
            or STREAM_PAGEVIEWS in query_sql
            or DEMO_DATABASE in query_sql
        ):
            return True
    return False


def run_cleanup(config: AppConfig) -> CleanupResult:
    steps: list[str] = []
    statements_run: list[str] = []

    try:
        for _ in range(8):
            terminate_stmt_count, terminate_ids = _terminate_queries_referencing_demo(config)
            for query_id in terminate_ids:
                statements_run.append(f"TERMINATE QUERY {query_id}")
            if not _has_active_demo_queries(config):
                break
            if terminate_stmt_count:
                steps.append(
                    f"Sent terminate for {terminate_stmt_count} running query(s) referencing demo objects"
                )
            time.sleep(2)

        if _has_active_demo_queries(config):
            raise RuntimeError("queries are still terminating; retry cleanup in a few seconds")

        def drop_with_retry(stmt: str, relation_name: str | None = None) -> str:
            for _ in range(8):
                try:
                    _deltastream_request(config, stmt)
                except Exception as exc:  # noqa: BLE001
                    message = str(exc).lower()
                    if "does not exist" in message or "not found" in message:
                        return "not found"
                    if "2bp01" in message:
                        _terminate_queries_referencing_demo(config)
                        time.sleep(2)
                        continue
                    raise

                if relation_name is None:
                    return "applied"

                for _ in range(8):
                    if not _relation_exists(config, relation_name):
                        return "applied"
                    time.sleep(1)
                return "applied"
            return "not found"

        drop_mv_stmt = f"DROP MATERIALIZED VIEW {DEMO_DATABASE}.{DEMO_SCHEMA}.{MV_PAGEVIEW_COUNTS}"
        statements_run.append(drop_mv_stmt)
        mv_status = drop_with_retry(drop_mv_stmt, relation_name=MV_PAGEVIEW_COUNTS)
        steps.append(f"Materialized view `{MV_PAGEVIEW_COUNTS}`: {mv_status}")

        drop_stream_stmt = f"DROP STREAM {DEMO_DATABASE}.{DEMO_SCHEMA}.{STREAM_PAGEVIEWS}"
        statements_run.append(drop_stream_stmt)
        stream_status = drop_with_retry(drop_stream_stmt, relation_name=STREAM_PAGEVIEWS)
        steps.append(f"Stream `{STREAM_PAGEVIEWS}`: {stream_status}")

        drop_db_stmt = f"DROP DATABASE {DEMO_DATABASE}"
        statements_run.append(drop_db_stmt)
        db_status = drop_with_retry(drop_db_stmt)
        steps.append(f"Database `{DEMO_DATABASE}`: {db_status}")

        return CleanupResult(ok=True, steps=steps, statements=statements_run)
    except Exception as exc:  # noqa: BLE001
        steps.append(f"Cleanup failed: {type(exc).__name__}: {exc}")
        return CleanupResult(ok=False, steps=steps, statements=statements_run)
