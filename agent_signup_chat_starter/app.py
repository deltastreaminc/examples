"""Streamlit starter app: signup, shared token, and MCP-backed chat."""

from __future__ import annotations

import os

import streamlit as st
from pydantic import ValidationError

from src.chat_backend import ChatMessage, MCPConnectionError, PydanticAIDemoBackend, QueryPolicyError
from src.config import AppConfig
from src.constants import ALLOWED_MVIEW_FQNS, DELTASTREAM_MCP_URL, INSECURE_DEMO_TLS
from src.http_clients import allowed_relation_label, probe_anthropic, probe_mcp, signup


def main() -> None:
    st.set_page_config(page_title="DeltaStream Signup Chat Starter", page_icon="\U0001f916", layout="wide")
    _init_state()

    st.title("DeltaStream Signup + Chat Starter")
    st.caption(
        "Sign up for a demo token, paste that shared token, then chat with an agent "
        f"that can only query {allowed_relation_label()}."
    )

    if INSECURE_DEMO_TLS:
        st.info("TLS verification is disabled for demo.local endpoints (self-signed certificate).")
    st.caption(f"Configured MCP URL: `{DELTASTREAM_MCP_URL}`")

    _render_signup_form()
    st.divider()
    _render_token_panel()
    st.divider()
    _render_chat_panel()


def _init_state() -> None:
    st.session_state.setdefault("signup_email", "")
    st.session_state.setdefault("api_token", os.getenv("API_TOKEN", ""))
    st.session_state.setdefault("token_validated", False)
    st.session_state.setdefault("validated_token", "")
    st.session_state.setdefault("chat_history", [])


def _render_signup_form() -> None:
    st.subheader("1) Sign up")
    with st.form("signup-form", clear_on_submit=False):
        email = st.text_input(
            "Email",
            value=st.session_state.signup_email,
            placeholder="user@example.com",
        )
        submitted = st.form_submit_button("Send signup email")

    st.session_state.signup_email = email

    if not submitted:
        return
    if "@" not in email:
        st.error("Please provide a valid email address.")
        return

    with st.spinner("Submitting signup request..."):
        try:
            message = signup(email=email, insecure_tls=INSECURE_DEMO_TLS)
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
            return

    st.success(message)
    st.info("After you click the confirmation link from your email, paste the API token below.")


def _render_token_panel() -> None:
    st.subheader("2) Enter shared API token")
    st.caption("This single token is used for both DeltaStream MCP and Anthropic requests.")

    token = st.text_input(
        "API token",
        value=st.session_state.api_token,
        type="password",
        placeholder="Paste token from confirmation page",
    )
    st.session_state.api_token = token
    if token.strip() != st.session_state.validated_token:
        st.session_state.token_validated = False

    col1, col2 = st.columns([1, 2])
    with col1:
        validate_clicked = st.button("Validate token", type="primary")
    with col2:
        st.caption("Validation checks Anthropic and DeltaStream MCP endpoints with the same token.")

    if not validate_clicked:
        return
    if not token.strip():
        st.error("Paste your API token before validation.")
        st.session_state.token_validated = False
        return

    with st.spinner("Validating token against demo endpoints..."):
        try:
            probe_anthropic(api_token=token.strip(), insecure_tls=INSECURE_DEMO_TLS)
            probe_mcp(
                api_token=token.strip(),
                mcp_url=_build_config(token.strip()).deltastream_mcp_url,
                insecure_tls=INSECURE_DEMO_TLS,
            )
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
            st.session_state.token_validated = False
            return

    st.session_state.token_validated = True
    st.session_state.validated_token = token.strip()
    st.success("Token is valid for both Anthropic and DeltaStream MCP.")


def _render_chat_panel() -> None:
    st.subheader("3) Chat")
    st.caption(
        "Agent guardrails only allow SELECT queries on: "
        + ", ".join(f"`{name}`" for name in ALLOWED_MVIEW_FQNS)
        + "."
    )

    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant" and message.get("sql"):
                with st.expander("Query details"):
                    st.code(message["sql"], language="sql")
                    st.write(f"Tool calls: {message.get('tool_calls', 0)}")
                    failures = message.get("tool_failures", [])
                    if failures:
                        st.write("Tool failures:")
                        for item in failures:
                            st.code(item)

    prompt = st.chat_input(
        "Ask a question about the allowed materialized views",
        disabled=not st.session_state.token_validated,
    )
    if not prompt:
        return

    st.session_state.chat_history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        config = _build_config(st.session_state.api_token.strip())
    except ValidationError as exc:
        st.error(f"Configuration error: {exc}")
        return

    backend = PydanticAIDemoBackend(config=config)
    history = [
        ChatMessage(role=item["role"], content=item["content"])
        for item in st.session_state.chat_history
    ]

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                result = backend.ask(prompt=prompt, history=history)
            except QueryPolicyError as exc:
                error_text = f"Blocked by safety policy: {exc}"
                st.error(error_text)
                st.session_state.chat_history.append({"role": "assistant", "content": error_text})
                return
            except MCPConnectionError as exc:
                error_text = f"MCP connection failed: {exc}"
                st.error(error_text)
                st.session_state.chat_history.append({"role": "assistant", "content": error_text})
                return
            except Exception as exc:  # noqa: BLE001
                error_text = f"Agent request failed: {_format_exception(exc)}"
                st.error(error_text)
                st.session_state.chat_history.append({"role": "assistant", "content": error_text})
                return

        st.markdown(result.answer)
        with st.expander("Query details"):
            st.code(result.generated_sql, language="sql")
            st.write(f"Tool calls: {result.tool_calls}")
            if result.tool_failures:
                st.write("Tool failures:")
                for item in result.tool_failures:
                    st.code(item)

    st.session_state.chat_history.append(
        {
            "role": "assistant",
            "content": result.answer,
            "sql": result.generated_sql,
            "tool_calls": result.tool_calls,
            "tool_failures": result.tool_failures,
            "evidence_relations": result.evidence_relations,
        }
    )


def _build_config(token: str) -> AppConfig:
    return AppConfig(api_token=token)


def _format_exception(exc: BaseException) -> str:
    if isinstance(exc, ExceptionGroup):
        details = []
        for sub_exc in exc.exceptions:
            details.append(str(sub_exc))
        flattened = "; ".join(item for item in details if item)
        return flattened or str(exc)
    return str(exc)


if __name__ == "__main__":
    main()
