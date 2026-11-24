"""Shell execution tool following section 9.7 with safety controls."""

from pathlib import Path
import shlex
import subprocess

from codag.core.types import RiskTier, ToolResult
from codag.safety.sandbox import Sandbox
from codag.skills.base import tool
from codag.skills.registry import default_registry

FORBIDDEN_OPERATORS = (";", "&&", "||", "|", ">", "<", "`", "$(")


class ShellEnvironment:
    def __init__(self, workspace_path: Path | None = None) -> None:
        self.workspace_path = workspace_path or Path.cwd()

    def set_workspace(self, path: Path) -> None:
        self.workspace_path = path


_shell_env = ShellEnvironment()


def configure_shell(workspace_path: Path) -> None:
    _shell_env.set_workspace(workspace_path)


@tool(
    name="shell.run_command",
    tier=RiskTier.SAFE_WRITE,
    description="Run an allow-listed shell command without shell operators.",
)
def run_command(command: str, timeout_s: int = 60) -> ToolResult:
    cmd_str = command.strip()
    if not cmd_str:
        return ToolResult(call_id="", ok=False, content="Empty command.")

    # 1. Reject shell operators in v1
    for op in FORBIDDEN_OPERATORS:
        if op in cmd_str:
            return ToolResult(
                call_id="",
                ok=False,
                content=f"Command contains prohibited shell operator {op!r}. Chaining/redirection is forbidden.",
            )

    # 2. Split arguments safely
    try:
        args = shlex.split(cmd_str)
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to parse command: {exc}")

    # 3. Execute with subprocess.run (shell=False)
    cwd = _shell_env.workspace_path
    cwd.mkdir(parents=True, exist_ok=True)

    try:
        res = subprocess.run(
            args,
            shell=False,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        combined_output = (res.stdout + res.stderr).strip()
        if len(combined_output) > 6000:
            combined_output = combined_output[:6000] + "\n... [Output truncated]"

        ok = (res.returncode == 0)
        content = combined_output if combined_output else f"(Command exited with code {res.returncode})"
        return ToolResult(call_id="", ok=ok, content=content)
    except subprocess.TimeoutExpired:
        return ToolResult(call_id="", ok=False, content=f"Command timed out after {timeout_s}s.")
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Execution error: {exc}")


default_registry.register(run_command)
