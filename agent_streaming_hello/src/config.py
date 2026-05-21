"""Configuration models and validation for the pageviews demo."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .constants import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_DELTASTREAM_API_URL,
    DEFAULT_DELTASTREAM_MCP_URL,
)


class AppConfig(BaseModel):
    """Runtime configuration collected from the UI."""

    model_config = ConfigDict(extra="forbid")

    kafka_brokers: str = Field(min_length=1)
    kafka_username: str = Field(min_length=1)
    kafka_password: SecretStr
    anthropic_api_key: SecretStr
    deltastream_api_token: SecretStr

    deltastream_api_url: str = DEFAULT_DELTASTREAM_API_URL
    deltastream_mcp_url: str = DEFAULT_DELTASTREAM_MCP_URL
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL

    @field_validator("kafka_brokers")
    @classmethod
    def _validate_brokers(cls, value: str) -> str:
        brokers = [item.strip() for item in value.split(",") if item.strip()]
        if not brokers:
            raise ValueError("Provide at least one Kafka broker host:port")
        return ",".join(brokers)

    def bootstrap_servers(self) -> list[str]:
        return [item.strip() for item in self.kafka_brokers.split(",") if item.strip()]


class SetupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    steps: list[str]
    statements: list[str] = Field(default_factory=list)


class CleanupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    steps: list[str]
    statements: list[str] = Field(default_factory=list)


class PipelineStatusResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    ready: bool
    details: list[str]


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kafka_ok: bool
    anthropic_ok: bool
    deltastream_ok: bool
    details: list[str]
