"""HTTP client for OpenAI-compatible chat completions via LM Studio.

We use the /chat/completions endpoint with messages array and optional streaming.
Network retries were removed to let caller decide logging and timing.
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx

from .config import get_settings

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

    async def chat_raw(self, messages: List[Dict[str, Any]], *, tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        url = f"{self._base}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": False,
        }
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

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
        url = f"{self._base}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": True,
        }
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
