"""Persistent chat session management for multi-project workflows."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any
from pydantic import BaseModel, Field


class ChatSession(BaseModel):
    id: str
    title: str
    project_path: str | None = None
    created_at: str
    updated_at: str
    message_count: int = 0


class ChatManager:
    def __init__(self, db_path: Path | str | None = None) -> None:
        base = Path(db_path).expanduser() if db_path else Path.home() / ".codag" / "chats.db"
        self.db_path = base
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    project_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    turn_id TEXT,
                    metadata TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)
            conn.commit()

    def create_session(
        self,
        title: str,
        project_path: str | None = None,
        session_id: str | None = None,
    ) -> ChatSession:
        """Create a new chat session linked to a project."""
        sid = session_id or f"chat_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        resolved_proj = str(Path(project_path).expanduser().resolve()) if project_path else None

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (id, title, project_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (sid, title.strip(), resolved_proj, now, now),
            )
            conn.commit()

        return ChatSession(
            id=sid,
            title=title.strip(),
            project_path=resolved_proj,
            created_at=now,
            updated_at=now,
            message_count=0,
        )

    def get_session(self, session_id_or_title: str) -> ChatSession | None:
        """Find a session by ID or exact title."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT s.id, s.title, s.project_path, s.created_at, s.updated_at, COUNT(m.id)
                FROM sessions s
                LEFT JOIN messages m ON s.id = m.session_id
                WHERE s.id = ? OR LOWER(s.title) = LOWER(?)
                GROUP BY s.id
                """,
                (session_id_or_title, session_id_or_title),
            )
            row = cur.fetchone()
            if row:
                return ChatSession(
                    id=row[0],
                    title=row[1],
                    project_path=row[2],
                    created_at=row[3],
                    updated_at=row[4],
                    message_count=row[5],
                )
        return None

    def list_sessions(self) -> list[ChatSession]:
        """List all chat sessions ordered by most recently updated."""
        sessions: list[ChatSession] = []
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT s.id, s.title, s.project_path, s.created_at, s.updated_at, COUNT(m.id)
                FROM sessions s
                LEFT JOIN messages m ON s.id = m.session_id
                GROUP BY s.id
                ORDER BY s.updated_at DESC
            """)
            for row in cur.fetchall():
                sessions.append(
                    ChatSession(
                        id=row[0],
                        title=row[1],
                        project_path=row[2],
                        created_at=row[3],
                        updated_at=row[4],
                        message_count=row[5],
                    )
                )
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a chat session and its messages."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            return cur.rowcount > 0

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a message in the session and update timestamp."""
        now = datetime.now(timezone.utc).isoformat()
        meta_str = json.dumps(metadata) if metadata else None
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp, turn_id, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, role, content, now, turn_id, meta_str),
            )
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            conn.commit()

    def get_messages(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve recent messages for a session formatted for model context."""
        messages: list[dict[str, Any]] = []
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT role, content FROM (
                    SELECT id, role, content FROM messages
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC
                """,
                (session_id, limit),
            )
            for row in cur.fetchall():
                messages.append({"role": row[0], "content": row[1]})
        return messages

    def get_or_create_session(
        self,
        name_or_id: str | None = None,
        project_path: str | None = None,
    ) -> ChatSession:
        """Get an existing session or create a new one."""
        if name_or_id:
            existing = self.get_session(name_or_id)
            if existing:
                return existing
            return self.create_session(title=name_or_id, project_path=project_path)

        # If project_path provided, check if a session exists for this project
        if project_path:
            resolved = str(Path(project_path).expanduser().resolve())
            proj_name = Path(resolved).name
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id FROM sessions WHERE project_path = ? ORDER BY updated_at DESC LIMIT 1",
                    (resolved,),
                )
                row = cur.fetchone()
                if row:
                    return self.get_session(row[0])  # type: ignore
            return self.create_session(title=f"Project: {proj_name}", project_path=resolved)

        # Default fallback session
        existing_default = self.get_session("Default")
        if existing_default:
            return existing_default
        return self.create_session(title="General Chat")
