"""FastAPI application bootstrap for Local Responses API skeleton.

Endpoints:
- GET /health -> {"status": "ok"}
- GET /config -> runtime configuration (non-secret)

Startup:
- initialize JSON logging
- connect SQLite and apply schema.sql

Run:
  uvicorn app.main:app --reload

Sanity:
  curl -s http://localhost:8000/health
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI

from .settings import get_settings
from .logging import setup_logging, get_logger
from .db import Database
from .lm_client import chat_once
from .tooling import get_tools


app = FastAPI(title="Local Responses API (skeleton)")


# Simple shared state
class State:
    db: Database | None = None


@app.on_event("startup")
async def on_startup() -> None:
    setup_logging()
    log = get_logger(__name__)

    settings = get_settings()
    log.info("starting")

    # DB path for skeleton
    db_path = Path("data/app.db")
    db = Database(db_path)
    await db.connect()

    # Apply schema
    schema_path = Path(__file__).resolve().parent.parent / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")
    await db.executescript(schema_sql)

    State.db = db
    log.info("startup_complete")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    log = get_logger(__name__)
    if State.db is not None:
        await State.db.close()
        State.db = None
    log.info("shutdown_complete")


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
async def config() -> Dict[str, Any]:
    s = get_settings()
    return {
        "LM_BASE_URL": s.LM_BASE_URL,
        "MODEL_CONTROLLER": s.MODEL_CONTROLLER,
        "K": s.K,
        "SUMMARY_TRIGGER": s.SUMMARY_TRIGGER,
    }


async def build_context(thread_id: str, user_text: str) -> List[Dict[str, str]]:
    """Build OpenAI-style messages array from stored thread state and current user text.

    - If summary exists, prepend as system message
    - Append last K thread messages
    - Append current user message at the end
    """
    assert State.db is not None, "Database is not initialized"
    s = get_settings()

    messages: List[Dict[str, str]] = []

    # summary
    summary = await State.db.get_summary(thread_id)
    if summary:
        messages.append({"role": "system", "content": summary})

    # last K messages (reverse to chronological order)
    recent = await State.db.get_thread_messages(thread_id, s.K)
    for m in reversed(recent):
        messages.append({"role": str(m["role"]), "content": str(m["content"])})

    # current user message
    messages.append({"role": "user", "content": user_text})

    return messages
