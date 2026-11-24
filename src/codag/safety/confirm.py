"""Confirmation UX for interactive terminal and adapters."""

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from codag.core.types import ToolCall

console = Console()


class ConfirmUX:
    def __init__(self, console_instance: Console | None = None) -> None:
        self.console = console_instance or console
        self._session_approved: set[str] = set()

    def request_approval(self, call: ToolCall, reason: str, tainted: bool = False) -> bool:
        """Prompt user for confirmation with action preview."""
        tool_key = f"{call.name}"
        if not tainted and tool_key in self._session_approved:
            return True

        title = f"[bold yellow]Confirmation Required: {call.name}[/bold yellow]"
        if tainted:
            title += " [bold red](TAINTED CONTEXT)[/bold red]"

        body_lines = [
            f"[bold]Reason:[/bold] {reason}",
            f"[bold]Arguments:[/bold]",
        ]
        for k, v in call.arguments.items():
            val_str = str(v)
            if len(val_str) > 200:
                val_str = val_str[:197] + "..."
            body_lines.append(f"  • [cyan]{k}[/cyan]: {val_str}")

        if tainted:
            body_lines.append("\n[red]Warning: Untrusted content (web/external file) is present in this turn.[/red]")

        self.console.print(Panel("\n".join(body_lines), title=title, border_style="yellow"))

        prompt_text = "[y] approve, [n] reject, [a] always allow this tool for session"
        choice = Prompt.ask(prompt_text, choices=["y", "n", "a"], default="n").strip().lower()

        if choice == "y":
            return True
        elif choice == "a" and not tainted:
            self._session_approved.add(tool_key)
            return True
        return False
