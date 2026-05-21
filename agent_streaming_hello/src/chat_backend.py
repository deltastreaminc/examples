"""Pluggable chat backend interfaces and pydantic-ai implementation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from .config import AppConfig
from .constants import MV_PAGEVIEW_COUNTS


class AgentAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Keep output structured so the UI can reliably render answer + evidence.
    answer: str = Field(description="Natural language answer for the user")
    evidence_relations: list[str] = Field(
        default_factory=list,
        description="Relation names used while answering",
    )


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatResult:
    answer: str
    evidence_relations: list[str]
    tool_calls: int


class ChatBackend:
    # Small interface so you can swap providers later (OpenAI, Bedrock, etc.)
    # without changing Streamlit UI code.
    def ask(self, prompt: str, history: list[ChatMessage]) -> ChatResult:  # pragma: no cover - interface
        raise NotImplementedError


class PydanticAIAnthropicMCPBackend(ChatBackend):
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def _system_prompt(self) -> str:
        # Prompt is intentionally strict about fully-qualified relation names
        # so the agent does not drift into a different default DB/schema.
        return (
            "You are a helpful analytics assistant for a pageviews tutorial. "
            "Always use fully-qualified relation names with database and schema. "
            "The demo relations are `hello_world_demo.public.pageviews_stream` and "
            f"`hello_world_demo.public.{MV_PAGEVIEW_COUNTS}`. "
            "Use `hello_world_demo.public.pageview_counts_mv` whenever pageview counts "
            "are requested. "
            "Give concise answers. Always provide the list of relation names you used "
            "in evidence_relations. If no data is available yet, explain what the user "
            "should run next."
        )

    async def _run_async(self, prompt: str, history: list[ChatMessage]) -> ChatResult:
        # Model/provider wiring for Anthropic in pydantic-ai.
        provider = AnthropicProvider(api_key=self._config.anthropic_api_key.get_secret_value())
        model = AnthropicModel(self._config.anthropic_model, provider=provider)

        # HTTP client carries DeltaStream token for MCP tool calls.
        http_client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._config.deltastream_api_token.get_secret_value()}"
            },
            timeout=120.0,
        )
        # Configure the DeltaStream MCP server tool endpoint used by the agent.
        server = MCPServerStreamableHTTP(
            self._config.deltastream_mcp_url,
            http_client=http_client,
            include_instructions=True,
            max_retries=2,
        )

        # Agent gets one model plus one MCP toolset.
        agent = Agent(
            model,
            instructions=self._system_prompt(),
            output_type=AgentAnswer,
            toolsets=[server],
            tool_retries=2,
        )

        # Flatten recent chat history into prompt text. For bigger apps, you may
        # want to switch to message-native history instead of text concatenation.
        history_text = "\n".join(
            f"{message.role.upper()}: {message.content}" for message in history[-10:]
        )
        full_prompt = (
            "Conversation history:\n"
            f"{history_text}\n\n"
            "User question:\n"
            f"{prompt}"
        )

        try:
            async with agent:
                result = await agent.run(full_prompt)
        finally:
            # Always close HTTP client to avoid connection leaks.
            await http_client.aclose()

        output = result.output
        # `tool_calls` is useful for debugging and UI visibility.
        usage = result.usage()
        tool_calls = int(getattr(usage, "tool_calls", 0) or 0)
        return ChatResult(
            answer=output.answer,
            evidence_relations=output.evidence_relations,
            tool_calls=tool_calls,
        )

    def ask(self, prompt: str, history: list[ChatMessage]) -> ChatResult:
        # Sync wrapper used by Streamlit callbacks.
        return asyncio.run(self._run_async(prompt=prompt, history=history))
