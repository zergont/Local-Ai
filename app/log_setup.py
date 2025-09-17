"""Uvicorn logging configuration helpers.

- Hides noisy /health access logs
- Suppresses websocket connect/disconnect chatter
- Formats our JSON logs (already structured) and uvicorn logs nicely
"""
from __future__ import annotations

import logging
import os
import re
from logging.config import dictConfig
from typing import Any, Dict


class HealthAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            msg = str(getattr(record, "msg", ""))
        return "/health" not in msg


class RegexExcludeFilter(logging.Filter):
    """Exclude records whose message matches any of provided regexes."""

    def __init__(self, patterns: list[str] | None = None) -> None:
        super().__init__()
        self._res = [re.compile(p) for p in (patterns or [])]

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            msg = str(getattr(record, "msg", ""))
        for r in self._res:
            if r.search(msg):
                return False
        return True


def build_uvicorn_log_config() -> Dict[str, Any]:
    # Based on Uvicorn default, with filters for /health and websocket noise
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "health-filter": {"()": HealthAccessFilter},
            "ws-noise-filter": {
                "()": RegexExcludeFilter,
                "patterns": [
                    r"WebSocket .+ \[accepted\]",
                    r"connection (open|closed)",
                ],
            },
        },
        "formatters": {
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": "%(levelprefix)s %(client_addr)s - \"%(request_line)s\" %(status_code)s",
            },
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "filters": ["ws-noise-filter"],
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "filters": ["health-filter"],
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            # General uvicorn logs (startup/shutdown, errors)
            "uvicorn": {"handlers": ["default"], "level": "INFO"},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            # Access logs (requests)
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
            # Protocol noise (websockets/http), push to WARNING to suppress info chatter
            "uvicorn.asgi": {"level": "WARNING"},
            "uvicorn.protocols.http.h11_impl": {"level": "WARNING"},
            "uvicorn.protocols.websockets.websockets_impl": {"level": "WARNING"},
        },
    }


def apply_default_uvicorn_logging() -> None:
    """Apply our quiet uvicorn logging config unless verbose env is set.

    Set LOCALAPI_UVICORN_VERBOSE=1 to disable and keep uvicorn defaults.
    """
    verbose = os.getenv("LOCALAPI_UVICORN_VERBOSE", "").strip().lower() in {"1", "true", "yes", "on"}
    if verbose:
        return
    try:
        dictConfig(build_uvicorn_log_config())
    except Exception:
        # Don't fail startup because of logging
        pass
