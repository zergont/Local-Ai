"""Async SQLite data access layer using aiosqlite.

Schema:
- threads(id TEXT PRIMARY KEY, created_at REAL)
- messages(id TEXT PRIMARY KEY, thread_id TEXT, role TEXT, content TEXT, created_at REAL,
           token_count INTEGER DEFAULT 0)
- summaries(thread_id TEXT PRIMARY KEY, content TEXT, created_at REAL)
- profiles(id TEXT PRIMARY KEY, name TEXT UNIQUE, settings_json TEXT, created_at REAL)
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import aiosqlite

from .logging_utils import log_error, log_info


PRAGMAS = [
    "PRAGMA journal_mode=WAL;",
    "PRAGMA synchronous=NORMAL;",
    "PRAGMA foreign_keys=ON;",
    "PRAGMA busy_timeout=5000;",
    "PRAGMA temp_store=MEMORY;",
]


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._pool_lock = asyncio.Lock()
        self._db: Optional[aiosqlite.Connection] = None

    @property
    def path(self) -> str:
        return self._path

    async def connect(self) -> None:
        db_dir = Path(self._path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        for pragma in PRAGMAS:
            await self._db.execute(pragma)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    # ---- low-level helpers with locked-retry on 'database is locked' ----

    async def _execute_with_retry(self, func, *args) -> Any:
        assert self._db is not None
        delays = [0.01, 0.02, 0.04, 0.08]
        last_err: Optional[Exception] = None
        for i, d in enumerate(delays, start=1):
            try:
                return await func(*args)
            except aiosqlite.OperationalError as e:  # type: ignore[attr-defined]
                msg = str(e)
                if "database is locked" in msg:
                    log_error("sqlite_locked", attempt=i, delay_s=d)
                    await asyncio.sleep(d)
                    continue
                raise
            except Exception as e:  # noqa: BLE001
                last_err = e
                break
        if last_err:
            raise last_err

    async def executescript(self, script: str) -> None:
        assert self._db is not None, "Database not connected"
        await self._execute_with_retry(self._db.executescript, script)
        await self._db.commit()

    async def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        assert self._db is not None, "Database not connected"
        await self._execute_with_retry(self._db.execute, sql, params or [])
        await self._db.commit()

    async def fetch_one(self, sql: str, params: Sequence[Any] | None = None) -> Optional[Dict[str, Any]]:
        assert self._db is not None, "Database not connected"
        self._db.row_factory = aiosqlite.Row
        async def _inner() -> Any:
            async with self._db.execute(sql, params or []) as cursor:
                return await cursor.fetchone()
        row = await self._execute_with_retry(_inner)
        return dict(row) if row else None

    async def fetch_all(self, sql: str, params: Sequence[Any] | None = None) -> List[Dict[str, Any]]:
        assert self._db is not None, "Database not connected"
        self._db.row_factory = aiosqlite.Row
        async def _inner() -> Any:
            async with self._db.execute(sql, params or []) as cursor:
                return await cursor.fetchall()
        rows = await self._execute_with_retry(_inner)
        return [dict(r) for r in rows]

    # ----------------- CRUD helpers -----------------

    async def create_thread(self) -> str:
        """Create a new thread and return its id."""
        thread_id = str(uuid.uuid4())
        await self.execute(
            "INSERT INTO threads(id, created_at) VALUES (?, ?)",
            [thread_id, time.time()],
        )
        return thread_id

    async def insert_message(self, thread_id: str, role: str, content_json: str) -> str:
        """Insert a message (content_json stored as TEXT) and return its id.

        Note: schema expects role in ('user','assistant','system','tool').
        """
        message_id = str(uuid.uuid4())
        await self.execute(
            "INSERT INTO messages(id, thread_id, role, content, created_at) VALUES (?,?,?,?,?)",
            [message_id, thread_id, role, content_json, time.time()],
        )
        return message_id

    async def insert_response(
        self,
        thread_id: str,
        input_message_id: str,
        status: str,
        usage: Dict[str, Any],
        error: Optional[str] = None,
    ) -> str:
        """Insert a response record with status/usage/error and return response_id.

        Requires columns: status TEXT, usage_json TEXT, error_text TEXT in responses table.
        """
        response_id = str(uuid.uuid4())
        usage_json = json.dumps(usage, ensure_ascii=False)
        await self.execute(
            (
                "INSERT INTO responses(id, thread_id, request_message_id, response_message_id, status, usage_json, error_text, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)"
            ),
            [
                response_id,
                thread_id,
                input_message_id,
                None,
                status,
                usage_json,
                error,
                time.time(),
            ],
        )
        return response_id

    async def update_response_output(self, response_id: str, output_message_id: str, status: str) -> None:
        """Update response with generated assistant message id and final status."""
        await self.execute(
            "UPDATE responses SET response_message_id = ?, status = ? WHERE id = ?",
            [output_message_id, status, response_id],
        )

    async def get_thread_messages(self, thread_id: str, limit: int) -> List[Dict[str, Any]]:
        """Return latest messages by created_at (descending), limited."""
        rows = await self.fetch_all(
            "SELECT id, role, content, created_at FROM messages WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?",
            [thread_id, limit],
        )
        return rows

    async def get_summary(self, thread_id: str) -> Optional[str]:
        row = await self.fetch_one("SELECT content FROM summaries WHERE thread_id = ?", [thread_id])
        return str(row["content"]) if row else None

    async def upsert_summary(self, thread_id: str, summary: str) -> None:
        await self.execute(
            (
                "INSERT INTO summaries(thread_id, content, created_at) VALUES (?,?,?) "
                "ON CONFLICT(thread_id) DO UPDATE SET content = excluded.content, created_at = excluded.created_at"
            ),
            [thread_id, summary, time.time()],
        )

    async def resolve_thread(self, previous_response_id: Optional[str], explicit_thread_id: Optional[str]) -> str:
        """Resolve actual thread id based on either explicit thread or previous response.

        If explicit thread_id provided -> return it.
        Else if previous_response_id provided -> look up thread_id from responses.
        Else -> create a new thread and return its id.
        """
        if explicit_thread_id:
            return explicit_thread_id
        if previous_response_id:
            row = await self.fetch_one("SELECT thread_id FROM responses WHERE id = ?", [previous_response_id])
            if row and row.get("thread_id"):
                return str(row["thread_id"])
        return await self.create_thread()

    async def get_response_detail(self, response_id: str) -> Optional[Dict[str, Any]]:
        """Return response record with thread_id, output_text, usage as dict.

        Joins responses with messages on response_message_id to fetch output_text.
        """
        sql = (
            "SELECT r.id as response_id, r.thread_id as thread_id, r.usage_json as usage_json, "
            "m.content as output_text "
            "FROM responses r LEFT JOIN messages m ON m.id = r.response_message_id "
            "WHERE r.id = ?"
        )
        row = await self.fetch_one(sql, [response_id])
        if not row:
            return None
        usage: Dict[str, Any] = {}
        if row.get("usage_json"):
            try:
                usage = json.loads(row["usage_json"]) if isinstance(row["usage_json"], str) else {}
            except Exception:
                usage = {}
        return {
            "response_id": str(row.get("response_id", response_id)),
            "thread_id": str(row.get("thread_id", "")),
            "output_text": str(row.get("output_text", "")),
            "usage": usage,
        }

    # --------------- profiles (memory) ---------------

    async def upsert_profile_kv(self, key: str, value: str) -> None:
        """Store single key/value in profiles (name unique)."""
        assert self._db is not None
        now = time.time()
        row = await self.fetch_one("SELECT id FROM profiles WHERE name=?", [key])
        payload = json.dumps({"value": value}, ensure_ascii=False)
        if row:
            await self.execute("UPDATE profiles SET settings_json=?, created_at=? WHERE name=?", [payload, now, key])
        else:
            pid = str(uuid.uuid4())
            await self.execute(
                "INSERT INTO profiles(id, name, settings_json, created_at) VALUES (?,?,?,?)",
                [pid, key, payload, now],
            )
        log_info("profile_upsert", key=key, value=value)

    async def get_profile_value(self, key: str) -> Optional[str]:
        row = await self.fetch_one("SELECT settings_json FROM profiles WHERE name=?", [key])
        if not row:
            return None
        try:
            data = json.loads(row["settings_json"]) if row["settings_json"] else {}
            v = data.get("value")
            if v is None:
                return None
            return str(v)
        except Exception:
            return None
