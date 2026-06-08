"""Application constants for the signup chat starter."""

from __future__ import annotations

import os


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}

SIGNUP_API_URL = os.getenv("SIGNUP_API_URL", "https://demo.local.deltastream.io/api/signup")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://demo.local.deltastream.io/anthropic/")
DELTASTREAM_MCP_URL = os.getenv(
    "DELTASTREAM_MCP_URL",
    "https://api-kd8j38.stage.deltastream-internal.name/mcp/v2",
)

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
ALLOWED_MVIEW_FQNS = (
    "starter.public.pageviews_mview",
)

# demo.local endpoints use self-signed TLS certificates.
INSECURE_DEMO_TLS = _env_bool("INSECURE_DEMO_TLS", True)
