"""Tooling helpers for IDs and time and tools list placeholder."""
from __future__ import annotations

import time
import uuid
from typing import List, Dict


def now_ts() -> float:
    return time.time()


def new_id() -> str:
    return str(uuid.uuid4())


def get_tools() -> List[Dict]:
    """Return list of available tools for LLM calls (placeholder: empty)."""
    return []
