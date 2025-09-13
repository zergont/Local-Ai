"""Core service orchestration for Local Responses API."""
from __future__ import annotations

import uuid
from typing import Dict, List, Tuple

from .config import get_settings
from .db import Database
from .llm_client import LLMClient
from .logging_utils import log_info


SYSTEM_PROMPT = "You are a helpful assistant. Be concise."


class LocalResponsesService:
    def __init__(self, db: Database, llm: LLMClient) -> None:
        self._db = db
        self._llm = llm
        self._s = get_settings()

    async def build_context(self, thread_id: str) -> List[Dict[str, str]]:
        # Compose context from summary + recent messages
        chat: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        summary = await self._db.get_summary(thread_id)
        if summary:
            chat.append({"role": "system", "content": f"Thread summary: {summary}"})
        recent = await self._db.get_thread_messages(thread_id, self._s.max_context_messages)
        # recent are DESC by created_at; reverse to chronological
        for m in reversed(recent):
            chat.append({"role": str(m["role"]), "content": str(m["content"])})
        return chat

    async def respond(
        self,
        *,
        thread_id: str | None,
        previous_response_id: str | None,
        user_text: str,
        store: bool,
    ) -> Tuple[str, str, str, Dict[str, int], str]:
        """Generate assistant response and optionally store messages.

        Returns: (user_msg_id, resp_msg_id, output_text, usage, actual_thread_id)
        """
        # Resolve thread id
        actual_thread_id = await self._db.resolve_thread(previous_response_id, thread_id)

        # Optionally store user message
        if store:
            user_msg_id = await self._db.insert_message(actual_thread_id, "user", user_text)
        else:
            user_msg_id = str(uuid.uuid4())

        # Build context and call LLM
        chat = await self.build_context(actual_thread_id)
        chat.append({"role": "user", "content": user_text})
        output_text, usage = await self._llm.chat(chat)

        # Optionally store assistant message
        if store:
            assistant_msg_id = await self._db.insert_message(actual_thread_id, "assistant", output_text)
        else:
            assistant_msg_id = str(uuid.uuid4())

        # Store response record (even if not storing messages, record the transaction)
        resp_id = await self._db.insert_response(
            actual_thread_id,
            input_message_id=user_msg_id,
            status="completed",
            usage=usage,
            error=None,
        )
        await self._db.update_response_output(resp_id, assistant_msg_id, status="completed")

        # Summarize opportunistically if threshold reached
        try:
            row = await self._db.fetch_one(
                "SELECT COUNT(1) AS n FROM messages WHERE thread_id=?",
                [actual_thread_id],
            )
            count = int(row["n"]) if row else 0
            if count >= self._s.summarize_after_messages and store:
                summarize_chat = [
                    {"role": "system", "content": "Summarize the following conversation in 1-2 sentences."},
                    *chat,
                    {"role": "assistant", "content": output_text},
                ]
                summary_text, _ = await self._llm.chat(summarize_chat)
                await self._db.upsert_summary(actual_thread_id, summary_text.strip())
                log_info("summary_updated", thread_id=actual_thread_id)
        except Exception:
            # Do not break response flow if summary fails
            pass

        return user_msg_id, resp_id, output_text, usage, actual_thread_id
