"""JSON logging utilities based on stdlib logging.

Provides setup_logging() and get_logger(name).
"""
from __future__ import annotations

import json
import logging as _logging
import os
import sys
from typing import Any, Dict


class JsonFormatter(_logging.Formatter):
    def format(self, record: _logging.LogRecord) -> str:  # type: ignore[override]
        payload: Dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "pid": os.getpid(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str | int = "INFO") -> None:
    level_value = _logging.getLevelName(level) if isinstance(level, str) else level
    root = _logging.getLogger()
    root.setLevel(level_value)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = _logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


def get_logger(name: str) -> _logging.Logger:
    return _logging.getLogger(name)
