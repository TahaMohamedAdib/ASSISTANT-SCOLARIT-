"""Persistance applicative SQLite (bibliotheque standard, sans ORM).

Tables : registre des documents (avec versions), taches d'ingestion,
conversations, messages, retours 👍/👎, questions sans reponse, pieces
jointes temporaires et executions d'evaluation. L'index vectoriel reste dans
Chroma ; cette base ne contient que des metadonnees et l'historique.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    doc_type TEXT,
    department TEXT,
    effective_date TEXT,
    version TEXT,
    official INTEGER NOT NULL DEFAULT 1,
    reference TEXT,
    file_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    extension TEXT NOT NULL,
    status TEXT NOT NULL,            -- uploaded | processing | indexed | failed | pending_review | superseded
    is_base INTEGER NOT NULL DEFAULT 0,
    page_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    uploaded_by TEXT,
    uploaded_at TEXT NOT NULL,
    indexed_at TEXT,
    replaces_id TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS documents_sha ON documents(sha256);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    stage TEXT NOT NULL,             -- uploaded | parsing | chunking | embedding | indexed | failed
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,              -- user | assistant
    content TEXT NOT NULL,
    payload TEXT,                    -- JSON : citations, found, followups, debug, stopped
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE,
    conversation_id TEXT,
    rating INTEGER NOT NULL,         -- 1 = 👍, -1 = 👎
    comment TEXT,
    question TEXT,
    answer TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS unanswered (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    conversation_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    chunks TEXT NOT NULL,            -- JSON : [{"text", "page", "vector"}]
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,            -- running | done | failed
    mode TEXT NOT NULL,
    summary TEXT,
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


class Database:
    """Acces thread-safe (un verrou, une connexion) : l'API et les taches de fond la partagent."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------------ helpers
    def execute(self, sql: str, params: tuple | dict = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def insert(self, table: str, values: dict[str, Any]) -> None:
        columns = ", ".join(values)
        marks = ", ".join(f":{key}" for key in values)
        self.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", values)

    def update(self, table: str, row_id: str, values: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = :{key}" for key in values)
        self.execute(f"UPDATE {table} SET {assignments} WHERE id = :_id", {**values, "_id": row_id})

    # ------------------------------------------------------------------ documents
    def document(self, document_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM documents WHERE id = ?", (document_id,))

    def documents(self, include_history: bool = False) -> list[dict[str, Any]]:
        where = "" if include_history else "WHERE status != 'superseded'"
        return self.all(f"SELECT * FROM documents {where} ORDER BY is_base DESC, uploaded_at DESC, title")

    # ------------------------------------------------------------------ conversations
    def conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))

    def messages(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self.all("SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid", (conversation_id,))
        for row in rows:
            row["payload"] = json.loads(row["payload"]) if row["payload"] else {}
        return rows

    def add_message(self, conversation_id: str, role: str, content: str, payload: dict | None = None) -> str:
        message_id = new_id()
        stamp = now()
        self.insert("messages", {
            "id": message_id, "conversation_id": conversation_id, "role": role, "content": content,
            "payload": json.dumps(payload or {}, ensure_ascii=False), "created_at": stamp,
        })
        self.update("conversations", conversation_id, {"updated_at": stamp})
        return message_id
