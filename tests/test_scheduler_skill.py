"""Tests for the scheduler skill: parsing, reminders, briefings, and launchd service."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from codag.core.types import RiskTier
from codag.skills.registry import default_registry
from codag.skills.scheduler.service import SchedulerService, parse_time_spec
from codag.skills.scheduler.tools import (
    cancel_reminder,
    configure_scheduler,
    create_reminder,
    generate_launchd_service,
    list_reminders,
    schedule_daily_briefing,
)


def test_scheduler_tools_registered():
    create_spec = default_registry.get_spec("scheduler.create_reminder")
    list_spec = default_registry.get_spec("scheduler.list_reminders")
    cancel_spec = default_registry.get_spec("scheduler.cancel_reminder")
    brief_spec = default_registry.get_spec("scheduler.schedule_daily_briefing")
    launch_spec = default_registry.get_spec("scheduler.generate_launchd_service")

    assert create_spec is not None and create_spec.base_tier == RiskTier.SAFE_WRITE
    assert list_spec is not None and list_spec.base_tier == RiskTier.READ
    assert cancel_spec is not None and cancel_spec.base_tier == RiskTier.SAFE_WRITE
    assert brief_spec is not None and brief_spec.base_tier == RiskTier.SAFE_WRITE
    assert launch_spec is not None and launch_spec.base_tier == RiskTier.SAFE_WRITE


def test_parse_time_spec():
    now = datetime.now()

    dt_secs = parse_time_spec("in 30 seconds")
    assert abs((dt_secs - (now + timedelta(seconds=30))).total_seconds()) < 2

    dt_mins = parse_time_spec("in 15 minutes")
    assert abs((dt_mins - (now + timedelta(minutes=15))).total_seconds()) < 2

    dt_hours = parse_time_spec("in 2 hours")
    assert abs((dt_hours - (now + timedelta(hours=2))).total_seconds()) < 2

    dt_at = parse_time_spec("at 14:30")
    assert dt_at.hour == 14
    assert dt_at.minute == 30


def test_scheduler_service_lifecycle(tmp_path: Path):
    db_file = tmp_path / "sched.db"
    tasks_file = tmp_path / "tasks.db"
    service = SchedulerService(db_path=db_file, tasks_db=tasks_file)

    # 1. Schedule reminder
    rec = service.schedule_reminder("Take vitamins", "in 10 minutes")
    assert rec.id.startswith("rem_")
    assert rec.status == "scheduled"

    # 2. List reminders
    recs = service.list_reminders()
    assert len(recs) == 1
    assert recs[0].message == "Take vitamins"

    # 3. Cancel reminder
    ok = service.cancel_reminder(rec.id)
    assert ok is True

    # 4. List cancelled
    cancelled = service.list_reminders(status="cancelled")
    assert len(cancelled) == 1
    assert cancelled[0].id == rec.id

    # 5. Daily briefing
    msg = service.schedule_daily_briefing("08:30")
    assert "08:30" in msg

    # 6. Launchd plist generator
    plist = service.generate_launchd_plist()
    assert "com.codag.assistant" in plist
    assert "<plist" in plist

    service.scheduler.shutdown(wait=False)


@patch("codag.skills.scheduler.tools._get_service")
def test_scheduler_tools_wrapper(mock_service):
    mock_inst = MagicMock()
    mock_service.return_value = mock_inst

    mock_rec = MagicMock(id="rem_1234", target_time="2026-11-22T12:00:00")
    mock_inst.schedule_reminder.return_value = mock_rec

    res = create_reminder("Meeting with Bob", "in 5 minutes")
    assert res.ok is True
    assert "rem_1234" in res.content

    mock_inst.list_reminders.return_value = [
        MagicMock(status="scheduled", id="rem_1234", message="Meeting with Bob", target_time="2026-11-22T12:00:00")
    ]
    res_list = list_reminders()
    assert res_list.ok is True
    assert "Meeting with Bob" in res_list.content

    mock_inst.cancel_reminder.return_value = True
    res_cancel = cancel_reminder("rem_1234")
    assert res_cancel.ok is True
    assert "cancelled successfully" in res_cancel.content
