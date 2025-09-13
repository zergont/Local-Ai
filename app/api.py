"""FastAPI app for Local Responses API.

Endpoints:
- POST /responses
- GET /responses/{response_id}
- GET /threads/{thread_id}/messages?limit=50
- GET /threads/{thread_id}/summary

Run:
    uvicorn Local_Ai:app --host 0.0.0.0 --port 8080

Sanity tests:
    curl -s -X POST http://localhost:8080/responses \
      -H 'content-type: application/json' \
      -d '{"input_text":"Hello!"}' | jq .
"""
from __future__ import annotations

import orjson
from typing import Any, List
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import ORJSONResponse

from .config import get_settings
from .db import Database
from .llm_client import LLMClient
from .logging_utils import log_error, log_info
from .models import ResponsePayload, ResponseRequest
from .service import LocalResponsesService


class ORJSONResponse2(ORJSONResponse):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Local Responses API", default_response_class=ORJSONResponse2)

    db = Database(settings.database_path)
    llm = LLMClient()
    service = LocalResponsesService(db, llm)

    @app.on_event("startup")
    async def _startup() -> None:
        await db.connect()
        # Apply schema.sql so required tables exist
        try:
            schema_path = Path(__file__).resolve().parent.parent / "schema.sql"
            schema_sql = schema_path.read_text(encoding="utf-8")
            await db.executescript(schema_sql)
            log_info("startup", db=db.path, llm_base=settings.llm_base_url, schema=str(schema_path))
        except Exception as e:  # noqa: BLE001
            log_error("startup_schema_error", error=str(e))
            raise

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await llm.aclose()
        await db.close()
        log_info("shutdown")

    @app.post("/responses", response_model=ResponsePayload)
    async def post_responses(req: ResponseRequest) -> ResponsePayload:
        try:
            _user_msg_id, resp_id, output_text, usage, actual_thread_id = await service.respond(
                thread_id=req.thread_id,
                previous_response_id=req.previous_response_id,
                user_text=req.input_text,
                store=req.store,
            )
            return ResponsePayload(
                response_id=resp_id,
                thread_id=actual_thread_id,
                output_text=output_text,
                status="completed",
                usage=usage,
            )
        except Exception as e:  # noqa: BLE001
            log_error("error_post_responses", error=str(e))
            raise HTTPException(status_code=500, detail="internal error")

    @app.get("/responses/{response_id}")
    async def get_response(response_id: str) -> Any:
        detail = await db.get_response_detail(response_id)
        if not detail:
            raise HTTPException(status_code=404, detail="not found")
        return detail

    @app.get("/threads/{thread_id}/messages")
    async def get_thread_messages(thread_id: str, limit: int = Query(50, ge=1, le=500)) -> Any:
        rows = await db.get_thread_messages(thread_id, limit)
        # return messages in chronological order
        return list(reversed(rows))

    @app.get("/threads/{thread_id}/summary")
    async def get_thread_summary(thread_id: str) -> Any:
        summary = await db.get_summary(thread_id)
        return {"thread_id": thread_id, "summary": summary or ""}

    return app


app = create_app()
