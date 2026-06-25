from __future__ import annotations

import json
import os
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .agent import stream_answer
from .deltastream_context import DeltaStreamMCPService
from .http_clients import probe_anthropic, probe_mcp, signup
from .schemas import ChatRequest, SignupRequest
from .settings import settings


app = FastAPI(title="Polymarket Live Signal Radar", version="0.1.0")
context_service = DeltaStreamMCPService()
FRONTEND_DIST_DIR = Path(os.getenv("FRONTEND_DIST_DIR", "frontend/dist"))


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True})


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Authorization must be Bearer token")
    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token cannot be empty")
    return token


@app.post("/api/signup")
async def api_signup(request: SignupRequest) -> JSONResponse:
    message = signup(request.email, settings.signup_api_url, settings.insecure_demo_tls)
    return JSONResponse({"message": message})


@app.post("/api/token/validate")
async def validate_token(authorization: str | None = Header(default=None)) -> JSONResponse:
    token = _extract_bearer_token(authorization)
    probe_anthropic(token, settings.anthropic_base_url, settings.insecure_demo_tls)
    probe_mcp(token, settings.deltastream_mcp_url, settings.insecure_demo_tls)
    return JSONResponse({"ok": True})


@app.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    token = _extract_bearer_token(authorization)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield _sse("start", {"status": "started"})
            context_bundle = await context_service.fetch_context(request.message, token)
            yield _sse(
                "context_meta",
                {
                    "question_mode": context_bundle.question_mode,
                    "target_asset": context_bundle.target_asset,
                    "target_market_title": context_bundle.target_market_title,
                    "target_outcome_label": context_bundle.target_outcome_label,
                    "latest_ctx_time_ms": context_bundle.latest_ctx_time_ms,
                    "queried_views": context_bundle.queried_views,
                    "primary_row_count": len(context_bundle.primary_rows),
                    "wallet_flow_row_count": len(context_bundle.wallet_flow_rows),
                    "wallet_activity_row_count": len(context_bundle.wallet_activity_rows),
                    "recent_fill_row_count": len(context_bundle.recent_fill_rows),
                    "metadata_row_count": len(context_bundle.metadata_rows),
                    "balance_row_count": len(context_bundle.balance_rows),
                },
            )

            rendered = ""
            async for delta in stream_answer(request.message, context_bundle, token):
                rendered += delta
                yield _sse("token", {"text": delta})

            yield _sse(
                "final",
                {
                    "text": rendered,
                    "latest_ctx_time_ms": context_bundle.latest_ctx_time_ms,
                    "question_mode": context_bundle.question_mode,
                    "queried_views": context_bundle.queried_views,
                },
            )
            yield _sse("done", {"status": "completed"})
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/", include_in_schema=False)
async def frontend_index():
    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return JSONResponse({"detail": "Frontend build not found"}, status_code=404)


@app.get("/{full_path:path}", include_in_schema=False)
async def frontend_routes(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    requested_file = FRONTEND_DIST_DIR / full_path
    if requested_file.is_file():
        return FileResponse(requested_file)

    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)

    return JSONResponse({"detail": "Frontend build not found"}, status_code=404)
