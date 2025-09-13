"""Thread summarization utilities.

Provides async summarize(thread_id) which composes a concise thread summary
(<= 1000 chars), stores/updates it in the DB, and returns the summary text.

Sections to cover: facts, tasks, file context, open questions.
Tool messages are excluded from the source history.
"""
from __future__ import annotations

from typing import List, Optional

from .db import Database
from .llm_client import LLMClient
from .logging_utils import log_error, log_info

# Module-local references to be initialized by the API on startup
_DB: Optional[Database] = None
_LLM: Optional[LLMClient] = None


def init(db: Database, llm: LLMClient) -> None:
    global _DB, _LLM
    _DB = db
    _LLM = llm


async def summarize(thread_id: str) -> str:
    """Create/update a concise summary for a thread and return it.

    - Collect last N messages (excluding role=tool)
    - Build a summarization prompt with sections: facts/tasks/file context/open questions
    - Ask the model for a short summary (<= 1000 chars)
    - Upsert into summaries table
    """
    assert _DB is not None and _LLM is not None, "summarizer not initialized"

    # Collect messages (limit generously to keep token usage bounded)
    LIMIT = 500
    rows = await _DB.get_thread_messages(thread_id, LIMIT)
    # Reverse to chronological order and filter out tool messages
    rows = list(reversed(rows))
    text_lines: List[str] = []
    for r in rows:
        role = str(r.get("role", ""))
        if role == "tool":
            continue
        content = str(r.get("content", "")).strip()
        if not content:
            continue
        text_lines.append(f"[{role}] {content}")

    convo = "\n".join(text_lines)

    system = (
        "You are an expert meeting/minutes assistant. Summarize the conversation briefly (<= 1000 characters). "
        "Use 4 sections with short bullet points: \n"
        "- Facts: key facts and decisions\n"
        "- Tasks: action items with owners if known\n"
        "- Files: referenced files or paths and their context\n"
        "- Open: open questions or next steps\n"
        "Be concise and avoid redundancy."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Conversation log:\n{convo}"},
    ]

    try:
        summary, _usage = await _LLM.chat(messages)  # no tools for summarization
    except Exception as e:  # noqa: BLE001
        log_error("summarize_llm_error", thread_id=thread_id, error=str(e))
        # Fallback: truncate conversation
        summary = (convo[:980] + "...") if len(convo) > 1000 else convo

    # Hard cap to 1000 chars
    if len(summary) > 1000:
        summary = summary[:997] + "..."

    await _DB.upsert_summary(thread_id, summary)
    log_info("summary_upserted", thread_id=thread_id, length=len(summary))
    return summary
