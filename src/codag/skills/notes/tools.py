"""Markdown notes skill."""

from datetime import datetime, timezone
from pathlib import Path
import re

from codag.core.types import RiskTier, ToolResult
from codag.skills.base import tool
from codag.skills.registry import default_registry


class NotesManager:
    def __init__(self, notes_dir: Path | str | None = None) -> None:
        base = Path(notes_dir).expanduser() if notes_dir else Path.home() / ".codag" / "notes"
        self.notes_dir = base
        self.notes_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, title: str) -> str:
        clean = re.sub(r"[^\w\s-]", "", title.strip().lower())
        clean = re.sub(r"[-\s]+", "_", clean)
        return clean or "untitled"

    def create(self, title: str, content: str) -> Path:
        name = self._sanitize_filename(title) + ".md"
        p = self.notes_dir / name
        header = f"# {title}\n\n"
        p.write_text(header + content, encoding="utf-8")
        return p

    def append(self, title: str, content: str) -> Path:
        name = self._sanitize_filename(title) + ".md"
        p = self.notes_dir / name
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        snippet = f"\n\n---\n*Added on {ts} UTC*\n{content}"
        if p.exists():
            with open(p, "a", encoding="utf-8") as f:
                f.write(snippet)
        else:
            p.write_text(f"# {title}\n{snippet}", encoding="utf-8")
        return p

    def search(self, query: str) -> list[tuple[str, str]]:
        results = []
        q_lower = query.lower()
        for f in sorted(self.notes_dir.glob("*.md")):
            text = f.read_text(encoding="utf-8", errors="replace")
            if q_lower in text.lower():
                snippet = text[:200].replace("\n", " ")
                results.append((f.stem, snippet))
        return results

    def list(self) -> list[str]:
        return [f.stem for f in sorted(self.notes_dir.glob("*.md"))]


_notes_mgr = NotesManager()


def configure_notes(notes_dir: Path | str) -> None:
    global _notes_mgr
    _notes_mgr = NotesManager(notes_dir)


@tool(
    name="notes.create_note",
    tier=RiskTier.SAFE_WRITE,
    description="Create a new markdown note with a title and content.",
)
def create_note(title: str, content: str) -> ToolResult:
    try:
        p = _notes_mgr.create(title, content)
        return ToolResult(call_id="", ok=True, content=f"Created note {p.name!r} in notes directory.")
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to create note: {exc}")


@tool(
    name="notes.append_note",
    tier=RiskTier.SAFE_WRITE,
    description="Append content to an existing note (or create it if it doesn't exist).",
)
def append_note(title: str, content: str) -> ToolResult:
    try:
        p = _notes_mgr.append(title, content)
        return ToolResult(call_id="", ok=True, content=f"Appended to note {p.name!r}.")
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to append note: {exc}")


@tool(
    name="notes.search_notes",
    tier=RiskTier.READ,
    description="Search through markdown notes for a query string.",
)
def search_notes(query: str) -> ToolResult:
    try:
        results = _notes_mgr.search(query)
        if not results:
            return ToolResult(call_id="", ok=True, content=f"No notes matching {query!r} found.")
        lines = [f"• {title}: {snip}..." for title, snip in results]
        return ToolResult(call_id="", ok=True, content="\n".join(lines))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Search failed: {exc}")


@tool(
    name="notes.list_notes",
    tier=RiskTier.READ,
    description="List all available markdown notes.",
)
def list_notes() -> ToolResult:
    try:
        titles = _notes_mgr.list()
        if not titles:
            return ToolResult(call_id="", ok=True, content="No notes found.")
        return ToolResult(call_id="", ok=True, content="\n".join(f"• {t}" for t in titles))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"List failed: {exc}")


default_registry.register(create_note)
default_registry.register(append_note)
default_registry.register(search_notes)
default_registry.register(list_notes)
