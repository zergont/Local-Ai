"""Structured JSON logging utilities.

All logs go to stdout as JSON lines. Designed for minimal overhead.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict


def _ts() -> float:
    return time.time()


def _base(event: str, level: str) -> Dict[str, Any]:
    return {
        "ts": _ts(),
        "level": level,
        "event": event,
        "pid": os.getpid(),
    }


def log_info(event: str, **kv: Any) -> None:
    rec = _base(event, "INFO")
    rec.update(kv)
    sys.stdout.write(json.dumps(rec) + "\n")
    sys.stdout.flush()


def log_error(event: str, **kv: Any) -> None:
    rec = _base(event, "ERROR")
    rec.update(kv)
    sys.stdout.write(json.dumps(rec) + "\n")
    sys.stdout.flush()


def log_warning(event: str, **kv: Any) -> None:
    rec = _base(event, "WARN")
    rec.update(kv)
    sys.stdout.write(json.dumps(rec) + "\n")
    sys.stdout.flush()
