"""Structured JSON logging utilities.

All logs go to stdout as JSON lines. Designed for minimal overhead.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, Iterable


def _ts() -> float:
    return time.time()


def _base(event: str, level: str) -> Dict[str, Any]:
    return {
        "ts": _ts(),
        "level": level,
        "event": event,
        "pid": os.getpid(),
    }


def _write(rec: Dict[str, Any]) -> None:
    # ensure_ascii=False — чтобы кириллица и прочие символы не экранировались \uXXXX
    sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log_info(event: str, **kv: Any) -> None:
    rec = _base(event, "INFO")
    rec.update(kv)
    _write(rec)


def log_error(event: str, **kv: Any) -> None:
    rec = _base(event, "ERROR")
    rec.update(kv)
    _write(rec)


def log_warning(event: str, **kv: Any) -> None:
    rec = _base(event, "WARN")
    rec.update(kv)
    _write(rec)


def print_banner(title: str, lines: Iterable[str]) -> None:
    """Print a simple pretty banner to stdout (human-friendly)."""
    lines = list(lines)
    width = max(len(title), *(len(s) for s in lines), 40) + 2
    bar = "=" * width
    sys.stdout.write("\n" + bar + "\n")
    sys.stdout.write(title + "\n")
    sys.stdout.write(bar + "\n")
    for s in lines:
        sys.stdout.write(s + "\n")
    sys.stdout.write(bar + "\n\n")
    sys.stdout.flush()
