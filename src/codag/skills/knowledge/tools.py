"""Knowledge skill: document chunking, embedding, incremental hashing, and semantic search."""

import hashlib
from pathlib import Path
from typing import Any

from codag.core.types import RiskTier, ToolResult
from codag.memory.vectors import VectorStore
from codag.safety.sandbox import Sandbox, SandboxError
from codag.skills.base import tool
from codag.skills.registry import default_registry

SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".py", ".js", ".ts",
    ".json", ".yaml", ".yml", ".toml", ".csv", ".html",
}


def _compute_file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    chunks: list[str] = []
    text = text.strip()
    if not text:
        return []

    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += (chunk_size - overlap)
    return chunks


class KnowledgeEnvironment:
    def __init__(self, sandbox: Sandbox | None = None, vector_store: VectorStore | None = None) -> None:
        self.sandbox = sandbox
        self.vector_store = vector_store
        self.hash_cache: dict[str, str] = {}


_knowledge_env = KnowledgeEnvironment()


def configure_knowledge(sandbox: Sandbox, vector_store: VectorStore) -> None:
    global _knowledge_env
    _knowledge_env.sandbox = sandbox
    _knowledge_env.vector_store = vector_store


@tool(
    name="knowledge.index_folder",
    tier=RiskTier.SAFE_WRITE,
    description="Index a local directory of documents for semantic search, using incremental file hashes.",
)
def index_folder(path: str = ".") -> ToolResult:
    if not _knowledge_env.sandbox or not _knowledge_env.vector_store:
        return ToolResult(call_id="", ok=False, content="Knowledge environment not configured.")

    try:
        resolved = _knowledge_env.sandbox.check_read(path)
        if not resolved.is_dir():
            return ToolResult(call_id="", ok=False, content=f"Not a directory: {path}")

        indexed_files = 0
        total_chunks = 0
        skipped_unchanged = 0

        for file_path in resolved.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if _knowledge_env.sandbox.is_denied(file_path):
                continue

            file_str = str(file_path.resolve())
            current_hash = _compute_file_hash(file_path)

            # Incremental re-indexing check
            if _knowledge_env.hash_cache.get(file_str) == current_hash:
                skipped_unchanged += 1
                continue

            try:
                raw_text = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            chunks = _chunk_text(raw_text)
            in_workspace = _knowledge_env.sandbox.is_in_workspace(file_path)

            for idx, chunk in enumerate(chunks):
                doc_id = f"doc_{file_path.stem}_{idx}_{current_hash[:8]}"
                _knowledge_env.vector_store.upsert(
                    collection_name="documents",
                    doc_id=doc_id,
                    text=chunk,
                    metadata={
                        "file": file_str,
                        "file_name": file_path.name,
                        "chunk_index": idx,
                        "file_hash": current_hash,
                        "in_workspace": in_workspace,
                    },
                )
                total_chunks += 1

            _knowledge_env.hash_cache[file_str] = current_hash
            indexed_files += 1

        summary = (
            f"Successfully indexed {indexed_files} files ({total_chunks} chunks)."
        )
        if skipped_unchanged > 0:
            summary += f" Skipped {skipped_unchanged} unchanged files."

        return ToolResult(call_id="", ok=True, content=summary)
    except SandboxError as exc:
        return ToolResult(call_id="", ok=False, content=str(exc))
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Indexing error: {exc}")


@tool(
    name="knowledge.ask_documents",
    tier=RiskTier.READ,
    description="Retrieve relevant document passages with file and passage references for Q&A.",
)
def ask_documents(query: str, top_k: int = 4) -> ToolResult:
    if not _knowledge_env.vector_store:
        return ToolResult(call_id="", ok=False, content="Knowledge vector store not configured.")

    try:
        results = _knowledge_env.vector_store.query("documents", query, top_k=top_k)
        if not results:
            return ToolResult(
                call_id="",
                ok=True,
                content=f"No matching documents or passages found for query {query!r}.",
            )

        any_untrusted = False
        passages: list[str] = []

        for r in results:
            meta = r.get("metadata", {})
            file_name = meta.get("file_name", "document")
            file_path = meta.get("file", "")
            chunk_idx = meta.get("chunk_index", 0)
            in_ws = meta.get("in_workspace", True)

            # Untrusted if read from outside the workspace
            if not in_ws:
                any_untrusted = True

            passage_header = f"[Reference: {file_name} (passage #{chunk_idx}) - {file_path}]"
            passages.append(f"{passage_header}\n{r.get('text', '').strip()}\n")

        content = "\n---\n".join(passages)
        if any_untrusted:
            content = f"<untrusted source=\"external_documents\">\n{content}\n</untrusted>"

        return ToolResult(
            call_id="",
            ok=True,
            content=content,
            untrusted=any_untrusted,
        )
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Query error: {exc}")


default_registry.register(index_folder)
default_registry.register(ask_documents)
