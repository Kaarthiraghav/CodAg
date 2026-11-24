"""Task management skill backed by SQLite."""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from codag.core.types import RiskTier, ToolResult
from codag.skills.base import tool
from codag.skills.registry import default_registry


class TaskDatabase:
    def __init__(self, db_path: Path | str | None = None) -> None:
        base = Path(db_path).expanduser() if db_path else Path.home() / ".codag" / "tasks.db"
        self.db_path = base
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                )
            """)
            conn.commit()

    def add(self, title: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO tasks (title, status, created_at) VALUES (?, 'pending', ?)", (title, now))
            conn.commit()
            return cur.lastrowid or 0

    def list(self, status: str | None = None) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                cur = conn.execute("SELECT * FROM tasks WHERE status = ? ORDER BY id ASC", (status,))
            else:
                cur = conn.execute("SELECT * FROM tasks ORDER BY id ASC")
            return [dict(row) for row in cur.fetchall()]

    def complete(self, task_id: int) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("UPDATE tasks SET status = 'completed', completed_at = ? WHERE id = ?", (now, task_id))
            conn.commit()
            return cur.rowcount > 0


_task_db = TaskDatabase()


def configure_tasks(db_path: Path | str) -> None:
    global _task_db
    _task_db = TaskDatabase(db_path)


@tool(
    name="tasks.add_task",
    tier=RiskTier.SAFE_WRITE,
    description="Add a new to-do task.",
)
def add_task(title: str) -> ToolResult:
    try:
        task_id = _task_db.add(title.strip())
        return ToolResult(call_id="", ok=True, content=f"Added task #{task_id}: {title!r}")
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to add task: {exc}")


@tool(
    name="tasks.list_tasks",
    tier=RiskTier.READ,
    description="List to-do tasks (filter by 'pending', 'completed', or None for all).",
)
def list_tasks(status: str = "pending") -> ToolResult:
    try:
        filter_status = None if status.lower() in ("all", "any") else status.lower()
        items = _task_db.list(filter_status)
        if not items:
            return ToolResult(call_id="", ok=True, content="No tasks found.")

        lines = []
        for it in items:
            mark = "[x]" if it["status"] == "completed" else "[ ]"
            lines.append(f"{mark} #{it['id']} {it['title']} ({it['status']})")
        return ToolResult(call_id="", ok=True, content="\n".join(lines))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to list tasks: {exc}")


@tool(
    name="tasks.complete_task",
    tier=RiskTier.SAFE_WRITE,
    description="Mark a task as completed by its integer ID.",
)
def complete_task(task_id: int) -> ToolResult:
    try:
        success = _task_db.complete(int(task_id))
        if success:
            return ToolResult(call_id="", ok=True, content=f"Task #{task_id} marked as completed.")
        return ToolResult(call_id="", ok=False, content=f"Task #{task_id} not found.")
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to complete task: {exc}")


default_registry.register(add_task)
default_registry.register(list_tasks)
default_registry.register(complete_task)
