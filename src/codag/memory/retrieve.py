"""Memory retrieval, ranking, context formatting, and memory tools."""

from codag.core.types import RiskTier, ToolResult
from codag.memory.extract import is_sensitive
from codag.memory.store import MemoryStore
from codag.memory.vectors import VectorStore
from codag.skills.base import tool
from codag.skills.registry import default_registry

_memory_store: MemoryStore | None = None
_vector_store: VectorStore | None = None


def configure_memory(store: MemoryStore, vector_store: VectorStore | None = None) -> None:
    global _memory_store, _vector_store
    _memory_store = store
    _vector_store = vector_store


def retrieve_relevant_facts(query: str, limit: int = 5) -> list[dict]:
    """Retrieve facts combining recency and semantic similarity."""
    if not _memory_store:
        return []

    # Start with most recent active facts
    facts = _memory_store.list_facts(limit=limit * 2)
    if not facts:
        return []

    if _vector_store:
        try:
            vec_res = _vector_store.query("facts", query, top_k=limit)
            matched_keys = {item["metadata"].get("key") for item in vec_res if "key" in item["metadata"]}
            # Put semantic matches first
            facts.sort(key=lambda f: f["key"] in matched_keys, reverse=True)
        except Exception:
            pass

    return facts[:limit]


def format_memory_context(facts: list[dict], budget_chars: int = 2000) -> str:
    """Format facts into a delimited background block within token budget."""
    if not facts:
        return ""

    lines = ["<background_about_user>"]
    total_len = len(lines[0])
    for f in facts:
        line = f"- {f['value']}"
        if total_len + len(line) + 30 > budget_chars:
            break
        lines.append(line)
        total_len += len(line) + 1
    lines.append("</background_about_user>")

    return "\n".join(lines)


# --- Core Memory Tools (Declared with @tool decorator) ---

@tool(
    name="memory.remember",
    tier=RiskTier.SAFE_WRITE,
    description="Remember a durable fact about the user (e.g. key='editor', value='uses VS Code').",
)
def remember(key: str, value: str, category: str = "general") -> ToolResult:
    if not _memory_store:
        return ToolResult(call_id="", ok=False, content="Memory store not configured.")

    if is_sensitive(key) or is_sensitive(value):
        return ToolResult(call_id="", ok=False, content="Cannot store sensitive information such as credentials or secrets.")

    try:
        fact_id = _memory_store.add_or_update_fact(key, value, category)
        if _vector_store:
            _vector_store.upsert("facts", f"fact_{fact_id}", f"{key}: {value}", metadata={"key": key, "category": category})
        return ToolResult(call_id="", ok=True, content=f"Remembered fact #{fact_id}: {key} -> {value}")
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to store fact: {exc}")


@tool(
    name="memory.recall",
    tier=RiskTier.READ,
    description="Recall stored facts relevant to a query.",
)
def recall(query: str) -> ToolResult:
    if not _memory_store:
        return ToolResult(call_id="", ok=False, content="Memory store not configured.")
    try:
        facts = retrieve_relevant_facts(query, limit=5)
        if not facts:
            return ToolResult(call_id="", ok=True, content="No relevant facts found in memory.")
        lines = [f"• [{f['category']}] {f['key']}: {f['value']}" for f in facts]
        return ToolResult(call_id="", ok=True, content="\n".join(lines))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to recall facts: {exc}")


@tool(
    name="memory.forget",
    tier=RiskTier.CONFIRM,
    description="Permanently delete a remembered fact by its ID or key (requires confirmation).",
)
def forget(identifier: str) -> ToolResult:
    if not _memory_store:
        return ToolResult(call_id="", ok=False, content="Memory store not configured.")
    try:
        deleted = _memory_store.delete_fact(identifier)
        if deleted:
            if _vector_store:
                _vector_store.delete("facts", f"fact_{identifier}")
            return ToolResult(call_id="", ok=True, content=f"Permanently forgot fact {identifier!r}.")
        return ToolResult(call_id="", ok=False, content=f"Fact {identifier!r} not found in memory.")
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to forget fact: {exc}")


default_registry.register(remember)
default_registry.register(recall)
default_registry.register(forget)
