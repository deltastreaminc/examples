from __future__ import annotations

import os

import streamlit as st
from pydantic import ValidationError

from src.chat_backend import ChatMessage, PydanticAIAnthropicMCPBackend
from src.config import AppConfig
from src.constants import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_DELTASTREAM_API_URL,
    DEFAULT_DELTASTREAM_MCP_URL,
    MV_PAGEVIEW_COUNTS,
    TOPIC_PAGEVIEWS,
)
from src.datagen import PageviewDataGenerator
from src.setup import (
    DEMO_DATABASE,
    DEMO_SCHEMA,
    get_pipeline_status,
    run_cleanup,
    run_setup,
    validate_connections,
    wait_for_pipeline_ready,
)


st.set_page_config(
    page_title="DeltaStream Hello World Agent",
    page_icon="https://www.deltastream.io/wp-content/uploads/2026/01/Flattened.png",
    layout="wide",
)


def _inject_brand_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ds-primary: #0A042A;
          --ds-secondary: #0C47DC;
          --ds-accent: #24E2FF;
          --ds-accent-2: #8C5FFF;
          --ds-bg-soft: #F0F3FF;
          --ds-bg-dark: #03133C;
          --ds-text: #001423;
          --ds-text-muted: rgba(10, 4, 42, 0.72);
          --ds-border: rgba(42, 63, 121, 0.35);
          --ds-radius: 14px;
        }

        .stApp {
          background:
            radial-gradient(820px 420px at 10% -10%, rgba(36, 226, 255, 0.20), transparent 60%),
            radial-gradient(680px 360px at 95% -8%, rgba(140, 95, 255, 0.16), transparent 55%),
            linear-gradient(180deg, #ffffff 0%, #f7f9ff 72%, #f0f3ff 100%);
          color: var(--ds-text);
        }

        .block-container {
          max-width: 1100px;
          padding-top: 2rem;
          padding-bottom: 3rem;
        }

        h1, h2, h3 {
          color: var(--ds-primary) !important;
          font-family: "DM Sans", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
          letter-spacing: -0.01em;
        }

        p, label, span, .stCaption {
          color: var(--ds-text) !important;
        }

        div[data-testid="stMetric"] {
          background: white;
          border: 1px solid var(--ds-border);
          border-radius: var(--ds-radius);
          padding: 0.85rem 1rem;
          box-shadow: 0 8px 24px rgba(10, 4, 42, 0.06);
        }

        .stButton > button {
          border-radius: 10px;
          border: 1px solid var(--ds-secondary);
          background: var(--ds-secondary) !important;
          color: #fff !important;
          font-family: "Atkinson Mono", "SFMono-Regular", Menlo, Consolas, monospace;
          font-size: 0.82rem;
          text-transform: uppercase;
          letter-spacing: 0.03em;
        }

        .stButton > button span,
        .stButton > button p,
        .stButton > button div {
          color: #fff !important;
        }

        .stButton > button[kind="secondary"],
        .stButton > button[kind="primary"],
        .stButton > button[kind="tertiary"] {
          background: var(--ds-secondary) !important;
          color: #ffffff !important;
          border-color: var(--ds-secondary) !important;
        }

        .stButton > button:hover {
          background: var(--ds-secondary);
          border-color: var(--ds-secondary);
          color: #fff;
        }

        div[data-baseweb="input"] > div {
          border-radius: 10px;
          border-color: rgba(12, 71, 220, 0.45);
          background: #fff;
        }

        div[data-baseweb="input"] > div:focus-within {
          box-shadow: 0 0 0 2px rgba(36, 226, 255, 0.45);
          border-color: var(--ds-secondary);
        }

        [data-testid="stExpander"] {
          border: 1px solid var(--ds-border);
          border-radius: var(--ds-radius);
          background: rgba(255, 255, 255, 0.92);
        }

        .ds-hero {
          background: linear-gradient(120deg, rgba(3, 19, 60, 0.96) 0%, rgba(10, 4, 42, 0.95) 50%, rgba(12, 71, 220, 0.93) 100%);
          border: 1px solid rgba(36, 226, 255, 0.45);
          border-radius: 20px;
          padding: 1.2rem 1.3rem;
          margin-bottom: 1rem;
          box-shadow: 0 18px 38px rgba(3, 19, 60, 0.24);
        }

        .ds-hero h2 {
          margin: 0 0 0.4rem 0;
          color: #fff !important;
        }

        .ds-hero p {
          margin: 0;
          color: rgba(255, 255, 255, 0.84) !important;
        }

        .ds-chip {
          display: inline-block;
          margin-top: 0.7rem;
          margin-right: 0.45rem;
          padding: 0.2rem 0.55rem;
          border-radius: 999px;
          border: 1px solid rgba(36, 226, 255, 0.6);
          color: rgba(255, 255, 255, 0.94) !important;
          font-family: "Atkinson Mono", "SFMono-Regular", Menlo, Consolas, monospace;
          font-size: 0.75rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _init_state() -> None:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "datagen" not in st.session_state:
        st.session_state.datagen = None
    if "last_validation" not in st.session_state:
        st.session_state.last_validation = None
    if "last_setup" not in st.session_state:
        st.session_state.last_setup = None
    if "last_cleanup" not in st.session_state:
        st.session_state.last_cleanup = None
    if "pipeline_status" not in st.session_state:
        st.session_state.pipeline_status = None
    if "deltastream_api_url" not in st.session_state:
        st.session_state.deltastream_api_url = os.getenv(
            "DELTASTREAM_API_URL",
            DEFAULT_DELTASTREAM_API_URL,
        )
    if "deltastream_mcp_url" not in st.session_state:
        st.session_state.deltastream_mcp_url = os.getenv(
            "DELTASTREAM_MCP_URL",
            DEFAULT_DELTASTREAM_MCP_URL,
        )
    if "anthropic_model" not in st.session_state:
        st.session_state.anthropic_model = os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
    if "kafka_brokers" not in st.session_state:
        st.session_state.kafka_brokers = os.getenv("KAFKA_BROKERS", "")
    if "kafka_username" not in st.session_state:
        st.session_state.kafka_username = os.getenv("KAFKA_USERNAME", "")
    if "kafka_password" not in st.session_state:
        st.session_state.kafka_password = os.getenv("KAFKA_PASSWORD", "")
    if "anthropic_api_key" not in st.session_state:
        st.session_state.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if "deltastream_api_token" not in st.session_state:
        st.session_state.deltastream_api_token = os.getenv("DELTASTREAM_API_TOKEN", "")


def _build_config() -> AppConfig:
    return AppConfig(
        kafka_brokers=st.session_state.kafka_brokers,
        kafka_username=st.session_state.kafka_username,
        kafka_password=st.session_state.kafka_password,
        anthropic_api_key=st.session_state.anthropic_api_key,
        deltastream_api_token=st.session_state.deltastream_api_token,
        deltastream_api_url=st.session_state.deltastream_api_url,
        deltastream_mcp_url=st.session_state.deltastream_mcp_url,
        anthropic_model=st.session_state.anthropic_model,
    )


def _render_setup_panel() -> AppConfig | None:
    st.subheader("1) Credentials and Setup")
    st.caption("Provide credentials, validate, then run one-click setup.")

    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Kafka brokers", key="kafka_brokers", placeholder="host1:9092,host2:9092")
        st.text_input("Kafka username", key="kafka_username")
        st.text_input("Kafka password", key="kafka_password", type="password")

    with col2:
        st.text_input("Anthropic API key", key="anthropic_api_key", type="password")
        st.text_input("DeltaStream API token", key="deltastream_api_token", type="password")

    st.text_input("DeltaStream API URL", key="deltastream_api_url")
    st.text_input("DeltaStream MCP URL", key="deltastream_mcp_url")
    st.text_input("Anthropic model", key="anthropic_model")

    st.info(
        f"Static demo objects: topic `{TOPIC_PAGEVIEWS}` -> stream `pageviews_stream` -> "
        f"materialized view `{MV_PAGEVIEW_COUNTS}` in `{DEMO_DATABASE}.{DEMO_SCHEMA}`"
    )

    try:
        config = _build_config()
    except ValidationError as exc:
        st.warning("Fill all required fields to continue.")
        st.caption(str(exc).split("\n")[0])
        return None

    action_col1, action_col2 = st.columns(2)
    with action_col1:
        if st.button("Validate Connections", type="secondary", use_container_width=True):
            with st.spinner("Validating Kafka, Anthropic, and DeltaStream..."):
                st.session_state.last_validation = validate_connections(config)

    with action_col2:
        if st.button("Run Setup", type="primary", use_container_width=True):
            with st.spinner("Running setup workflow..."):
                st.session_state.last_setup = run_setup(config)

    if st.button("Run Cleanup", type="secondary", use_container_width=True):
        with st.spinner("Terminating queries and cleaning up demo resources..."):
            st.session_state.last_cleanup = run_cleanup(config)

    status_col1, status_col2 = st.columns(2)
    with status_col1:
        if st.button("Check Pipeline Status", type="secondary", use_container_width=True):
            st.session_state.pipeline_status = get_pipeline_status(config)
    with status_col2:
        if st.button("Wait Until Ready", type="secondary", use_container_width=True):
            with st.spinner("Polling pipeline status until ready..."):
                st.session_state.pipeline_status = wait_for_pipeline_ready(config)

    if st.session_state.last_validation is not None:
        result = st.session_state.last_validation
        status_col1, status_col2, status_col3 = st.columns(3)
        status_col1.metric("Kafka", "OK" if result.kafka_ok else "Failed")
        status_col2.metric("Anthropic", "OK" if result.anthropic_ok else "Failed")
        status_col3.metric("DeltaStream", "OK" if result.deltastream_ok else "Failed")
        with st.expander("Validation details"):
            for line in result.details:
                st.write(f"- {line}")

    if st.session_state.last_setup is not None:
        setup_result = st.session_state.last_setup
        if setup_result.ok:
            st.success("Setup completed.")
        else:
            st.error("Setup finished with errors. Review details below.")
        with st.expander("Setup steps", expanded=True):
            for step in setup_result.steps:
                st.write(f"- {step}")
        with st.expander("DSQL statements"):
            for idx, stmt in enumerate(setup_result.statements, start=1):
                st.code(f"-- {idx}\n{stmt}", language="sql")

    if st.session_state.last_cleanup is not None:
        cleanup_result = st.session_state.last_cleanup
        if cleanup_result.ok:
            st.success("Cleanup completed.")
        else:
            st.error("Cleanup finished with errors. Review details below.")
        with st.expander("Cleanup steps", expanded=True):
            for step in cleanup_result.steps:
                st.write(f"- {step}")
        with st.expander("Cleanup DSQL statements"):
            for idx, stmt in enumerate(cleanup_result.statements, start=1):
                st.code(f"-- {idx}\n{stmt}", language="sql")

    if st.session_state.pipeline_status is not None:
        pipeline_status = st.session_state.pipeline_status
        if pipeline_status.ready:
            st.success("Pipeline is ready.")
        elif pipeline_status.ok:
            st.warning("Pipeline is not ready yet.")
        else:
            st.error("Pipeline status check failed.")
        with st.expander("Pipeline status details", expanded=True):
            for detail in pipeline_status.details:
                st.write(f"- {detail}")

    return config


def _render_datagen_panel(config: AppConfig | None) -> None:
    st.subheader("2) Data Generator")
    st.caption("Generate live pageview events into the static `pageviews` topic.")
    eps = st.slider("Events per second", min_value=1, max_value=50, value=5)

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Start Datagen", use_container_width=True):
            if config is None:
                st.error("Provide valid credentials first.")
            else:
                existing = st.session_state.datagen
                if existing is not None and existing.is_running:
                    existing.stop()
                datagen = PageviewDataGenerator(config=config, events_per_second=float(eps))
                datagen.start()
                st.session_state.datagen = datagen
                st.success("Datagen started.")

    with col2:
        if st.button("Stop Datagen", use_container_width=True):
            datagen = st.session_state.datagen
            if datagen is not None:
                datagen.stop()
                st.success("Datagen stopped.")
            else:
                st.info("Datagen was not running.")

    with col3:
        if st.button("Reset Demo", use_container_width=True):
            datagen = st.session_state.datagen
            if datagen is not None:
                datagen.stop()
                datagen.reset_stats()
            st.session_state.chat_history = []
            st.success("Cleared chat history and reset datagen stats.")

    datagen = st.session_state.datagen
    if datagen is None:
        st.info("Datagen status: idle")
        return

    stat_col1, stat_col2, stat_col3 = st.columns(3)
    stat_col1.metric("Datagen running", "Yes" if datagen.is_running else "No")
    stat_col2.metric("Events sent", datagen.stats.sent_events)
    stat_col3.metric("Last error", datagen.stats.last_error or "None")


def _render_chat_panel(config: AppConfig | None) -> None:
    st.subheader("3) Chat")
    st.caption("Ask about pageview counts. Chat history is session-only.")

    if config is None:
        st.warning("Complete the setup fields before using chat.")
        return

    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.write(message["content"])
            if message["role"] == "assistant" and message.get("evidence"):
                st.caption(f"Evidence relations: {', '.join(message['evidence'])}")

    user_prompt = st.chat_input("Example: What are the top pages by pageviews?")
    if not user_prompt:
        return

    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.write(user_prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            backend = PydanticAIAnthropicMCPBackend(config)
            history = [
                ChatMessage(role=msg["role"], content=msg["content"])
                for msg in st.session_state.chat_history
                if msg["role"] in {"user", "assistant"}
            ]
            try:
                result = backend.ask(prompt=user_prompt, history=history)
                st.write(result.answer)
                if result.evidence_relations:
                    st.caption(f"Evidence relations: {', '.join(result.evidence_relations)}")
                else:
                    st.caption("Evidence relations: none reported")
                st.caption(f"Tool calls: {result.tool_calls}")
                st.session_state.chat_history.append(
                    {
                        "role": "assistant",
                        "content": result.answer,
                        "evidence": result.evidence_relations,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                error_text = f"Chat request failed: {type(exc).__name__}: {exc}"
                st.error(error_text)
                st.session_state.chat_history.append(
                    {
                        "role": "assistant",
                        "content": error_text,
                        "evidence": [],
                    }
                )


def main() -> None:
    _init_state()
    _inject_brand_theme()
    st.markdown(
        """
        <div class="ds-hero">
          <h2>/ DeltaStream Hello World Agent /</h2>
          <p>Stream pageviews into Kafka, build realtime counts in DeltaStream, and query results from chat.</p>
          <span class="ds-chip">Kafka -> DeltaStream -> Agent</span>
          <span class="ds-chip">Single Topic Demo</span>
          <span class="ds-chip">Template Starter</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info(
        "This demo is a minimal end-to-end template: it creates one Kafka topic (`pageviews`), "
        "builds one DeltaStream stream and one materialized view for cumulative page counts, "
        "runs pageview datagen, and lets you query results through an MCP-backed chat agent."
    )

    config = _render_setup_panel()
    st.divider()
    _render_datagen_panel(config)
    st.divider()
    _render_chat_panel(config)


if __name__ == "__main__":
    main()
