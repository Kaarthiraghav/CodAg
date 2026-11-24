"""SQLite storage for durable facts and episodic conversation history."""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any


class MemoryStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        base = Path(db_path).expanduser() if db_path else Path.home() / ".codag" / "memory.db"
        self.db_path = base
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    source_turn TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    assistant_message TEXT NOT NULL,
                    summary TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    # --- Facts API ---

    def add_or_update_fact(
        self,
        key: str,
        value: str,
        category: str = "general",
        source_turn: str | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO facts (key, value, category, source_turn, created_at, updated_at, status)
                VALUES (?, ?, ?, ?, ?, ?, 'active')
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    updated_at = excluded.updated_at
            """, (key.strip().lower(), value.strip(), category.strip().lower(), source_turn, now, now))
            conn.commit()
            return cur.lastrowid or 0

    def get_fact(self, fact_id: int) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_fact_by_key(self, key: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM facts WHERE key = ?", (key.strip().lower(),))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_facts(self, category: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if category:
                cur = conn.execute(
                    "SELECT * FROM facts WHERE category = ? ORDER BY id DESC LIMIT ?",
                    (category.strip().lower(), limit),
                )
            else:
                cur = conn.execute("SELECT * FROM facts ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    def delete_fact(self, identifier: int | str) -> bool:
        """Hard delete as per spec 8.3: Forget requests delete the data; do not mark hidden."""
        with sqlite3.connect(self.db_path) as conn:
            if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
                cur = conn.execute("DELETE FROM facts WHERE id = ?", (int(identifier),))
            else:
                cur = conn.execute("DELETE FROM facts WHERE key = ?", (str(identifier).strip().lower(),))
            conn.commit()
            return cur.rowcount > 0

    def export_facts(self) -> list[dict[str, Any]]:
        return self.list_facts(limit=1000)

    # --- Episodes API ---

    def add_episode(
        self,
        turn_id: str,
        user_message: str,
        assistant_message: str,
        summary: str | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO episodes (turn_id, user_message, assistant_message, summary, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (turn_id, user_message, assistant_message, summary, now))
            conn.commit()
            return cur.lastrowid or 0

    def list_recent_episodes(self, limit: int = 10) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM episodes ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]
