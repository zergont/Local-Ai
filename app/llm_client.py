"""HTTP client for OpenAI-compatible chat completions via LM Studio.

We use the /chat/completions endpoint with messages array and optional tool-calling.
All network calls are retried with exponential backoff and jitter.
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import get_settings
from .logging_utils import log_error, log_info


class LLMClient:
    def __init__(self) -> None:
        s = get_settings()
        self._base = s.llm_base_url.rstrip("/")
        self._model = s.llm_model
        self._timeout = s.request_timeout
        self._temperature = s.temperature
        self._max_tokens = s.max_tokens
        self._client = httpx.AsyncClient(timeout=self._timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post_json_with_retries(self, url: str, payload: Dict[str, Any], *, max_retries: int = 3) -> Dict[str, Any]:
        last_err: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            t0 = time.perf_counter()
            try:
                resp = await self._client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                dt_ms = int((time.perf_counter() - t0) * 1000)
                log_info("llm_call", model=self._model, latency_ms=dt_ms)
                return data
            except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as e:
                last_err = e
                dt_ms = int((time.perf_counter() - t0) * 1000)
                log_error("llm_call_error", model=self._model, latency_ms=dt_ms, error=str(e))
                if attempt >= max_retries:
                    break
                # backoff with jitter
                base = 0.25 * (2 ** (attempt - 1))
                jitter = random.uniform(0, 0.15)
                await asyncio.sleep(base + jitter)
        assert last_err is not None
        raise last_err

    async def chat_raw(self, messages: List[Dict[str, Any]], *, tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        url = f"{self._base}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return await self._post_json_with_retries(url, payload)

    async def chat(self, messages: List[Dict[str, Any]], *, tools: Optional[List[Dict[str, Any]]] = None) -> Tuple[str, Dict[str, int]]:
        data = await self.chat_raw(messages, tools=tools)
        message = data.get("choices", [{}])[0].get("message", {})
        text = message.get("content") or ""
        usage = data.get("usage", {}) or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))
        return text, {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
