"""
benchmark/shared/bench_core.py — core harness primitives for the AI Returns Benchmark.

Key types:
  AgentConfig   — loaded from an agent's config.json; holds MCP URL, token env var, system prompt.
  RunRecord     — raw output of a single (agent, model, scenario, repeat) run: prompt, response,
                  tool calls, token counts, latency, cost.
  VerdictRecord — pass/fail judgement produced by grading a RunRecord against the answer key;
                  includes expected vs. actual payloads and failure reasons.

Key function:
  run_one(agent_cfg, model_id, candidate, repeat_idx) -> RunRecord
    Executes one benchmark run.  Has a 3-attempt outer retry loop (backoff 1.5 * 2^attempt s)
    that retries on transient errors (connection, overloaded, rate-limit, timeout, MCP server).
    The BENCH_TOOL_RETRIES env var (default 2, recommended 4) controls MCP-level retries inside
    PydanticAI — a separate layer from the outer loop.

TLS note: TLS verification is disabled when DELTASTREAM_INSECURE=1 **or** when the MCP URL
  matches the public production endpoint (https://api.deltastream.io/mcp/v2).  Do not change
  that logic without understanding both conditions.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from . import pricing


class DecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class AgentConfig:
    name: str
    mcp_url: str
    mcp_server_name: str
    mcp_token: str
    system_prompt: str


@dataclass
class RunRecord:
    stage: str
    run_id: str
    agent: str
    model: str
    prompt_id: int
    repeat_index: int
    prompt_text: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    tool_calls: int
    latency_ms: int
    cost_usd: float | None
    final_text: str
    parsed_payload: dict[str, Any] | None
    stop_reason: str | None
    error: str | None = None


@dataclass
class VerdictRecord:
    stage: str
    run_id: str
    agent: str
    model: str
    prompt_id: int
    repeat_index: int
    verdict: str
    failure_reasons: list[str]
    parsed_payload: dict[str, Any] | None


def _anthropic_model(model: str) -> AnthropicModel:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    provider = AnthropicProvider(api_key=os.environ["ANTHROPIC_API_KEY"])
    return AnthropicModel(model, provider=provider)


def _build_agent(agent_cfg: AgentConfig, model: str) -> Agent[None, DecisionPayload]:
    timeout_s = float(os.environ.get("ANTHROPIC_TIMEOUT_SECONDS", "600"))
    tool_retries = int(os.environ.get("BENCH_TOOL_RETRIES", "2"))
    insecure_env = os.environ.get("DELTASTREAM_INSECURE", "").lower() in {
        "1",
        "true",
        "yes",
        "y",
    }
    insecure_url = agent_cfg.mcp_url.startswith("https://api.deltastream.io/mcp/v2")
    insecure = insecure_env or insecure_url
    http_client = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {agent_cfg.mcp_token}"},
        timeout=timeout_s,
        verify=not insecure,
    )
    server = MCPServerStreamableHTTP(
        agent_cfg.mcp_url,
        http_client=http_client,
        max_retries=tool_retries,
        include_instructions=True,
    )
    return Agent(
        _anthropic_model(model),
        instructions=agent_cfg.system_prompt,
        output_type=DecisionPayload,
        tool_retries=tool_retries,
        toolsets=[server],
    )


def _format_exception_chain(err: BaseException) -> str:
    pieces = [f"{type(err).__name__}: {err}"]
    cur = err
    depth = 0
    while depth < 5:
        nxt = cur.__cause__ or cur.__context__
        if nxt is None:
            break
        pieces.append(f"caused_by[{depth + 1}] {type(nxt).__name__}: {nxt}")
        cur = nxt
        depth += 1
    return " | ".join(pieces)


def _extract_retry_details(msgs: list[Any]) -> str | None:
    retry_rows: list[str] = []
    for msg in msgs:
        for part in getattr(msg, "parts", []):
            if type(part).__name__ != "RetryPromptPart":
                continue
            tool_name = getattr(part, "tool_name", None)
            content = getattr(part, "content", None)
            if tool_name is None:
                continue
            retry_rows.append(f"tool={tool_name} retry={content}")
    if not retry_rows:
        return None
    return " || ".join(retry_rows[-3:])


def load_agent(agent_dir: Path) -> AgentConfig:
    cfg = json.loads((agent_dir / "config.json").read_text())
    token_env = cfg.get("mcp_token_env")
    if not token_env:
        raise RuntimeError(f"missing mcp_token_env in {agent_dir / 'config.json'}")
    token = os.environ.get(token_env)
    if not token:
        raise RuntimeError(f"missing required env var: {token_env}")
    return AgentConfig(
        name=cfg["name"],
        mcp_url=cfg.get("mcp_url", "https://api.deltastream.io/mcp/v2"),
        mcp_server_name=cfg.get("mcp_server_name", "deltastream"),
        mcp_token=token,
        system_prompt=(agent_dir / "system_prompt.md").read_text(),
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def extract_json_payload(text: str) -> tuple[dict[str, Any] | None, str | None]:
    if not text:
        return None, "empty_final_text"
    fences = re.findall(r"```(?:json)?\s*\n(.*?)\n```", text, flags=re.S)
    candidates = list(reversed(fences))
    if text.strip().startswith("{") and text.strip().endswith("}"):
        candidates.append(text.strip())
    for raw in candidates:
        try:
            parsed = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed, None
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed, None
        except json.JSONDecodeError:
            pass
    return None, "unparseable_json"


def _usage_dict(usage: Any) -> dict[str, int]:
    if usage is None:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }

    def g(k: str) -> int:
        v = getattr(usage, k, None)
        if v is None and hasattr(usage, "model_dump"):
            v = usage.model_dump().get(k)
        return int(v or 0)

    return {
        "input_tokens": g("input_tokens"),
        "output_tokens": g("output_tokens"),
        "cache_creation_input_tokens": g("cache_creation_input_tokens"),
        "cache_read_input_tokens": g("cache_read_input_tokens"),
    }


def _final_text(content_blocks: list[Any]) -> str:
    parts = []
    for blk in content_blocks:
        if getattr(blk, "type", None) == "text":
            parts.append(blk.text or "")
    return "\n".join(parts).strip()


def _count_tool_calls(content_blocks: list[Any]) -> int:
    count = 0
    for blk in content_blocks:
        if getattr(blk, "type", None) == "mcp_tool_use":
            count += 1
    return count


def run_one(
    *,
    run_id: str,
    stage: str,
    agent: AgentConfig,
    model: str,
    prompt_id: int,
    prompt_text: str,
    repeat_index: int,
    max_tokens: int = 4096,
) -> RunRecord:
    t0 = time.time()
    last_err: Exception | None = None
    result = None
    pa_agent = _build_agent(agent, model)

    async def _invoke(prompt: str) -> Any:
        async with pa_agent:
            return await pa_agent.run(prompt)

    for attempt in range(3):
        call_started = time.time()
        stop_heartbeat = threading.Event()

        def _heartbeat() -> None:
            while not stop_heartbeat.wait(30):
                waited = int(time.time() - call_started)
                print(
                    f"   ... waiting {waited}s model={model} prompt={prompt_id} attempt={attempt + 1}",
                    flush=True,
                )

        hb = threading.Thread(target=_heartbeat, daemon=True)
        hb.start()
        run_messages: list[Any] = []
        try:
            with capture_run_messages() as messages:
                result = asyncio.run(_invoke(prompt_text))
                run_messages = list(messages)
            last_err = None
            break
        except Exception as e:  # noqa: BLE001
            retry_detail = _extract_retry_details(run_messages)
            base = _format_exception_chain(e)
            detail = f"{base} | retry_details={retry_detail}" if retry_detail else base
            last_err = RuntimeError(detail)
            msg = detail.lower()
            transient = (
                "connection" in msg
                or "overloaded" in msg
                or "rate" in msg
                or "timeout" in msg
                or "mcp server" in msg
            )
            if transient and attempt < 2:
                time.sleep(1.5 * (2**attempt))
                continue
            break
        finally:
            stop_heartbeat.set()
            hb.join(timeout=0.2)

    if result is None:
        return RunRecord(
            stage=stage,
            run_id=run_id,
            agent=agent.name,
            model=model,
            prompt_id=prompt_id,
            repeat_index=repeat_index,
            prompt_text=prompt_text,
            input_tokens=0,
            output_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            tool_calls=0,
            latency_ms=int((time.time() - t0) * 1000),
            cost_usd=None,
            final_text="",
            parsed_payload=None,
            stop_reason=None,
            error=f"{type(last_err).__name__}: {last_err}" if last_err else "unknown",
        )

    payload = result.output
    usage_obj = result.usage()
    usage = _usage_dict(usage_obj)
    payload_dict = payload.model_dump()
    output_text = json.dumps(payload_dict, sort_keys=True)
    tool_calls = int(getattr(usage_obj, "tool_calls", 0) or 0)
    return RunRecord(
        stage=stage,
        run_id=run_id,
        agent=agent.name,
        model=model,
        prompt_id=prompt_id,
        repeat_index=repeat_index,
        prompt_text=prompt_text,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cache_creation_input_tokens=usage["cache_creation_input_tokens"],
        cache_read_input_tokens=usage["cache_read_input_tokens"],
        tool_calls=tool_calls,
        latency_ms=int((time.time() - t0) * 1000),
        cost_usd=pricing.cost_usd(model, usage),
        final_text=output_text,
        parsed_payload=payload_dict,
        stop_reason=getattr(result, "stop_reason", None),
    )


def median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def as_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [asdict(r) for r in rows]
