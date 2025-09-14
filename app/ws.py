from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Any
import json
import uuid

from .service import LocalResponsesService

router = APIRouter()


@router.websocket("/ws/respond")
async def ws_respond(ws: WebSocket) -> None:
    await ws.accept()
    try:
        init = await ws.receive_text()
        req = json.loads(init)
        service: LocalResponsesService = ws.app.state.service  # injected on startup
        async for frame in service.respond_stream(
            user_text=str(req.get("input_text", "")),
            thread_id=req.get("thread_id"),
            previous_response_id=req.get("previous_response_id"),
            store=bool(req.get("store", True)),
        ):
            await ws.send_text(json.dumps(frame, ensure_ascii=False))
    except WebSocketDisconnect:
        return
    except Exception:
        trace_id = str(uuid.uuid4())
        await ws.send_text(json.dumps({"type": "error", "message": "internal error", "trace_id": trace_id}, ensure_ascii=False))
    finally:
        await ws.close()
