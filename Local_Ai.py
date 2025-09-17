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

# Apply our uvicorn logging automatically unless overridden
try:
    from app.log_setup import apply_default_uvicorn_logging
    apply_default_uvicorn_logging()
except Exception:
    pass

__all__ = ["app"]


if __name__ == "__main__":
    # Allow running as: python Local_Ai.py
    import uvicorn
    import logging
    try:
        from app.config import get_settings
        from app.log_setup import build_uvicorn_log_config  # type: ignore
    except Exception:
        get_settings = None  # type: ignore
        build_uvicorn_log_config = None  # type: ignore

    # Optional: filter /health from uvicorn access logs when running via this entrypoint
    class _HealthFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
            try:
                msg = record.getMessage()
            except Exception:  # noqa: BLE001
                msg = str(getattr(record, "msg", ""))
            return "/health" not in msg

    logging.getLogger("uvicorn.access").addFilter(_HealthFilter())

    try:
        s = get_settings() if get_settings else None
        host = getattr(s, "api_host", "0.0.0.0") if s else "0.0.0.0"
        port = int(getattr(s, "api_port", 8080)) if s else 8080
    except Exception:
        host = "0.0.0.0"
        port = 8080

    log_config = build_uvicorn_log_config() if build_uvicorn_log_config else None
    uvicorn.run("Local_Ai:app", host=host, port=port, log_config=log_config)
