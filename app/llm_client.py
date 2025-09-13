"""HTTP client for OpenAI-compatible chat completions via LM Studio.

We use the /chat/completions endpoint with messages array.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import httpx

from .config import get_settings


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

    async def chat(self, messages: List[Dict[str, str]]) -> Tuple[str, Dict[str, int]]:
        url = f"{self._base}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))
        return text, {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
