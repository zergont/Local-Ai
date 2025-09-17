"""Core service orchestration for Local Responses API."""
from __future__ import annotations

import json
import time
import uuid
import sys
import re
from typing import Any, AsyncIterator, Dict, List, Tuple

from .config import get_settings
from .db import Database
from .llm_client import LLMClient
from .logging_utils import log_info, log_error

try:  # pragma: no cover
    from .utils_tokens import estimate_messages_tokens, estimate_tokens  # type: ignore
except Exception:  # pragma: no cover
    def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:  # type: ignore
        total = 0
        for m in messages:
            c = m.get("content", "")
            if isinstance(c, list):
                flat_parts: List[str] = []
                for part in c:
                    if isinstance(part, str):
                        flat_parts.append(part)
                    elif isinstance(part, dict):
                        for v in part.values():
                            if isinstance(v, str):
                                flat_parts.append(v)
                c = " ".join(flat_parts)
            if not isinstance(c, str):
                c = str(c)
            total += max(1, int(len(c)/4)+2)
        return total
    def estimate_tokens(text: str) -> int:  # type: ignore
        return max(1, int(len(text)/4)+1)

SYSTEM_PROMPT = (
    "You are a helpful assistant. Be concise. "
    "If you need to deliberate or outline steps, put ALL of that inside <think>…</think> and write the final answer after the tag."
)
MEMORY_NAME_RE = re.compile(r"запомни,? что меня зовут (.+)$", re.IGNORECASE)


