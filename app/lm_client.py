"""LM client: single non-stream chat call with retries/backoff.

Exports:
- async chat_once(messages: list[dict], model: str, tools: list[dict] | None) -> dict
"""
from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, List, Optional

import httpx

from .settings import get_settings

_DEFAULT_TIMEOUT = 30.0  # seconds
_MAX_RETRIES = 3


async def _sleep_backoff(attempt: int) -> None:
    # Exponential backoff with jitter: base 0.5s * 2^(attempt-1) + [0..250ms]
    base = 0.5 * (2 ** max(0, attempt - 1))
    jitter = random.uniform(0.0, 0.25)
    await asyncio.sleep(base + jitter)


async def chat_once(messages: List[Dict[str, Any]], model: str, tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Call LM Studio-compatible /chat/completions once with retry/backoff.

    Args:
        messages: OpenAI-style messages list [{role, content, ...}]
        model: model/controller identifier
        tools: optional OpenAI tools array

    Returns:
        Parsed JSON dict from the completion API response.
    """
    settings = get_settings()
    url = settings.LM_BASE_URL.rstrip("/") + "/chat/completions"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools

    last_error: Optional[Exception] = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers={"content-type": "application/json"})
                resp.raise_for_status()
                return resp.json()
        except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as e:
            last_error = e
            if attempt >= _MAX_RETRIES:
                break
            await _sleep_backoff(attempt)
    # If we are here, raise last error
    assert last_error is not None
    raise last_error
