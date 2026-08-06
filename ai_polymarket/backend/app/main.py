from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from .agent import _bare_model_name, messages_from_transcript, stream_answer
from .http_clients import probe_anthropic, probe_gemini, probe_mcp, signup
from .schemas import ChatRequest, SignupRequest
from .settings import settings

logger = logging.getLogger("polymarket.agent")
# Ensure our per-call LLM usage summary is visible at INFO. Under uvicorn the root
# logger often has no INFO handler, so records would otherwise be dropped — attach
# our own stream handler and stop propagation to avoid duplicate lines.
logger.setLevel(logging.INFO)
if not logger.handlers:
    _log_handler = logging.StreamHandler()
    _log_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(_log_handler)
logger.propagate = False

# Eye-catcher so you can confirm the running pod is the image you just built.
# Bump settings.build_marker (or set BUILD_MARKER env) each build to verify rollout.
logger.info(
    "========== POLYMARKET AGENT STARTUP build=%s date=%s model=%s mcp=%s ==========",
    settings.build_marker,
    settings.build_date,
    settings.model_name,
    settings.deltastream_mcp_url,
)


FRONTEND_DIST_DIR = Path(os.getenv("FRONTEND_DIST_DIR", "frontend/dist"))

# Normalised prefix (no trailing slash, empty = root deployment).
# The Ingress forwards ALL traffic for this container (GET + POST) through the
# /polymarket rule, unstripped, so every route must be served under this prefix.
# (Root /api/* on the demo host belongs to the demo platform, not this app.)
_ROOT_PATH = settings.root_path.rstrip("/")

# Public base path the SPA is served under (always ends with '/'). Injected into
# index.html at runtime so a single build works at any mount path — no build-time
# BASE_PATH needed. "/" for root deployments, "/polymarket/" under ROOT_PATH.
_APP_BASE = f"{_ROOT_PATH}/" if _ROOT_PATH else "/"


