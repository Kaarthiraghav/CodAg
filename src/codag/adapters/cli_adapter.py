"""CLI interface adapter implementing InputAdapter and OutputAdapter."""

from typing import Any, Generator
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from codag.adapters.base import InputAdapter, OutputAdapter
from codag.core.types import AgentEvent

console = Console()


class CLIInputAdapter(InputAdapter):
    """Read interactive user input from the terminal."""

    def __init__(self, console_instance: Console | None = None) -> None:
        self.console = console_instance or console

    def events(self) -> Generator[dict[str, Any], None, None]:
        while True:
            try:
                line = Prompt.ask("\n[bold cyan]You[/bold cyan]").strip()
                if not line:
                    continue
                if line.lower() in ("exit", "quit"):
                    break
                yield {"type": "user_message", "content": line}
            except (KeyboardInterrupt, EOFError):
                break


class CLIOutputAdapter(OutputAdapter):
    """Render agent events in rich terminal format."""

    def __init__(self, console_instance: Console | None = None) -> None:
        self.console = console_instance or console

    def emit(self, event: AgentEvent) -> None:
        etype = event.event_type
        payload = event.payload

        if etype == "text_delta":
            text = payload.get("text", "")
            self.console.print(text, end="")
        elif etype == "tool_started":
            tool_name = payload.get("tool", "")
            self.console.print(f"\n[cyan]Executing {tool_name}...[/cyan]")
        elif etype == "tool_finished":
            ok = payload.get("ok", True)
            status_tag = "[green]Done[/green]" if ok else "[red]Failed[/red]"
            self.console.print(f"[{status_tag}] {payload.get('tool', '')}")
        elif etype == "confirmation_requested":
            tool_name = payload.get("tool", "")
            reason = payload.get("reason", "")
            args = payload.get("arguments", {})
            body = [f"[bold]Reason:[/bold] {reason}", "[bold]Arguments:[/bold]"]
            for k, v in args.items():
                body.append(f"  • {k}: {v}")
            panel = Panel("\n".join(body), title=f"[bold yellow]Approval Needed: {tool_name}[/bold yellow]", border_style="yellow")
            self.console.print(panel)
        elif etype == "turn_finished":
            self.console.print()
        elif etype == "error":
            err = payload.get("error", "")
            self.console.print(f"\n[bold red]Error:[/bold red] {err}")
