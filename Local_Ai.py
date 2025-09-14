"""Entry point to run the FastAPI app for Local Responses API.

Run (recommended):
  uvicorn Local_Ai:app --host 0.0.0.0 --port 8080

Or run directly (will start uvicorn):
  python Local_Ai.py

Env sample (.env):
  LOCALAPI_DATABASE_PATH=data/local_api.db
  LOCALAPI_LLM_BASE_URL=http://192.168.0.111:1234/v1
  LOCALAPI_LLM_MODEL=TheBloke/Mistral-7B

Curl sanity test:
  curl -s -X POST http://localhost:8080/responses \
    -H 'content-type: application/json' \
    -d '{"thread_id":"t1","input_text":"Hello!"}' | jq .
"""
from __future__ import annotations

from app.api import app
from app.ui import router as ui_router
from app.ws import router as ws_router

# include UI and WS routers for local chat interface
app.include_router(ui_router)
app.include_router(ws_router)

__all__ = ["app"]


if __name__ == "__main__":
    # Allow running as: python Local_Ai.py
    import uvicorn
    try:
        from app.config import get_settings

        s = get_settings()
        host = getattr(s, "api_host", "0.0.0.0")
        port = int(getattr(s, "api_port", 8080))
    except Exception:
        host = "0.0.0.0"
        port = 8080
    uvicorn.run("Local_Ai:app", host=host, port=port)