def _render_index() -> HTMLResponse | JSONResponse:
    """Serve index.html with the runtime base path injected.

    Adds `<base href="{_APP_BASE}">` (so relative asset URLs resolve correctly)
    and `window.__APP_BASE__` (so the chat API call targets the right prefix).
    """
    index_file = FRONTEND_DIST_DIR / "index.html"
    if not index_file.is_file():
        return JSONResponse({"detail": "Frontend build not found"}, status_code=404)
    html = index_file.read_text(encoding="utf-8")
    injection = (
        f'<base href="{_APP_BASE}">'
        f'<script>window.__APP_BASE__={json.dumps(_APP_BASE)};</script>'
        f'<script>window.__BUILD_INFO__={json.dumps({"buildDate": settings.build_date, "buildMarker": settings.build_marker})};</script>'
    )
    # Insert immediately after <head> so it precedes Vite's asset tags.
    if "<head>" in html:
        html = html.replace("<head>", "<head>" + injection, 1)
    else:
        html = injection + html
    return HTMLResponse(html)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Authorization must be Bearer token")
    token = authorization[len(prefix):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token cannot be empty")
    return token


def _validate_demo_token(token: str) -> None:
    try:
        if settings.llm_provider == "google":
            probe_gemini(
                token,
                settings.gemini_base_url,
                _bare_model_name(settings.model_name),
                settings.insecure_demo_tls,
            )
        else:
            anthropic_token = settings.anthropic_api_key or token
            probe_anthropic(anthropic_token, settings.anthropic_base_url, settings.insecure_demo_tls)
        probe_mcp(token, settings.deltastream_mcp_url, settings.insecure_demo_tls)
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _friendly_stream_error_message(error_message: str) -> str:
    if "429" in error_message and "Rate limit exceeded" in error_message:
        return (
            "Anthropic demo rate limit exceeded. Please wait a minute and retry, "
            "or reduce repeated requests while testing."
        )
    lowered = error_message.lower()
    if (
        "name resolution" in lowered
        or "name or service not known" in lowered
        or "failed to resolve" in lowered
        or "nodename nor servname" in lowered
        or "connection refused" in lowered
        or "network is unreachable" in lowered
    ):
        return (
            "The backend could not reach the model/MCP endpoints. From inside the "
            "deployment, set AI_DEMO_BACKEND (and DELTASTREAM_MCP_URL) to addresses "
            "the pod can resolve, then retry. Details: " + error_message
        )
    if "status_code: 504" in lowered or "upstream request timeout" in lowered or "gateway timeout" in lowered:
        return (
            "The model timed out before completing the response. "
            "Please retry, or ask a narrower question to reduce response time."
        )
    return error_message


# Seconds of stream inactivity before emitting an SSE keepalive comment. Keeps
# proxies/gateways from closing the long-lived chat stream during a long model
# generation (which can run 15-40s with no intermediate events). Tunable via the
# SSE_HEARTBEAT_SECONDS env var.
_SSE_HEARTBEAT_SECONDS = max(1.0, settings.sse_heartbeat_seconds)


# ---------------------------------------------------------------------------
# Background chat jobs (polling model).
#
# Many gateways buffer responses and enforce a short total-request timeout
# (e.g. Envoy's 15s default), which makes long-lived SSE streaming unusable.
# Instead, /api/chat/start launches the agent as a background job that buffers
# events, and the client polls /api/chat/poll for new events in short requests
# that are immune to buffering and total-request timeouts.
#
# NOTE: jobs are stored in-process, so run a single worker / single replica
# (or enable session affinity) so polls reach the same process that started
# the job. The default uvicorn command uses one worker.
# ---------------------------------------------------------------------------

_CHAT_JOBS: dict[str, dict[str, Any]] = {}
_CHAT_JOB_TTL_SECONDS = 600.0

# In-process conversation memory (single replica; documented above). Keyed by a
# client-supplied conversation_id, each entry holds a plain transcript of
# (question, answer) pairs plus a last-updated timestamp. Reconstructed into
# pydantic-ai message history on each turn so follow-ups can resolve references
# like "that market" against prior answers. Lost on restart — fine for a demo.
_CONVERSATIONS: dict[str, dict[str, Any]] = {}


def _cleanup_conversations() -> None:
    now = time.monotonic()
    stale = [
        conversation_id
        for conversation_id, entry in _CONVERSATIONS.items()
        if now - entry["updated"] > settings.conversation_ttl_seconds
    ]
    for conversation_id in stale:
        _CONVERSATIONS.pop(conversation_id, None)


def _conversation_history(conversation_id: str | None) -> list[Any] | None:
    if not conversation_id:
        return None
    entry = _CONVERSATIONS.get(conversation_id)
    if not entry or not entry["transcript"]:
        return None
    return messages_from_transcript(entry["transcript"])


def _record_conversation_turn(
    conversation_id: str | None, question: str, answer: str
) -> None:
    if not conversation_id or not question or not answer:
        return
    entry = _CONVERSATIONS.setdefault(conversation_id, {"transcript": [], "updated": 0.0})
    entry["transcript"].append((question, answer))
    # Keep the most recent N messages (each turn = 2 messages: Q + A).
    max_turns = max(1, settings.conversation_max_messages // 2)
    if len(entry["transcript"]) > max_turns:
        entry["transcript"] = entry["transcript"][-max_turns:]
    entry["updated"] = time.monotonic()


def _log_llm_usage(
    event_type: str,
    payload: Any,
    message: str,
    conversation_id: str | None,
    source: str,
) -> None:
    """Emit one INFO line per user call summarizing LLM request/token usage."""
    if event_type != "llm_timing" or not isinstance(payload, dict):
        return
    if payload.get("kind") != "summary":
        return
    preview = (message or "").strip().replace("\n", " ")
    if len(preview) > 80:
        preview = preview[:77] + "..."
    logger.info(
        "llm call [%s]: model_requests=%d tool_calls=%d attempts=%d "
        "input_tokens=%d output_tokens=%d duration_ms=%d outcome=%s conversation=%s q=%r",
        source,
        payload.get("model_requests", 0),
        payload.get("tool_calls", 0),
        payload.get("attempts", 0),
        payload.get("input_tokens", 0),
        payload.get("output_tokens", 0),
        payload.get("duration_ms", 0),
        payload.get("outcome", "?"),
        conversation_id or "-",
        preview,
    )


def _event_to_dict(event_type: str, payload: Any) -> dict[str, Any] | None:
    """Map an internal agent event to a client event {event, data}."""
    if event_type in {"query_mview", "execute_dsql"}:
        return {"event": "sql", "data": {"statement": payload}}
    if event_type == "doc_search":
        return {"event": "doc_search", "data": {"query": payload}}
    if event_type == "llm_timing":
        return {"event": "llm_timing", "data": payload}
    if event_type == "reset":
        return {"event": "reset", "data": {}}
    if event_type == "token":
        return {"event": "token", "data": {"text": payload}}
    if event_type == "final":
        return {"event": "final", "data": {"text": payload}}
    if event_type == "follow_ups" and isinstance(payload, dict):
        return {"event": "follow_ups", "data": payload}
    return None


def _cleanup_chat_jobs() -> None:
    now = time.monotonic()
    stale = [
        job_id
        for job_id, job in _CHAT_JOBS.items()
        if now - job["updated"] > _CHAT_JOB_TTL_SECONDS
    ]
    for job_id in stale:
        _CHAT_JOBS.pop(job_id, None)


async def _run_chat_job(
    job_id: str, message: str, token: str, conversation_id: str | None = None
) -> None:
    job = _CHAT_JOBS[job_id]

    def _append(event: dict[str, Any]) -> None:
        job["events"].append(event)
        job["updated"] = time.monotonic()

    # Token validation makes blocking HTTP probes; run off the event loop.
    try:
        await asyncio.to_thread(_validate_demo_token, token)
    except HTTPException as exc:
        _append({"event": "error", "data": {"message": str(exc.detail)}})
        job["status"] = "error"
        job["updated"] = time.monotonic()
        return

    history = _conversation_history(conversation_id)
    final_text = ""
    try:
        async for event_type, payload in stream_answer(message, token, history=history):
            if event_type == "final" and isinstance(payload, str):
                final_text = payload
            _log_llm_usage(event_type, payload, message, conversation_id, "poll")
            event = _event_to_dict(event_type, payload)
            if event is not None:
                _append(event)
    except Exception as exc:  # noqa: BLE001
        _append({"event": "error", "data": {"message": _friendly_stream_error_message(str(exc))}})
        job["status"] = "error"
        job["updated"] = time.monotonic()
        return

    _record_conversation_turn(conversation_id, message, final_text)
    _append({"event": "done", "data": {"status": "completed"}})
    job["status"] = "done"
    job["updated"] = time.monotonic()


# ---------------------------------------------------------------------------
# Inner app — all routes registered without a prefix, then mounted under
# ROOT_PATH so they are reachable at /<prefix>/api/* and /<prefix>/*.
# ---------------------------------------------------------------------------

_inner = FastAPI(title="Polymarket Live Signal Radar", version="0.1.0")


@_inner.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "build_marker": settings.build_marker,
            "build_date": settings.build_date,
        }
    )


