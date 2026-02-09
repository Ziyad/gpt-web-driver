from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any


def _now_epoch() -> int:
    return int(time.time())


def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _coerce_content(c: Any) -> str:
    # OpenAI-style content can be a string or an array of parts; keep it simple.
    if c is None:
        return ""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for p in c:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text") or ""))
        return "".join(parts)
    return str(c)


def _prompt_from_messages(messages: list[dict[str, Any]]) -> str:
    # Minimal: send the last user message to the UI.
    for m in reversed(messages or []):
        if str(m.get("role") or "").strip().lower() == "user":
            return _coerce_content(m.get("content"))
    # Fallback: concatenate all contents.
    return "\n".join(_coerce_content(m.get("content")) for m in (messages or []))


def create_app(*, session, default_model: str = "gpt-web-driver") -> Any:
    """
    Create a FastAPI app exposing POST /v1/chat/completions.

    `fastapi`/`uvicorn` are optional dependencies; this function imports them lazily.
    """
    try:
        from fastapi import FastAPI, HTTPException  # type: ignore
    except ModuleNotFoundError as e:  # pragma: no cover
        raise RuntimeError("fastapi is required for the API server. Install with: pip install 'gpt-web-driver[api]'") from e

    @asynccontextmanager
    async def lifespan(app: Any):
        await session.start()
        try:
            yield
        finally:
            await session.close()

    app = FastAPI(lifespan=lifespan)
    app.state.session = session
    app.state.default_model = str(default_model)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "paused": bool(session.paused_reason), "paused_reason": session.paused_reason}

    @app.post("/v1/system/resume")
    async def system_resume() -> dict[str, Any]:
        session.resume()
        return {"ok": True}

    @app.post("/v1/chat/completions")
    async def chat_completions(payload: dict[str, Any]) -> dict[str, Any]:
        if session.paused_reason:
            raise HTTPException(status_code=503, detail={"error": "paused", "reason": session.paused_reason})

        model = str(payload.get("model") or app.state.default_model)
        if _coerce_bool(payload.get("stream")):
            raise HTTPException(status_code=400, detail={"error": "streaming_not_supported"})

        messages = payload.get("messages") or []
        if not isinstance(messages, list):
            raise HTTPException(status_code=400, detail="'messages' must be a list")

        prompt = _prompt_from_messages([m for m in messages if isinstance(m, dict)])
        if not str(prompt).strip():
            raise HTTPException(status_code=400, detail="empty prompt")

        try:
            text = await session.chat_completion(prompt)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

        created = _now_epoch()
        rid = f"chatcmpl_{uuid.uuid4().hex[:24]}"
        return {
            "id": rid,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                # Token counts are unknown without a tokenizer. Some clients expect integers here,
                # so return 0s rather than nulls.
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    return app


def run_uvicorn(app: Any, *, host: str, port: int, log_level: str = "info") -> None:
    try:
        import uvicorn  # type: ignore
    except ModuleNotFoundError as e:  # pragma: no cover
        raise RuntimeError("uvicorn is required for the API server. Install with: pip install 'gpt-web-driver[api]'") from e

    uvicorn.run(app, host=str(host), port=int(port), log_level=str(log_level))
