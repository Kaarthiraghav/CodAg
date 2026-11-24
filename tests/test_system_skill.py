"""Tests for the system skill: notifications, clipboard, apps, and settings."""

from unittest.mock import MagicMock, patch
import pytest

from codag.config import PolicyConfig
from codag.core.types import RiskTier, ToolCall, TurnContext
from codag.safety.permissions import PermissionEngine
from codag.safety.sandbox import Sandbox
from codag.skills.registry import default_registry
from codag.skills.system.tools import (
    change_setting,
    clipboard,
    notify,
    open_app,
    quit_app,
)


def test_system_tools_registered():
    notify_spec = default_registry.get_spec("system.notify")
    open_spec = default_registry.get_spec("system.open_app")
    clip_spec = default_registry.get_spec("system.clipboard")
    quit_spec = default_registry.get_spec("system.quit_app")
    setting_spec = default_registry.get_spec("system.change_setting")

    assert notify_spec is not None and notify_spec.base_tier == RiskTier.SAFE_WRITE
    assert open_spec is not None and open_spec.base_tier == RiskTier.SAFE_WRITE
    assert clip_spec is not None and clip_spec.base_tier == RiskTier.SAFE_WRITE
    assert quit_spec is not None and quit_spec.base_tier == RiskTier.CONFIRM
    assert setting_spec is not None and setting_spec.base_tier == RiskTier.CONFIRM


def test_system_confirm_tiers_require_approval():
    policy = PolicyConfig()
    sandbox = Sandbox(policy)
    permissions = PermissionEngine(policy, sandbox)

    quit_spec = default_registry.get_spec("system.quit_app")
    call_quit = ToolCall(id="q1", name="system.quit_app", arguments={"app_name": "Safari"})
    dec_quit = permissions.decide(call_quit, quit_spec, TurnContext(turn_id="t1"))
    assert dec_quit.action == "ask"
    assert dec_quit.tier == RiskTier.CONFIRM

    setting_spec = default_registry.get_spec("system.change_setting")
    call_set = ToolCall(id="s1", name="system.change_setting", arguments={"setting_name": "dark_mode", "value": "on"})
    dec_set = permissions.decide(call_set, setting_spec, TurnContext(turn_id="t2"))
    assert dec_set.action == "ask"
    assert dec_set.tier == RiskTier.CONFIRM


@patch("subprocess.run")
def test_system_notify(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    res = notify(title="Test", message="Hello world")
    assert res.ok is True
    assert "Notification delivered" in res.content
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "osascript" in args[0]
    assert "display notification" in args[2]


@patch("subprocess.run")
def test_system_open_app(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    res = open_app(app_name="Safari")
    assert res.ok is True
    assert "Successfully opened application: Safari" in res.content
    mock_run.assert_called_once_with(["open", "-a", "Safari"], capture_output=True, text=True, check=True)


@patch("subprocess.run")
def test_system_clipboard_copy_and_paste(mock_run):
    # Test copy
    mock_run.return_value = MagicMock(returncode=0)
    res_copy = clipboard(action="copy", text="secret-note")
    assert res_copy.ok is True
    assert "Copied 11 characters" in res_copy.content

    # Test paste
    mock_run.return_value = MagicMock(returncode=0, stdout="pasted-content")
    res_paste = clipboard(action="paste")
    assert res_paste.ok is True
    assert "pasted-content" in res_paste.content


@patch("subprocess.run")
def test_system_quit_app(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    res = quit_app(app_name="Notes")
    assert res.ok is True
    assert "quit signal sent" in res.content
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_system_change_setting(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    res = change_setting(setting_name="dark_mode", value="on")
    assert res.ok is True
    assert "Dark Mode" in res.content

    res_vol = change_setting(setting_name="volume", value="50")
    assert res_vol.ok is True
    assert "50%" in res_vol.content
