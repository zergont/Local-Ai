"""FastAPI app for Local Responses API.

Endpoints:
- POST /responses
- GET /responses/{response_id}
- GET /threads/{thread_id}/messages?limit=50
- GET /threads/{thread_id}/summary
- POST /threads/{thread_id}/summarize
- GET /file/{id}
- /config, UI, upload
- /debug/context/{thread_id}
- POST /config/think-mode
"""
from __future__ import annotations

import uuid as _uuid
import orjson
from typing import Any
from pathlib import Path
import asyncio
import time

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import ORJSONResponse, FileResponse

from .config import get_settings
from .db import Database
from .llm_client import LLMClient
from .logging_utils import log_error, log_info, print_banner
from .models import ResponsePayload, ResponseRequest
from .service import LocalResponsesService
from . import summarizer
from .ui import router as ui_router
from .ws import router as ws_router


class ORJSONResponse2(ORJSONResponse):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:  # type: ignore[override]
        return orjson.dumps(content)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Local Responses API", default_response_class=ORJSONResponse2)

    app.include_router(ui_router)
    app.include_router(ws_router)

    db = Database(settings.database_path)
    llm = LLMClient()
    service = LocalResponsesService(db, llm)

    # expose service to ws router via app.state
    app.state.service = service
    app.state.llm_online = False

    @app.on_event("startup")
    async def _startup() -> None:
        await db.connect()
        # Apply schema.sql so required tables exist
        try:
            schema_path = Path(__file__).resolve().parent.parent / "schema.sql"
            schema_sql = schema_path.read_text(encoding="utf-8")
            await db.executescript(schema_sql)
            log_info(
                "startup",
                message="Local AI service started",
                db_path=db.path,
                llm_url=settings.llm_base_url,
                schema_path=str(schema_path),
                chat_model=settings.llm_model,
                vision_model=settings.vision_model,
                max_upload_mb=settings.max_upload_mb,
                allowed_extensions=settings.allowed_exts,
                base_url=settings.app_base_url,
            )
            print_banner(
                "Local AI — сервер запущен",
                [
                    f"База данных: {db.path}",
                    f"LLM: {settings.llm_model}",
                    f"Vision: {settings.vision_model}",
                    f"LLM API: {settings.llm_base_url}",
                    f"Схема: {schema_path}",
                    f"BASE URL: {settings.app_base_url}",
                ],
            )
        except Exception as e:  # noqa: BLE001
            log_error("schema_error", message="Failed to apply schema.sql", error=str(e))
            raise
        # Probe LLM connectivity (GET /models) with retries
        base = settings.llm_base_url.rstrip("/")
        url = f"{base}/models"
        last_err: Exception | None = None
        for attempt in range(1, 4):
            t0 = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()
                n_models = len(data.get("data", [])) if isinstance(data, dict) else None
                dt_ms = int((time.perf_counter() - t0) * 1000)
                log_info("llm_probe_success", base_url=base, latency_ms=dt_ms, models_count=n_models, message="LLM connection established")
                app.state.llm_online = True
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                dt_ms = int((time.perf_counter() - t0) * 1000)
                log_error("llm_probe_error", base_url=base, latency_ms=dt_ms, attempt=attempt, error=f"{type(e).__name__}: {str(e)}")
                await asyncio.sleep(0.25 * (2 ** (attempt - 1)))
        if not app.state.llm_online:
            log_error("llm_unavailable", base_url=base, error=str(last_err) if last_err else "unknown")
            print_banner(
                "Внимание: LLM недоступен",
                [
                    f"LLM API: {settings.llm_base_url}",
                    "Проверьте адрес/порт, доступность LM Studio и значения переменных окружения.",
                ],
            )
        # Init summarizer module
        summarizer.init(db, llm)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await llm.aclose()
        await db.close()
        log_info("shutdown", message="Service stopped")
        print_banner("Local AI — сервер остановлен", [])

    @app.get("/config")
    async def get_config() -> dict[str, Any]:
        s = get_settings()
        return {
            "LM_BASE_URL": s.llm_base_url,
            "MODEL_CONTROLLER": s.llm_model,
            "K": s.max_context_messages,
            "SUMMARY_TRIGGER": s.summarize_after_messages,
            "MAX_UPLOAD_MB": s.max_upload_mb,
            "ALLOWED_EXTS": s.allowed_exts,
            "LLM_ONLINE": bool(app.state.llm_online),
            "CONTEXT_WINDOW_TOKENS": s.context_window_tokens,
            "CONTEXT_PROMPT_BUDGET_RATIO": s.context_prompt_budget_ratio,
            "CONTEXT_HYSTERESIS_TOKENS": s.context_hysteresis_tokens,
            "APP_BASE_URL": s.app_base_url,
        }

    @app.post("/responses", response_model=ResponsePayload)
    async def post_responses(req: ResponseRequest) -> ResponsePayload:
        rid = str(_uuid.uuid4())
        resp_id: str | None = None
        try:
            _user_msg_id, resp_id, output_text, usage, actual_thread_id = await service.respond(
                thread_id=req.thread_id,
                previous_response_id=req.previous_response_id,
                user_text=req.input_text,
                store=req.store,
            )
            return ResponsePayload(response_id=resp_id, thread_id=actual_thread_id, output_text=output_text, status="completed", usage=usage)
        except Exception as e:  # noqa: BLE001
            if resp_id:
                log_error("post_responses_error", error=str(e), trace_id=rid, response_id=resp_id)
            else:
                log_error("post_responses_error", error=str(e), trace_id=rid)
            detail: dict[str, Any] = {"error": "internal error", "trace_id": rid}
            if resp_id:
                detail["response_id"] = resp_id
            raise HTTPException(status_code=500, detail=detail)

    @app.get("/responses/{response_id}")
    async def get_response(response_id: str) -> Any:
        detail = await db.get_response_detail(response_id)
        if not detail:
            raise HTTPException(status_code=404, detail="not found")
        return detail

    @app.get("/threads/{thread_id}/messages")
    async def get_thread_messages(thread_id: str, limit: int = Query(50, ge=1, le=500)) -> Any:
        rows = await db.get_thread_messages(thread_id, limit)
        return list(reversed(rows))

    @app.get("/threads/{thread_id}/summary")
    async def get_thread_summary(thread_id: str) -> Any:
        summary = await db.get_summary(thread_id)
        return {"thread_id": thread_id, "summary": summary or ""}

    @app.post("/threads/{thread_id}/summarize")
    async def post_thread_summarize(thread_id: str) -> Any:
        try:
            text = await summarizer.summarize(thread_id)
            return {"thread_id": thread_id, "summary": text}
        except Exception as e:  # noqa: BLE001
            log_error("summarize_error", thread_id=thread_id, error=str(e))
            raise HTTPException(status_code=500, detail="internal error")

    @app.get("/file/{file_id}")
    async def get_file(file_id: str) -> FileResponse:
        base = Path("files").resolve()
        path = (base / file_id).resolve()
        if not path.is_file() or base not in path.parents:
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(path)

    @app.get("/debug/context/{thread_id}")
    async def get_debug_context(thread_id: str) -> Any:
        try:
            return await service.debug_context(thread_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e))

    return app


app = create_app()
