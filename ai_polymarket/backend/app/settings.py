from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # Build/version marker logged loudly at startup so you can confirm the running
    # pod is the image you just built. Override per build via env BUILD_MARKER
    # (e.g. BUILD_MARKER=1.0.2-logging in the Dockerfile/deployment).
    build_marker: str = "dev-mcp-request-logging"
    build_date: str = "unknown"
    # Base URL of the AI demo backend. All demo-hosted endpoints are derived from this.
    ai_demo_backend: str = "https://demo.deltastream.io"
    deltastream_mcp_url: str = "https://api-kd8j38.stage.deltastream-internal.name/mcp/v2"
    anthropic_api_key: str | None = None
    insecure_demo_tls: bool = False

    model_name: str = "google:gemini-3.5-flash"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    # Optional path prefix the app is served under when the Ingress does NOT strip
    # the prefix before forwarding to the pod. Must start with '/' and must NOT end
    # with '/'. Leave empty for root deployments or when the Ingress strips the prefix.
    # Example: ROOT_PATH=/polymarket
    root_path: str = ""
    query_limit: int = 250
    primary_query_limit: int = 500
    # Conversation memory: keep the most recent N transcript messages (user +
    # assistant) per conversation so follow-up questions ("that market", "all of
    # this") resolve against prior turns. In-process only (single replica).
    conversation_max_messages: int = 10
    conversation_ttl_seconds: float = 1800.0
    quick_mode_enabled: bool = True
    quick_mode_max_attempts: int = 2
    quick_mode_max_tokens: int = 1400
    quick_mode_timeout_seconds: float = 90.0
    # Seconds of SSE stream inactivity before sending a keepalive comment. Keeps
    # gateways/proxies from closing the long-lived chat stream during quiet gaps.
    sse_heartbeat_seconds: float = 5.0
    # Gemini is a thinking model; reasoning tokens share the output budget and dynamic
    # thinking can dominate latency on multi-tool agentic tasks.
    # Gemini 3.x: use thinking_level ("low"/"high"). Gemini 2.5: use thinking_budget.
    gemini_max_output_tokens: int = 8192
    gemini_thinking_level: str | None = "low"
    gemini_thinking_budget: int | None = None

    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV_PATH),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def signup_api_url(self) -> str:
        return f"{self.ai_demo_backend.rstrip('/')}/api/signup"

    @property
    def anthropic_base_url(self) -> str:
        return f"{self.ai_demo_backend.rstrip('/')}/anthropic"

    @property
    def gemini_base_url(self) -> str:
        return f"{self.ai_demo_backend.rstrip('/')}/gemini"

    @property
    def llm_provider(self) -> str:
        """Derive the LLM provider from the MODEL_NAME prefix.

        Returns "google" for `google:`/`gemini:` prefixes, otherwise "anthropic".
        """
        prefix = self.model_name.split(":", 1)[0].strip().lower()
        if prefix in {"google", "gemini"}:
            return "google"
        return "anthropic"


settings = Settings()
