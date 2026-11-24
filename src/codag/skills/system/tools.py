"""System skill: macOS actions (notifications, clipboard, apps, settings)."""

import json
from pathlib import Path
import subprocess
from typing import Any

from codag.core.types import RiskTier, ToolResult
from codag.skills.base import tool
from codag.skills.registry import default_registry


def _escape_applescript_string(s: str) -> str:
    """Escape backslashes and double quotes for AppleScript string literals."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


@tool(
    name="system.notify",
    tier=RiskTier.SAFE_WRITE,
    description="Display a native macOS desktop notification via osascript.",
)
def notify(title: str, message: str) -> ToolResult:
    """Send a native macOS notification."""
    safe_title = _escape_applescript_string(title)
    safe_msg = _escape_applescript_string(message)
    script = f'display notification "{safe_msg}" with title "{safe_title}"'
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return ToolResult(
            call_id="",
            ok=True,
            content=f"Notification delivered: '{title}' - '{message}'",
        )
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to display notification: {exc}")


@tool(
    name="system.open_app",
    tier=RiskTier.SAFE_WRITE,
    description="Launch or bring a macOS application to the front (e.g. Safari, Notes, Terminal).",
)
def open_app(app_name: str) -> ToolResult:
    """Open an application using macOS `open -a`."""
    try:
        proc = subprocess.run(
            ["open", "-a", app_name],
            capture_output=True,
            text=True,
            check=True,
        )
        return ToolResult(
            call_id="",
            ok=True,
            content=f"Successfully opened application: {app_name}",
        )
    except subprocess.CalledProcessError as cpe:
        return ToolResult(
            call_id="",
            ok=False,
            content=f"Could not open application '{app_name}': {cpe.stderr or cpe.stdout or 'Application not found'}",
        )
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Error launching application: {exc}")


@tool(
    name="system.clipboard",
    tier=RiskTier.SAFE_WRITE,
    description="Interact with the macOS clipboard (action: 'copy' with text, or 'paste'/'get' to read).",
)
def clipboard(action: str = "get", text: str = "") -> ToolResult:
    """Read or set the system clipboard using pbcopy and pbpaste."""
    action_lower = action.lower().strip()
    try:
        if action_lower in ("set", "copy", "write"):
            proc = subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                check=True,
            )
            return ToolResult(
                call_id="",
                ok=True,
                content=f"Copied {len(text)} characters to clipboard.",
            )
        elif action_lower in ("get", "paste", "read"):
            proc = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                check=True,
            )
            content = proc.stdout
            preview = content[:200] + ("..." if len(content) > 200 else "")
            return ToolResult(
                call_id="",
                ok=True,
                content=f"Clipboard content ({len(content)} chars):\n{preview}",
            )
        else:
            return ToolResult(
                call_id="",
                ok=False,
                content=f"Unknown clipboard action '{action}'. Use 'copy' or 'paste'.",
            )
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Clipboard operation failed: {exc}")


@tool(
    name="system.quit_app",
    tier=RiskTier.CONFIRM,
    description="Gracefully quit a running macOS application (CONFIRM tier).",
)
def quit_app(app_name: str) -> ToolResult:
    """Quit a macOS application via osascript."""
    safe_name = _escape_applescript_string(app_name)
    script = f'tell application "{safe_name}" to quit'
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return ToolResult(
            call_id="",
            ok=True,
            content=f"Application '{app_name}' quit signal sent.",
        )
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to quit application '{app_name}': {exc}")


@tool(
    name="system.change_setting",
    tier=RiskTier.CONFIRM,
    description="Change a macOS system preference such as 'dark_mode' or 'volume' (CONFIRM tier).",
)
def change_setting(setting_name: str, value: str) -> ToolResult:
    """Change a system setting (dark_mode, volume)."""
    name_lower = setting_name.lower().strip().replace(" ", "_")
    val_lower = value.lower().strip()

    try:
        if name_lower in ("dark_mode", "appearance"):
            enable_dark = val_lower in ("on", "true", "yes", "1", "dark")
            flag_str = "true" if enable_dark else "false"
            script = f'tell application "System Events" to tell appearance preferences to set dark mode to {flag_str}'
            subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True)
            mode_desc = "Dark Mode" if enable_dark else "Light Mode"
            return ToolResult(call_id="", ok=True, content=f"System appearance set to {mode_desc}.")

        elif name_lower in ("volume", "sound_volume", "audio"):
            vol_int = max(0, min(100, int(val_lower.rstrip("%"))))
            script = f"set volume output volume {vol_int}"
            subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True)
            return ToolResult(call_id="", ok=True, content=f"System output volume set to {vol_int}%.")

        else:
            return ToolResult(
                call_id="",
                ok=False,
                content=f"Unsupported setting '{setting_name}'. Supported settings: 'dark_mode' (on/off), 'volume' (0-100).",
            )
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to change setting '{setting_name}': {exc}")


# Auto-register system tools
default_registry.register(notify)
default_registry.register(open_app)
default_registry.register(clipboard)
default_registry.register(quit_app)
default_registry.register(change_setting)
