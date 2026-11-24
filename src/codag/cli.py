"""CLI commands for CodAg (chat, ask, doctor, audit, undo)."""

from pathlib import Path
import re
import shutil
import subprocess
import sys
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
import typer

from codag.config import load_config
from codag.core.agent import Agent
from codag.safety.audit import AuditLogger
from codag.safety.snapshots import SnapshotManager

app = typer.Typer(help="CodAg: Local personal AI assistant")
console = Console()


@app.command()
def doctor(config_dir: str = "config") -> None:
    """Check Python version, git, Ollama connectivity, models, and configuration."""
    cfg = load_config(config_dir)
    table = Table(title="CodAg Doctor Checkup")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details")

    all_passed = True

    # 1. Python version (3.12 required for runtime)
    py_ver = sys.version_info
    py_str = f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"
    if py_ver.major == 3 and py_ver.minor == 12:
        table.add_row("Python Runtime", "[green]OK[/green]", f"Python {py_str}")
    else:
        table.add_row("Python Runtime", "[yellow]WARNING[/yellow]", f"Found {py_str}, recommend 3.12")

    # 2. Git
    git_bin = shutil.which("git")
    if git_bin:
        table.add_row("Git", "[green]OK[/green]", git_bin)
    else:
        table.add_row("Git", "[red]MISSING[/red]", "git executable not found in PATH")
        all_passed = False

    # 3. uv package manager
    uv_bin = shutil.which("uv")
    if uv_bin:
        table.add_row("uv Package Manager", "[green]OK[/green]", uv_bin)
    else:
        table.add_row("uv Package Manager", "[yellow]NOT FOUND[/yellow]", "Install uv for fast virtualenv & package management")

    # 4. Data directory
    data_path = cfg.paths.resolved_data_dir
    try:
        data_path.mkdir(parents=True, exist_ok=True)
        table.add_row("Data Directory", "[green]OK[/green]", str(data_path))
    except Exception as exc:
        table.add_row("Data Directory", "[red]ERROR[/red]", f"{data_path}: {exc}")
        all_passed = False

    # 4. Ollama service & models
    import ollama

    client = ollama.Client(host=cfg.ollama.host)
    try:
        available = client.list()
        table.add_row("Ollama Service", "[green]OK[/green]", f"Reachable at {cfg.ollama.host}")

        models_list: list[str] = []
        if hasattr(available, "models") and available.models:
            for m in available.models:
                name = getattr(m, "model", None) or getattr(m, "name", "")
                models_list.append(name)
        elif isinstance(available, dict) and "models" in available:
            models_list = [m.get("name") or m.get("model", "") for m in available["models"]]

        def has_model(target: str) -> bool:
            return any(target in m or m.startswith(target) for m in models_list)

        check_targets = [
            ("Main Model", cfg.models.main),
            ("Embedding Model", cfg.models.embedding),
            ("Coder Model", cfg.models.coder),
        ]
        for role_name, target_model in check_targets:
            if has_model(target_model):
                table.add_row(role_name, "[green]OK[/green]", f"Found {target_model}")
            else:
                table.add_row(role_name, "[yellow]NOT PULLED[/yellow]", f"Run `ollama pull {target_model}`")
    except Exception as exc:
        table.add_row("Ollama Service", "[red]ERROR[/red]", f"Cannot connect: {exc}")
        all_passed = False

    console.print(table)
    if not all_passed:
        raise typer.Exit(code=1)


@app.command()
def ask(question: str, config_dir: str = "config") -> None:
    """Ask a single question or command using the agent turn pipeline."""
    cfg = load_config(config_dir)
    agent = Agent(cfg)

    full_output = []
    for chunk in agent.run_turn(question):
        console.print(chunk, end="")
        full_output.append(chunk)
    console.print()

    # Open PDF automatically if generated
    full_text = "".join(full_output)
    if "Successfully generated PDF document at '" in full_text:
        match = re.search(r"Successfully generated PDF document at '([^']+)'", full_text)
        if match:
            pdf_path = Path(match.group(1))
            if pdf_path.exists():
                subprocess.run(["open", str(pdf_path)], check=False)


