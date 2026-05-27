"""Typed runtime configuration for the starter app."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, SecretStr

from .constants import ANTHROPIC_BASE_URL, DEFAULT_ANTHROPIC_MODEL, DELTASTREAM_MCP_URL, INSECURE_DEMO_TLS


class AppConfig(BaseModel):
    """Configuration required by the chat backend."""

    model_config = ConfigDict(extra="forbid")

    api_token: SecretStr
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    anthropic_base_url: str = ANTHROPIC_BASE_URL
    deltastream_mcp_url: str = DELTASTREAM_MCP_URL
    insecure_tls: bool = INSECURE_DEMO_TLS