@_inner.post("/api/signup")
async def api_signup(request: SignupRequest) -> JSONResponse:
    try:
        message = signup(request.email, settings.signup_api_url, settings.insecure_demo_tls)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return JSONResponse({"message": message})


@_inner.post("/api/token/validate")
async def validate_token(authorization: str | None = Header(default=None)) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    _validate_demo_token(token)
    return JSONResponse({"ok": True})


@_inner.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    # Extract the token synchronously so an obviously malformed request fails fast
    # with a 401 before the stream opens. Full validation (which makes blocking
    # network probes) is done inside the generator so the first byte flushes
    # immediately and the gateway sees the response start without delay.
    token = _extract_bearer_token(authorization)

    async def event_generator() -> AsyncGenerator[str, None]:
        # Flush an initial comment + start event ASAP so the gateway receives
        # response headers / first byte immediately and treats this as an open
        # stream rather than a stalled request.
        yield ": open\n\n"
        yield _sse("start", {"status": "started"})

        # Token validation makes blocking HTTP probes (httpx.Client); run it off
        # the event loop so heartbeats and the stream stay responsive.
        try:
            await asyncio.to_thread(_validate_demo_token, token)
        except HTTPException as exc:
            yield _sse("error", {"message": str(exc.detail)})
            yield _sse("done", {"status": "error"})
            return

        # Drain the agent stream through a queue so a heartbeat timeout never
        # cancels the in-flight agent work (asyncio.wait_for would cancel the
        # awaited coroutine; cancelling queue.get() is safe).
        queue: asyncio.Queue = asyncio.Queue()
        _DONE = object()

        async def _produce() -> None:
            try:
                history = _conversation_history(request.conversation_id)
                async for item in stream_answer(request.message, token, history=history):
                    await queue.put(("event", item))
            except Exception as exc:  # noqa: BLE001
                await queue.put(("error", _friendly_stream_error_message(str(exc))))
            finally:
                await queue.put(("done", _DONE))

        producer = asyncio.create_task(_produce())
        rendered = ""
        try:
            while True:
                try:
                    kind, value = await asyncio.wait_for(
                        queue.get(), timeout=_SSE_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue

                if kind == "done":
                    break
                if kind == "error":
                    yield _sse("error", {"message": value})
                    yield _sse("done", {"status": "error"})
                    return

                event_type, payload = value
                if event_type in {"query_mview", "execute_dsql"}:
                    yield _sse("sql", {"statement": payload})
                elif event_type == "doc_search":
                    yield _sse("doc_search", {"query": payload})
                elif event_type == "llm_timing":
                    _log_llm_usage(
                        event_type, payload, request.message, request.conversation_id, "stream"
                    )
                    yield _sse("llm_timing", payload)
                elif event_type == "reset":
                    rendered = ""
                    yield _sse("reset", {})
                elif event_type == "token":
                    rendered += payload
                    yield _sse("token", {"text": payload})
                elif event_type == "final":
                    rendered = payload
                    yield _sse("final", {"text": payload})
                elif event_type == "follow_ups" and isinstance(payload, dict):
                    yield _sse("follow_ups", payload)
        finally:
            if not producer.done():
                producer.cancel()

        _record_conversation_turn(request.conversation_id, request.message, rendered)
        yield _sse("done", {"status": "completed"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@_inner.post("/api/chat/start")
async def chat_start(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Start a chat as a background job and return its id for polling."""
    token = _extract_bearer_token(authorization)
    _cleanup_chat_jobs()
    _cleanup_conversations()
    job_id = uuid.uuid4().hex
    _CHAT_JOBS[job_id] = {
        "events": [],
        "status": "running",
        "updated": time.monotonic(),
    }
    # Keep a reference to the task so it isn't garbage-collected mid-run.
    task = asyncio.create_task(
        _run_chat_job(job_id, request.message, token, request.conversation_id)
    )
    _CHAT_JOBS[job_id]["task"] = task
    return JSONResponse({"job_id": job_id})


@_inner.get("/api/chat/poll/{job_id}")
async def chat_poll(job_id: str, cursor: int = 0) -> JSONResponse:
    """Return chat events buffered since `cursor`, plus the job status."""
    job = _CHAT_JOBS.get(job_id)
    if job is None:
        return JSONResponse({"detail": "Chat job not found or expired"}, status_code=404)

    events = job["events"]
    if cursor < 0:
        cursor = 0
    new_events = events[cursor:]
    next_cursor = cursor + len(new_events)
    status = job["status"]

    # Once the client has drained all events of a finished job, drop it.
    if status in {"done", "error"} and next_cursor >= len(events):
        _CHAT_JOBS.pop(job_id, None)

    return JSONResponse(
        {"events": new_events, "cursor": next_cursor, "status": status}
    )


@_inner.get("/", include_in_schema=False, response_model=None)
async def frontend_index():
    return _render_index()


@_inner.get("/{full_path:path}", include_in_schema=False, response_model=None)
async def frontend_routes(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    requested_file = FRONTEND_DIST_DIR / full_path
    if requested_file.is_file():
        return FileResponse(requested_file)

    # Return 404 for missing static assets rather than the SPA shell —
    # serving HTML for a JS/CSS request causes a browser MIME type error.
    static_extensions = {".js", ".css", ".png", ".ico", ".svg", ".woff", ".woff2", ".ttf", ".map"}
    if any(full_path.endswith(ext) for ext in static_extensions):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return _render_index()


# ---------------------------------------------------------------------------
# Outer app — mounts the inner app under ROOT_PATH (or at root when unset).
# ---------------------------------------------------------------------------

app = FastAPI(title="Polymarket Live Signal Radar", version="0.1.0")

if _ROOT_PATH:
    app.mount(_ROOT_PATH, _inner)
else:
    app.mount("/", _inner)