@app.command()
def chat(
    session: str = typer.Argument(None, help="Session name or ID to resume or create"),
    project: str = typer.Option(None, "--project", "-p", help="Bind session to a project directory"),
    config_dir: str = "config",
) -> None:
    """Interactive multi-turn terminal chat with tools, safety gates, and slash commands."""
    import sqlite3
    cfg = load_config(config_dir)
    agent = Agent(cfg)

    # Auto-detect project if user is inside a specific directory and didn't specify one
    if not project and not session:
        cwd = Path.cwd().resolve()
        home = Path.home().resolve()
        if cwd != home:
            project = str(cwd)

    session_obj = agent.chat_manager.get_or_create_session(session, project_path=project)

    def print_banner(sess):
        proj_info = f" | Project: {sess.project_path}" if sess.project_path else ""
        console.print(Panel(
            f"[bold green]CodAg Assistant[/bold green] [cyan][{sess.title}{proj_info}][/cyan]\n"
            "[dim]Commands: /help, /chats, /switch <name>, /project [path], /pdf [title], /undo, /clear, /exit[/dim]",
            border_style="green",
        ))

    print_banner(session_obj)
    last_assistant_response = ""

    while True:
        try:
            user_input = console.input("\n[bold cyan]You>[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\nExiting.")
            break

        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in {"/exit", "/quit"}:
                console.print("[dim]Goodbye.[/dim]")
                break

            if cmd == "/help":
                console.print(Panel(
                    "[bold]Available In-Chat Commands:[/bold]\n"
                    "  [cyan]/chats[/cyan]              List all saved chat sessions\n"
                    "  [cyan]/switch <name|id>[/cyan]    Switch to another chat session\n"
                    "  [cyan]/new <title>[/cyan]         Create and switch to a new chat session\n"
                    "  [cyan]/project [path][/cyan]      View or change the active project workspace\n"
                    "  [cyan]/pdf [title][/cyan]          Export the last response as a PDF and open it in Preview\n"
                    "  [cyan]/undo[/cyan]               Undo the last file modification or restore deleted file\n"
                    "  [cyan]/clear[/cyan]              Clear the terminal screen\n"
                    "  [cyan]/exit[/cyan] or [cyan]/quit[/cyan]      Exit chat",
                    title="CodAg In-Chat Commands",
                    border_style="blue",
                ))
                continue

            if cmd == "/clear":
                console.clear()
                print_banner(session_obj)
                continue

            if cmd == "/chats":
                sessions = agent.chat_manager.list_sessions()
                table = Table(title=f"Chat Sessions ({len(sessions)})")
                table.add_column("ID", style="cyan")
                table.add_column("Title", style="bold")
                table.add_column("Project", style="green")
                table.add_column("Msgs", justify="right")
                table.add_column("Active")
                for s in sessions:
                    is_active = "[green]* (current)[/green]" if s.id == session_obj.id else ""
                    table.add_row(s.id, s.title, s.project_path or "-", str(s.message_count), is_active)
                console.print(table)
                continue

            if cmd == "/switch":
                if not arg:
                    console.print("[yellow]Usage: /switch <session_name_or_id>[/yellow]")
                    continue
                target = agent.chat_manager.get_session(arg)
                if target:
                    session_obj = target
                    console.print(f"[green]Switched to session '{session_obj.title}'[/green]")
                    print_banner(session_obj)
                else:
                    console.print(f"[red]Session '{arg}' not found.[/red]")
                continue

            if cmd == "/new":
                if not arg:
                    console.print("[yellow]Usage: /new <title>[/yellow]")
                    continue
                session_obj = agent.chat_manager.create_session(title=arg, project_path=session_obj.project_path)
                console.print(f"[green]Created and switched to new session '{session_obj.title}'[/green]")
                print_banner(session_obj)
                continue

            if cmd == "/project":
                if arg:
                    p = Path(arg).expanduser().resolve()
                    if p.is_dir():
                        session_obj.project_path = str(p)
                        with sqlite3.connect(agent.chat_manager.db_path) as conn:
                            conn.execute("UPDATE sessions SET project_path = ? WHERE id = ?", (str(p), session_obj.id))
                            conn.commit()
                        console.print(f"[green]Updated active project to: {p}[/green]")
                    else:
                        console.print(f"[red]Directory not found: {arg}[/red]")
                else:
                    console.print(f"Active project: [cyan]{session_obj.project_path or 'None (Global)'}[/cyan]")
                continue

            if cmd == "/undo":
                success, msg = agent.snapshots.undo()
                if success:
                    console.print(f"[green]{msg}[/green]")
                else:
                    console.print(f"[red]{msg}[/red]")
                continue

            if cmd == "/pdf":
                if not last_assistant_response:
                    console.print("[yellow]No response available to export yet.[/yellow]")
                    continue
                title = arg or f"{session_obj.title} Notes"
                from codag.skills.files.tools import generate_pdf_from_markdown
                out_dir = Path(session_obj.project_path) if session_obj.project_path else agent.config.paths.resolved_data_dir / "exports"
                out_dir.mkdir(parents=True, exist_ok=True)
                clean_name = re.sub(r"[^\w\-_\. ]", "_", title).strip().replace(" ", "_")
                out_pdf = out_dir / f"{clean_name}.pdf"
                try:
                    generate_pdf_from_markdown(out_pdf, title, last_assistant_response)
                    console.print(f"[green]Created PDF: {out_pdf}[/green]")
                    subprocess.run(["open", str(out_pdf)], check=False)
                except Exception as exc:
                    console.print(f"[red]Failed to create PDF: {exc}[/red]")
                continue

            console.print(f"[yellow]Unknown command '{cmd}'. Type /help for available commands.[/yellow]")
            continue

        turn_chunks: list[str] = []
        console.print("[bold green]CodAg>[/bold green] ", end="")
        try:
            for chunk in agent.run_turn(user_input, session_id=session_obj.id):
                console.print(chunk, end="")
                turn_chunks.append(chunk)
            console.print()

            full_resp = "".join(turn_chunks)
            if full_resp:
                last_assistant_response = full_resp

            # If a PDF was generated during the turn, open it automatically in macOS Preview
            if "Successfully generated PDF document at '" in full_resp:
                match = re.search(r"Successfully generated PDF document at '([^']+)'", full_resp)
                if match:
                    pdf_file = Path(match.group(1))
                    if pdf_file.exists():
                        console.print(f"[dim]Opening {pdf_file.name} in macOS Preview...[/dim]")
                        subprocess.run(["open", str(pdf_file)], check=False)

        except Exception as exc:
            console.print(f"\n[red]Error: {exc}[/red]")


