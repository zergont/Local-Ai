"""Core service orchestration for Local Responses API."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Tuple

from .config import get_settings
from .db import Database
from .llm_client import LLMClient
from .logging_utils import log_info, log_error
from .tooling import list_tools, tools_openai_format, maybe_call_one_tool


# Keep system prompt minimal; do not block chain-of-thought explicitly.
SYSTEM_PROMPT = "You are a helpful assistant. Be concise."


class LocalResponsesService:
    def __init__(self, db: Database, llm: LLMClient) -> None:
        self._db = db
        self._llm = llm
        self._s = get_settings()
        self._tools = {t.name: t for t in list_tools()}

    async def build_context(self, thread_id: str) -> List[Dict[str, str]]:
        chat: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        summary = await self._db.get_summary(thread_id)
        if summary:
            chat.append({"role": "system", "content": f"Thread summary: {summary}"})
        recent = await self._db.get_thread_messages(thread_id, self._s.max_context_messages)
        for m in reversed(recent):
            chat.append({"role": str(m["role"]), "content": str(m["content"])})
        return chat

    async def _maybe_tool_call(self, messages: List[Dict[str, Any]], model_text: str, raw_resp: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            tool_calls = raw_resp.get("choices", [{}])[0].get("message", {}).get("tool_calls")
        except Exception:
            tool_calls = None
        if not tool_calls:
            return messages
        call = tool_calls[0]
        fn = call.get("function", {})
        name = str(fn.get("name", ""))
        arguments = fn.get("arguments")
        if isinstance(arguments, str):
            try:
                args_obj = json.loads(arguments)
            except Exception:
                args_obj = {}
        elif isinstance(arguments, dict):
            args_obj = arguments
        else:
            args_obj = {}
        tool = self._tools.get(name)
        if not tool:
            log_error("tool_not_found", tool=name)
            return messages
        t0 = time.perf_counter()
        try:
            result = await tool.invoke(**args_obj)
            ok = True
        except Exception as e:  # noqa: BLE001
            result = {"error": str(e)}
            ok = False
        dt_ms = int((time.perf_counter() - t0) * 1000)
        log_info("tool_call", tool=name, latency_ms=dt_ms, status="ok" if ok else "error")
        messages.append({"role": "tool", "name": name, "content": json.dumps(result, ensure_ascii=False)})
        return messages

    async def respond(
        self,
        *,
        thread_id: str | None,
        previous_response_id: str | None,
        user_text: str,
        store: bool,
    ) -> Tuple[str, str, str, Dict[str, int], str]:
        actual_thread_id = await self._db.resolve_thread(previous_response_id, thread_id)
        if store:
            user_msg_id = await self._db.insert_message(actual_thread_id, "user", user_text)
        else:
            user_msg_id = str(uuid.uuid4())
        chat = await self.build_context(actual_thread_id)
        chat.append({"role": "user", "content": user_text})
        tools = tools_openai_format()
        t0 = time.perf_counter()
        text, usage = await self._llm.chat(chat, tools=tools)
        raw = await self._llm.chat_raw(chat, tools=tools)
        dt_ms = int((time.perf_counter() - t0) * 1000)
        log_info("llm_response", thread_id=actual_thread_id, latency_ms=dt_ms)
        chat = await self._maybe_tool_call(chat + [{"role": "assistant", "content": text}], text, raw)
        if chat and chat[-1].get("role") == "tool":
            t1 = time.perf_counter()
            text2, usage2 = await self._llm.chat(chat, tools=tools)
            dt_ms2 = int((time.perf_counter() - t1) * 1000)
            log_info("llm_response", thread_id=actual_thread_id, latency_ms=dt_ms2)
            text = text2
            usage = {
                "prompt_tokens": int(usage.get("prompt_tokens", 0)) + int(usage2.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)) + int(usage2.get("completion_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)) + int(usage2.get("total_tokens", 0)),
            }
        # Store and return raw assistant text (UI collapses reasoning safely)
        if store:
            assistant_msg_id = await self._db.insert_message(actual_thread_id, "assistant", text)
        else:
            assistant_msg_id = str(uuid.uuid4())
        resp_id = await self._db.insert_response(
            actual_thread_id,
            input_message_id=user_msg_id,
            status="completed",
            usage=usage,
            error=None,
        )
        await self._db.update_response_output(resp_id, assistant_msg_id, status="completed")
        try:
            row = await self._db.fetch_one("SELECT COUNT(1) AS n FROM messages WHERE thread_id=?", [actual_thread_id])
            count = int(row["n"]) if row else 0
            if count >= self._s.summarize_after_messages and store:
                from . import summarizer
                await summarizer.summarize(actual_thread_id)
        except Exception:
            pass
        return user_msg_id, resp_id, text, usage, actual_thread_id

    async def respond_stream(self, *, user_text: str, thread_id: str | None, previous_response_id: str | None, store: bool) -> AsyncIterator[Dict[str, Any]]:
        actual_thread_id = await self._db.resolve_thread(previous_response_id, thread_id)
        user_msg_id = await self._db.insert_message(actual_thread_id, "user", user_text)
        messages = await self.build_context(actual_thread_id)
        messages.append({"role": "user", "content": user_text})
        tools = tools_openai_format()
        probe_raw = await self._llm.chat_raw(messages, tools=tools)
        messages, _ = await maybe_call_one_tool(messages + [{"role": "assistant", "content": ""}], probe_raw)
        response_id = str(uuid.uuid4())
        yield {"type": "start", "response_id": response_id, "thread_id": actual_thread_id}
        buf: List[str] = []
        async for delta in self._llm.chat_stream(messages, tools=tools):
            buf.append(delta)
            yield {"type": "delta", "text": delta}
        output_text = "".join(buf).strip()
        out_msg_id = await self._db.insert_message(actual_thread_id, "assistant", output_text)
        await self._db.insert_response(actual_thread_id, user_msg_id, status="completed", usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        yield {"type": "end", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
