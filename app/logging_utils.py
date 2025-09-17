"""Structured logging utilities with human-friendly console output.

By default, prints concise human-readable lines. Set env LOCALAPI_LOG_JSON=1 to also emit JSON lines.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, Iterable

# Controls
HUMAN_MIRROR = True  # always show human-readable line
JSON_ENABLED = os.getenv("LOCALAPI_LOG_JSON", "0").strip().lower() in {"1", "true", "yes", "on"}


def _ts() -> float:
    return time.time()


def _base(event: str, level: str) -> Dict[str, Any]:
    return {
        "ts": _ts(),
        "level": level,
        "event": event,
        "pid": os.getpid(),
    }


def _kv(rec: Dict[str, Any], keys: list[str]) -> str:
    parts = []
    for k in keys:
        if k in rec and rec[k] is not None:
            parts.append(f"{k}={rec[k]}")
    return " ".join(parts)


def _maybe_pretty_echo(rec: Dict[str, Any]) -> None:
    ev = str(rec.get("event") or rec.get("phase") or "").strip()
    lvl = str(rec.get("level", "INFO")).upper()
    out = ""
    if ev in {"llm_online", "llm_offline"}:
        out = f"[LLM] {ev.replace('llm_', '')}: {rec.get('base_url', '')}"
    elif ev == "startup":
        out = f"[APP] started — model: {rec.get('chat_model')} — base: {rec.get('base_url')}"
    elif ev == "shutdown":
        out = "[APP] stopped"
    elif ev == "llm_probe_error":
        out = f"[LLM] probe error { _kv(rec, ['attempt','latency_ms']) } base={rec.get('base_url','')} err={rec.get('error','')}".strip()
    elif ev == "llm_unavailable":
        out = f"[LLM] unavailable: {rec.get('base_url','')}"
    elif ev == "context_ok":
        out = f"[CTX] budget ok: used={rec.get('tokens')}/{rec.get('budget')}"
    elif ev == "context_trim":
        out = f"[CTX] trimmed: used={rec.get('tokens')}/{rec.get('budget')} k={rec.get('k_final')}"
    elif ev == "summary":
        out = f"[SUM] ok { _kv(rec, ['latency']) }ms"
    elif ev == "summary_error":
        out = f"[SUM] error { _kv(rec, ['latency']) }ms: {rec.get('error','')}"
    elif ev == "fold_history_ok":
        out = f"[SUM] stored length={rec.get('length')}"
    elif ev == "memory_store":
        out = f"[MEM] {rec.get('key')}={rec.get('value')}"
    elif ev == "final":
        out = f"[RESP] model={rec.get('model','?')} thread={str(rec.get('thread_id',''))[:8]}… resp={str(rec.get('response_id',''))[:8]}… {rec.get('latency',0)} ms"
    else:
        # Generic fallback for any other JSON events
        extras = {k: v for k, v in rec.items() if k not in {"ts", "level", "event", "pid"}}
        tail = " ".join(f"{k}={v}" for k, v in extras.items())
        out = f"[LOG] {lvl} {ev} {tail}".rstrip()
    sys.stdout.write(out + "\n")
    sys.stdout.flush()


def _write(rec: Dict[str, Any]) -> None:
    if JSON_ENABLED:
        # emit JSON only when enabled
        sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    if HUMAN_MIRROR:
        _maybe_pretty_echo(rec)


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