@app.command()
def audit(limit: int = 20, config_dir: str = "config") -> None:
    """Display recent audit log entries."""
    cfg = load_config(config_dir)
    audit_logger = AuditLogger(cfg.paths.resolved_data_dir)
    entries = audit_logger.list_entries(limit=limit)

    table = Table(title=f"Recent Audit Entries (last {len(entries)})")
    table.add_column("Timestamp", style="dim")
    table.add_column("Tool", style="cyan")
    table.add_column("Decision", style="bold")
    table.add_column("Approved")
    table.add_column("OK")
    table.add_column("Details")
    table.add_column("Undo Token")

    for e in entries:
        appr_str = "-" if e.user_approved is None else ("[green]Yes[/green]" if e.user_approved else "[red]No[/red]")
        ok_str = "-" if e.ok is None else ("[green]Yes[/green]" if e.ok else "[red]No[/red]")
        dec_color = "green" if e.decision == "allow" else ("yellow" if e.decision == "ask" else "red")
        dec_str = f"[{dec_color}]{e.decision.upper()}[/{dec_color}]"

        summary = e.result_summary or str(e.arguments)
        if len(summary) > 60:
            summary = summary[:57] + "..."

        table.add_row(
            e.ts.split("T")[1][:8],
            e.tool,
            dec_str,
            appr_str,
            ok_str,
            summary,
            e.undo_token or "-",
        )

    console.print(table)


@app.command()
def undo(token: str = typer.Argument(None, help="Undo token (optional, defaults to last action)"), config_dir: str = "config") -> None:
    """Reverse a previous file change or restore a deleted file."""
    cfg = load_config(config_dir)
    snapshots = SnapshotManager(cfg.paths.resolved_data_dir)
    success, msg = snapshots.undo(token)
    if success:
        console.print(f"[green]{msg}[/green]")
    else:
        console.print(f"[red]{msg}[/red]")
        raise typer.Exit(code=1)


@app.command("eval")
def run_eval(suite: str = "all", config_dir: str = "config") -> None:
    """Run evaluation suites (router, safety, scenarios, all)."""
    # Ensure current working directory is in sys.path
    if "." not in sys.path and "" not in sys.path:
        sys.path.insert(0, str(Path.cwd()))
    from evals.run_evals import run_all_evals
    try:
        run_all_evals(config_dir=config_dir, suite=suite)
    except SystemExit as exc:
        if exc.code != 0:
            raise typer.Exit(code=exc.code)


memory_app = typer.Typer(help="Manage durable facts in agent memory")
app.add_typer(memory_app, name="memory")


@memory_app.command("list")
def memory_list(category: str = typer.Option(None, help="Filter by category"), config_dir: str = "config") -> None:
    """List stored facts."""
    from codag.memory.store import MemoryStore
    cfg = load_config(config_dir)
    store = MemoryStore(cfg.paths.resolved_data_dir / "memory.db")
    facts = store.list_facts(category=category)

    table = Table(title=f"Stored Facts ({len(facts)})")
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_column("Category", style="green")
    table.add_column("Updated", style="dim")

    for f in facts:
        table.add_row(
            str(f["id"]),
            f["key"],
            f["value"],
            f["category"],
            f["updated_at"].split("T")[0] if "T" in f["updated_at"] else f["updated_at"],
        )

    console.print(table)


