"""Scheduler service using APScheduler and SQLite persistence."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import uuid
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger

from codag.skills.system.tools import notify as system_notify


def parse_time_spec(when: str) -> datetime:
    """Parse relative or absolute time spec into a timezone-aware datetime."""
    cleaned = when.lower().strip()
    now = datetime.now()

    # 1. Check relative: in X seconds / minutes / hours / days
    m_rel = re.match(r"(?:in\s+)?(\d+)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)$", cleaned)
    if m_rel:
        qty = int(m_rel.group(1))
        unit = m_rel.group(2)
        if unit.startswith("s"):
            return now + timedelta(seconds=qty)
        elif unit.startswith("m"):
            return now + timedelta(minutes=qty)
        elif unit.startswith("h"):
            return now + timedelta(hours=qty)
        elif unit.startswith("d"):
            return now + timedelta(days=qty)

    # 2. Check at HH:MM
    m_time = re.match(r"(?:at\s+)?(\d{1,2}):(\d{2})\s*(am|pm)?$", cleaned)
    if m_time:
        hour = int(m_time.group(1))
        minute = int(m_time.group(2))
        ampm = m_time.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    # 3. Try ISO format
    try:
        return datetime.fromisoformat(when)
    except Exception:
        pass

    # Default fallback: 10 minutes from now
    return now + timedelta(minutes=10)


class ReminderRecord:
    def __init__(
        self,
        id: str,
        message: str,
        target_time: str,
        status: str = "scheduled",
        created_at: str | None = None,
    ) -> None:
        self.id = id
        self.message = message
        self.target_time = target_time
        self.status = status
        self.created_at = created_at or datetime.now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "message": self.message,
            "target_time": self.target_time,
            "status": self.status,
            "created_at": self.created_at,
        }


class SchedulerService:
    def __init__(
        self,
        db_path: Path | str | None = None,
        tasks_db: Path | str | None = None,
    ) -> None:
        base_dir = Path.home() / ".codag"
        self.db_path = Path(db_path) if db_path else base_dir / "scheduler.db"
        self.tasks_db = Path(tasks_db) if tasks_db else base_dir / "tasks.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()
        self.scheduler = BackgroundScheduler()
        if not self.scheduler.running:
            self.scheduler.start()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY,
                    message TEXT NOT NULL,
                    target_time TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def _on_reminder_fire(self, reminder_id: str, message: str) -> None:
        """Triggered by APScheduler when reminder time arrives."""
        # 1. Fire desktop notification
        system_notify(title="CodAg Reminder", message=message)

        # 2. Update status in database
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE reminders SET status = 'completed' WHERE id = ?", (reminder_id,))
            conn.commit()

    def _on_briefing_fire(self) -> None:
        """Triggered by APScheduler for daily briefing."""
        pending_tasks = []
        if self.tasks_db.exists():
            try:
                with sqlite3.connect(self.tasks_db) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, title FROM tasks WHERE status = 'pending' ORDER BY id ASC LIMIT 5")
                    pending_tasks = cur.fetchall()
            except Exception:
                pass

        count = len(pending_tasks)
        if count == 0:
            msg = "Good morning! You have no pending tasks today."
        else:
            task_titles = ", ".join(t[1] for t in pending_tasks[:3])
            msg = f"Good morning! You have {count} pending tasks: {task_titles}."

        system_notify(title="CodAg Daily Briefing", message=msg)

    def schedule_reminder(self, message: str, when: str) -> ReminderRecord:
        """Schedule a reminder to fire at a target time."""
        target_dt = parse_time_spec(when)
        reminder_id = f"rem_{uuid.uuid4().hex[:8]}"

        record = ReminderRecord(
            id=reminder_id,
            message=message,
            target_time=target_dt.isoformat(),
            status="scheduled",
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO reminders (id, message, target_time, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (record.id, record.message, record.target_time, record.status, record.created_at),
            )
            conn.commit()

        # Add to APScheduler
        self.scheduler.add_job(
            self._on_reminder_fire,
            trigger=DateTrigger(run_date=target_dt),
            args=[reminder_id, message],
            id=reminder_id,
            replace_existing=True,
        )

        return record

    def list_reminders(self, status: str | None = None) -> list[ReminderRecord]:
        """List stored reminders."""
        query = "SELECT id, message, target_time, status, created_at FROM reminders"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY target_time ASC"

        results: list[ReminderRecord] = []
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            for row in cur.fetchall():
                results.append(
                    ReminderRecord(
                        id=row[0],
                        message=row[1],
                        target_time=row[2],
                        status=row[3],
                        created_at=row[4],
                    )
                )
        return results

    def cancel_reminder(self, reminder_id: str) -> bool:
        """Cancel a pending reminder."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ?", (reminder_id,))
            updated = cur.rowcount > 0
            conn.commit()

        try:
            self.scheduler.remove_job(reminder_id)
        except Exception:
            pass

        return updated

    def schedule_daily_briefing(self, time_of_day: str = "09:00") -> str:
        """Schedule a recurring daily briefing job."""
        parts = time_of_day.strip().split(":")
        hour = int(parts[0]) if parts else 9
        minute = int(parts[1]) if len(parts) > 1 else 0

        job_id = "codag_daily_briefing"
        self.scheduler.add_job(
            self._on_briefing_fire,
            trigger=CronTrigger(hour=hour, minute=minute),
            id=job_id,
            replace_existing=True,
        )
        return f"Daily briefing scheduled at {hour:02d}:{minute:02d} every day."

    def generate_launchd_plist(self) -> str:
        """Generate a launchd agent plist string for login autostart."""
        user_home = Path.home()
        codag_bin = shutil_which_codag = sys.executable
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.codag.assistant</string>
    <key>ProgramArguments</key>
    <array>
        <string>{codag_bin}</string>
        <string>-m</string>
        <string>codag.cli</string>
        <string>chat</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{user_home}/.codag/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>{user_home}/.codag/launchd_err.log</string>
</dict>
</plist>
"""
