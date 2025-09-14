"""HTTP client for OpenAI-compatible chat completions via LM Studio.

We use the /chat/completions endpoint with messages array and optional tool-calling.
All network calls are retried with exponential backoff and jitter. Supports streaming.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx

from .config import get_settings
from .logging_utils import log_error, log_info

SSE_PREFIX = b"data: "


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

    async def chat_stream(self, messages: List[Dict[str, Any]], *, tools: Optional[List[Dict[str, Any]]] = None) -> AsyncIterator[str]:
        """Yield streamed content deltas as they arrive."""
        url = f"{self._base}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        last_err: Optional[Exception] = None
        for attempt in range(1, 4):
            t0 = time.perf_counter()
            try:
                async with self._client.stream("POST", url, json=payload) as r:
                    r.raise_for_status()
                    async for chunk in r.aiter_raw():
                        for line in chunk.splitlines():
                            line = line.strip()
                            if not line or not line.startswith(SSE_PREFIX):
                                continue
                            data = line[len(SSE_PREFIX):].decode("utf-8", errors="ignore")
                            if data == "[DONE]":
                                return
                            try:
                                obj = json.loads(data)
                            except Exception:
                                continue
                            delta = ""
                            try:
                                delta = obj["choices"][0]["delta"].get("content") or ""
                            except Exception:
                                try:
                                    delta = obj["choices"][0]["message"].get("content") or ""
                                except Exception:
                                    delta = ""
                            if delta:
                                yield delta
                dt_ms = int((time.perf_counter() - t0) * 1000)
                log_info("llm_stream_end", model=self._model, latency_ms=dt_ms)
                return
            except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as e:
                last_err = e
                dt_ms = int((time.perf_counter() - t0) * 1000)
                log_error("llm_stream_error", model=self._model, latency_ms=dt_ms, error=str(e))
                if attempt >= 3:
                    break
                base = 0.25 * (2 ** (attempt - 1))
                jitter = random.uniform(0, 0.15)
                await asyncio.sleep(base + jitter)
        assert last_err is not None
        raise last_err