class LocalResponsesService:
    def __init__(self, db: Database, llm: LLMClient) -> None:
        self._db = db
        self._llm = llm
        self._s = get_settings()

    async def _maybe_store_memory(self, user_text: str) -> None:
        m = MEMORY_NAME_RE.search(user_text.strip())
        if not m:
            return
        name = m.group(1).strip().strip('.!')
        if len(name) > 80:
            name = name[:80]
        await self._db.upsert_profile_kv("user.name", name)
        log_info("memory_store", key="user.name", value=name)

    async def build_context(self, thread_id: str, *, k_override: int | None = None) -> List[Dict[str, str]]:
        chat: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        uname = await self._db.get_profile_value("user.name")
        if uname:
            chat.append({"role": "system", "content": f"Факты о пользователе: имя = {uname}."})
        summary = await self._db.get_summary(thread_id)
        if summary:
            chat.append({"role": "system", "content": f"Thread summary: {summary}"})
        k = k_override if k_override is not None else self._s.max_context_messages
        recent = await self._db.get_thread_messages(thread_id, k)
        for m in reversed(recent):
            chat.append({"role": str(m["role"]), "content": str(m["content"])})
        return chat

    async def _fold_history(self, thread_id: str) -> None:
        rows = list(reversed(await self._db.get_thread_messages(thread_id, 5000)))
        lines: List[str] = []
        for r in rows:
            role = str(r.get("role", ""))
            if role == "tool":
                continue
            content = str(r.get("content", "")).strip()
            if content:
                lines.append(f"{role}: {content}")
        convo_text = "\n".join(lines)
        if not convo_text:
            return
        system = "Сожми историю диалога в краткий конспект. Сохрани имена, предпочтения, задачи, факты и ссылки. Будь кратким и точным."
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": convo_text},
        ]
        t0 = time.perf_counter()
        try:
            summary, _usage = await self._llm.chat(messages)
            dt_ms = int((time.perf_counter() - t0) * 1000)
            log_info("summary", model=self._s.llm_model, stream=False, thread_id=thread_id, latency=dt_ms)
        except Exception as e:  # noqa: BLE001
            dt_ms = int((time.perf_counter() - t0) * 1000)
            log_error("summary_error", model=self._s.llm_model, stream=False, thread_id=thread_id, latency=dt_ms, error=str(e)[:200])
            log_error("fold_history_error", thread_id=thread_id, error=str(e))
            return
        await self._db.upsert_summary(thread_id, summary)
        log_info("fold_history_ok", thread_id=thread_id, length=len(summary))

    def _apply_budget(self, _tokens: int) -> int:
        return int(self._s.context_window_tokens * self._s.context_prompt_budget_ratio)

    async def _ensure_budget(self, thread_id: str, *, user_text: str) -> List[Dict[str, str]]:
        chat = await self.build_context(thread_id)
        used = estimate_messages_tokens(chat)
        budget = self._apply_budget(used)
        if used > budget + self._s.context_hysteresis_tokens:
            await self._fold_history(thread_id)
            chat = await self.build_context(thread_id)
            used = estimate_messages_tokens(chat)
        if used > budget:
            k = self._s.max_context_messages
            while used > budget and k > 1:
                k = max(1, int(k * 0.7))
                chat = await self.build_context(thread_id, k_override=k)
                used = estimate_messages_tokens(chat)
            log_info("context_trim", thread_id=thread_id, tokens=used, budget=budget, k_final=k)
        else:
            log_info("context_ok", thread_id=thread_id, tokens=used, budget=budget)
        return chat

    def _log_final(self, thread_id: str, response_id: str, latency_ms: int) -> None:
        log_info("final", model=self._s.llm_model, stream=True, thread_id=thread_id, response_id=response_id, latency=latency_ms)

    async def _run_stream_collect(self, messages: List[Dict[str, Any]]) -> tuple[str, Dict[str, int]]:
        parts: List[str] = []
        async for delta in self._llm.chat_stream(messages):
            parts.append(delta)
        full_raw = "".join(parts).strip()
        prompt_tokens = estimate_messages_tokens(messages)
        completion_tokens = estimate_tokens(full_raw)
        usage = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens}
        return full_raw, usage

    async def respond(self, *, thread_id: str | None, previous_response_id: str | None, user_text: str, store: bool) -> Tuple[str, str, str, Dict[str, int], str]:
        actual_thread_id = await self._db.resolve_thread(previous_response_id, thread_id)
        await self._maybe_store_memory(user_text)
        if store:
            user_msg_id = await self._db.insert_message(actual_thread_id, "user", user_text)
        else:
            user_msg_id = str(uuid.uuid4())
        chat = await self._ensure_budget(actual_thread_id, user_text=user_text)
        chat.append({"role": "user", "content": user_text})
        t0 = time.perf_counter()
        text, usage = await self._run_stream_collect(chat)
        dt_ms = int((time.perf_counter() - t0) * 1000)
        if store:
            assistant_msg_id = await self._db.insert_message(actual_thread_id, "assistant", text)
        else:
            assistant_msg_id = str(uuid.uuid4())
        resp_id = await self._db.insert_response(actual_thread_id, input_message_id=user_msg_id, status="completed", usage=usage, error=None)
        await self._db.update_response_output(resp_id, assistant_msg_id, status="completed")
        self._log_final(actual_thread_id, resp_id, dt_ms)
        try:
            row = await self._db.fetch_one("SELECT COUNT(1) AS n FROM messages WHERE thread_id= ?", [actual_thread_id])
            count = int(row["n"]) if row else 0
            if count >= self._s.summarize_after_messages and store:
                from . import summarizer
                await summarizer.summarize(actual_thread_id)
        except Exception:
            pass
        return user_msg_id, resp_id, text, usage, actual_thread_id

    async def respond_stream(self, *, user_text: str, thread_id: str | None, previous_response_id: str | None, store: bool) -> AsyncIterator[Dict[str, Any]]:
        actual_thread_id = await self._db.resolve_thread(previous_response_id, thread_id)
        await self._maybe_store_memory(user_text)
        user_msg_id = await self._db.insert_message(actual_thread_id, "user", user_text)
        messages = await self._ensure_budget(actual_thread_id, user_text=user_text)
        messages.append({"role": "user", "content": user_text})
        response_id = str(uuid.uuid4())
        t0 = time.perf_counter()
        yield {"type": "start", "response_id": response_id, "thread_id": actual_thread_id}
        raw_acc = ""
        async for delta in self._llm.chat_stream(messages):
            raw_acc += delta
            yield {"type": "delta", "text": delta}
        prompt_tokens = estimate_messages_tokens(messages)
        completion_tokens = estimate_tokens(raw_acc)
        usage = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens}
        out_msg_id = await self._db.insert_message(actual_thread_id, "assistant", raw_acc)
        await self._db.insert_response(actual_thread_id, user_msg_id, status="completed", usage=usage)
        dt_ms = int((time.perf_counter() - t0) * 1000)
        yield {"type": "end", "usage": usage}
        self._log_final(actual_thread_id, response_id, dt_ms)

    async def debug_context(self, thread_id: str) -> Dict[str, Any]:
        s = self._s
        budget = int(s.context_window_tokens * s.context_prompt_budget_ratio)
        async def _build(k: int) -> List[Dict[str, str]]:
            chat: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
            uname = await self._db.get_profile_value("user.name")
            if uname:
                chat.append({"role": "system", "content": f"Факты о пользователе: имя = {uname}."})
            summary = await self._db.get_summary(thread_id)
            if summary:
                chat.append({"role": "system", "content": f"Thread summary: {summary}"})
            recent = await self._db.get_thread_messages(thread_id, k)
            for m in reversed(recent):
                chat.append({"role": str(m["role"]), "content": str(m["content"])})
            return chat
        k = s.max_context_messages
        chat = await _build(k)
        used = estimate_messages_tokens(chat)
        if used > budget:
            while used > budget and k > 1:
                k = max(1, int(k * 0.7))
                chat = await _build(k)
                used = estimate_messages_tokens(chat)
        summary_tokens = 0
        for m in chat:
            if m["role"] == "system" and m["content"].startswith("Thread summary:"):
                summary_tokens = estimate_messages_tokens([m])
                break
        items: List[Dict[str, Any]] = []
        for m in chat:
            t = estimate_messages_tokens([m])
            content = str(m.get("content", ""))
            preview = content[:160] + ("…" if len(content) > 160 else "")
            items.append({"role": m.get("role", ""), "tokens": t, "preview": preview})
        remaining = max(0, budget - used)
        return {"thread_id": thread_id, "budget_tokens": budget, "estimated_used": used, "remaining": remaining, "summary_tokens": summary_tokens, "k_last_used": k, "messages": items}
