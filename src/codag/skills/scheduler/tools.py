"""Scheduler skill tools: reminders, briefings, and launchd service generator."""

from pathlib import Path
from typing import Any

from codag.core.types import RiskTier, ToolResult
from codag.skills.base import tool
from codag.skills.registry import default_registry
from codag.skills.scheduler.service import SchedulerService


class SchedulerEnvironment:
    def __init__(self) -> None:
        self.service: SchedulerService | None = None


_scheduler_env = SchedulerEnvironment()


def configure_scheduler(db_path: Path | str | None = None, tasks_db: Path | str | None = None) -> None:
    global _scheduler_env
    if _scheduler_env.service is None:
        _scheduler_env.service = SchedulerService(db_path=db_path, tasks_db=tasks_db)


def _get_service() -> SchedulerService:
    global _scheduler_env
    if _scheduler_env.service is None:
        _scheduler_env.service = SchedulerService()
    return _scheduler_env.service


@tool(
    name="scheduler.create_reminder",
    tier=RiskTier.SAFE_WRITE,
    description="Schedule a reminder notification for a specific time or delay (e.g. 'in 10 minutes', 'at 15:30').",
)
def create_reminder(message: str, when: str = "in 10 minutes") -> ToolResult:
    """Schedule a reminder to be delivered as a macOS desktop notification."""
    try:
        service = _get_service()
        record = service.schedule_reminder(message=message, when=when)
        return ToolResult(
            call_id="",
            ok=True,
            content=f"Reminder scheduled (#{record.id}): '{message}' at {record.target_time}",
        )
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to schedule reminder: {exc}")


@tool(
    name="scheduler.list_reminders",
    tier=RiskTier.READ,
    description="List scheduled and pending reminders.",
)
def list_reminders(status: str = "") -> ToolResult:
    """List reminders from the scheduler store."""
    try:
        service = _get_service()
        records = service.list_reminders(status=status if status else None)
        if not records:
            return ToolResult(call_id="", ok=True, content="No reminders found.")

        lines = ["Scheduled Reminders:"]
        for r in records:
            lines.append(f"- [{r.status.upper()}] #{r.id}: '{r.message}' (due: {r.target_time})")
        return ToolResult(call_id="", ok=True, content="\n".join(lines))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to list reminders: {exc}")


@tool(
    name="scheduler.cancel_reminder",
    tier=RiskTier.SAFE_WRITE,
    description="Cancel a scheduled reminder by its ID (e.g. 'rem_1234abcd').",
)
def cancel_reminder(reminder_id: str) -> ToolResult:
    """Cancel an active scheduled reminder."""
    try:
        service = _get_service()
        ok = service.cancel_reminder(reminder_id)
        if ok:
            return ToolResult(call_id="", ok=True, content=f"Reminder #{reminder_id} cancelled successfully.")
        else:
            return ToolResult(call_id="", ok=False, content=f"Reminder #{reminder_id} not found.")
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to cancel reminder: {exc}")


@tool(
    name="scheduler.schedule_daily_briefing",
    tier=RiskTier.SAFE_WRITE,
    description="Configure a recurring daily morning briefing notification (e.g. '09:00').",
)
def schedule_daily_briefing(time_of_day: str = "09:00") -> ToolResult:
    """Schedule a recurring morning briefing summarizing pending tasks."""
    try:
        service = _get_service()
        msg = service.schedule_daily_briefing(time_of_day=time_of_day)
        return ToolResult(call_id="", ok=True, content=msg)
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to schedule daily briefing: {exc}")


@tool(
    name="scheduler.generate_launchd_service",
    tier=RiskTier.SAFE_WRITE,
    description="Generate macOS launchd agent configuration to run CodAg scheduler at login.",
)
def generate_launchd_service() -> ToolResult:
    """Generate launchd plist for persistence."""
    try:
        service = _get_service()
        plist_content = service.generate_launchd_plist()
        launch_dir = Path.home() / "Library" / "LaunchAgents"
        launch_dir.mkdir(parents=True, exist_ok=True)
        plist_path = launch_dir / "com.codag.assistant.plist"
        plist_path.write_text(plist_content, encoding="utf-8")
        return ToolResult(
            call_id="",
            ok=True,
            content=f"launchd agent plist generated at {plist_path}. Load with:\nlaunchctl load {plist_path}",
        )
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to generate launchd service: {exc}")


# Auto-register scheduler tools
default_registry.register(create_reminder)
default_registry.register(list_reminders)
default_registry.register(cancel_reminder)
default_registry.register(schedule_daily_briefing)
default_registry.register(generate_launchd_service)