@memory_app.command("forget")
def memory_forget(identifier: str = typer.Argument(..., help="Fact ID or key to permanently delete"), config_dir: str = "config") -> None:
    """Permanently delete a remembered fact."""
    from codag.memory.store import MemoryStore
    from codag.memory.vectors import ChromaVectorStore
    cfg = load_config(config_dir)
    store = MemoryStore(cfg.paths.resolved_data_dir / "memory.db")
    vectors = ChromaVectorStore(cfg.paths.resolved_data_dir / "vectors", embedding_model=cfg.models.embedding)

    deleted = store.delete_fact(identifier)
    if deleted:
        vectors.delete("facts", f"fact_{identifier}")
        console.print(f"[green]Permanently forgot fact {identifier!r}.[/green]")
    else:
        console.print(f"[red]Fact {identifier!r} not found in memory.[/red]")
        raise typer.Exit(code=1)


@memory_app.command("export")
def memory_export(format: str = typer.Option("json", help="Export format: json or markdown"), config_dir: str = "config") -> None:
    """Export all stored facts."""
    import json
    from codag.memory.store import MemoryStore
    cfg = load_config(config_dir)
    store = MemoryStore(cfg.paths.resolved_data_dir / "memory.db")
    facts = store.export_facts()

    if format.lower() == "markdown":
        console.print("# CodAg Memory Facts\n")
        for f in facts:
            console.print(f"- **{f['key']}** ({f['category']}): {f['value']}")
    else:
        console.print(json.dumps(facts, indent=2))


chats_app = typer.Typer(help="Manage multi-project chat sessions")
app.add_typer(chats_app, name="chats")


@chats_app.command("list")
def chats_list(config_dir: str = "config") -> None:
    """List all chat sessions."""
    from codag.core.chats import ChatManager
    cfg = load_config(config_dir)
    manager = ChatManager(cfg.paths.resolved_data_dir / "chats.db")
    sessions = manager.list_sessions()

    table = Table(title=f"Chat Sessions ({len(sessions)})")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="bold")
    table.add_column("Project Path", style="green")
    table.add_column("Messages", justify="right")
    table.add_column("Updated", style="dim")

    for s in sessions:
        proj = s.project_path or "-"
        table.add_row(
            s.id,
            s.title,
            proj,
            str(s.message_count),
            s.updated_at.split("T")[0] if "T" in s.updated_at else s.updated_at,
        )

    console.print(table)


@chats_app.command("new")
def chats_new(
    title: str = typer.Argument(..., help="Session title"),
    project: str = typer.Option(None, "--project", "-p", help="Target project workspace directory"),
    config_dir: str = "config",
) -> None:
    """Create a new chat session."""
    from codag.core.chats import ChatManager
    cfg = load_config(config_dir)
    manager = ChatManager(cfg.paths.resolved_data_dir / "chats.db")
    session = manager.create_session(title=title, project_path=project)
    proj_msg = f" linked to project '{session.project_path}'" if session.project_path else ""
    console.print(f"[green]Created chat session '{session.title}' ({session.id}){proj_msg}[/green]")


@chats_app.command("delete")
def chats_delete(
    session_id: str = typer.Argument(..., help="Session ID to delete"),
    config_dir: str = "config",
) -> None:
    """Delete a chat session and its history."""
    from codag.core.chats import ChatManager
    cfg = load_config(config_dir)
    manager = ChatManager(cfg.paths.resolved_data_dir / "chats.db")
    deleted = manager.delete_session(session_id)
    if deleted:
        console.print(f"[green]Deleted chat session '{session_id}'.[/green]")
    else:
        console.print(f"[red]Chat session '{session_id}' not found.[/red]")
        raise typer.Exit(code=1)


@chats_app.command("show")
def chats_show(
    session_id: str = typer.Argument(..., help="Session ID to view"),
    limit: int = typer.Option(20, help="Number of messages to display"),
    config_dir: str = "config",
) -> None:
    """Display recent transcript for a session."""
    from codag.core.chats import ChatManager
    cfg = load_config(config_dir)
    manager = ChatManager(cfg.paths.resolved_data_dir / "chats.db")
    session = manager.get_session(session_id)
    if not session:
        console.print(f"[red]Chat session '{session_id}' not found.[/red]")
        raise typer.Exit(code=1)

    proj_msg = f" (Project: {session.project_path})" if session.project_path else ""
    console.print(f"[bold cyan]Transcript: {session.title}{proj_msg}[/bold cyan]\n")
    messages = manager.get_messages(session.id, limit=limit)
    for m in messages:
        role = m["role"]
        color = "cyan" if role == "user" else "green"
        console.print(f"[{color}][bold]{role.capitalize()}:[/bold] {m['content']}[/{color}]\n")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
