"""Vector store interface wrapping ChromaDB with local embeddings."""

from abc import ABC, abstractmethod
import math
from pathlib import Path
from typing import Any
import ollama


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, collection_name: str, doc_id: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        """Store or update text embedding."""

    @abstractmethod
    def query(self, collection_name: str, query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve most similar documents."""

    @abstractmethod
    def delete(self, collection_name: str, doc_id: str) -> bool:
        """Remove document embedding."""


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


class ChromaVectorStore(VectorStore):
    def __init__(
        self,
        persist_dir: Path | str | None = None,
        embedding_model: str = "nomic-embed-text",
        ollama_client: ollama.Client | None = None,
    ) -> None:
        self.persist_dir = Path(persist_dir).expanduser() if persist_dir else Path.home() / ".codag" / "vectors"
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_model = embedding_model
        self.client = ollama_client or ollama.Client()

        # In-memory fallback index if chromadb cannot be loaded
        self._fallback_index: dict[str, dict[str, dict[str, Any]]] = {}

        self._chroma_client = None
        self._meta_file = self.persist_dir / "index_meta.json"
        self._check_and_handle_model_mismatch()

        try:
            import chromadb
            self._chroma_client = chromadb.PersistentClient(path=str(self.persist_dir))
        except Exception:
            self._chroma_client = None

    def _check_and_handle_model_mismatch(self) -> None:
        """Store embedding model name and dimension; rebuild/clear index on mismatch."""
        import json
        if self._meta_file.exists():
            try:
                data = json.loads(self._meta_file.read_text(encoding="utf-8"))
                stored_model = data.get("embedding_model")
                if stored_model and stored_model != self.embedding_model:
                    # Mismatch detected: clear chroma directory files to rebuild
                    for item in self.persist_dir.iterdir():
                        if item.is_file() and item != self._meta_file:
                            item.unlink(missing_ok=True)
            except Exception:
                pass

        try:
            self._meta_file.write_text(
                json.dumps({"embedding_model": self.embedding_model, "dimension": 768 if "nomic" in self.embedding_model else 1024}),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _get_embedding(self, text: str) -> list[float]:
        try:
            res = self.client.embeddings(model=self.embedding_model, prompt=text)
            return res.get("embedding", [])
        except Exception:
            return []

    def upsert(self, collection_name: str, doc_id: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        emb = self._get_embedding(text)
        meta = metadata or {}

        if self._chroma_client is not None:
            try:
                coll = self._chroma_client.get_or_create_collection(name=collection_name)
                coll.upsert(
                    ids=[doc_id],
                    documents=[text],
                    embeddings=[emb] if emb else None,
                    metadatas=[meta],
                )
                return
            except Exception:
                pass

        # Fallback index
        if collection_name not in self._fallback_index:
            self._fallback_index[collection_name] = {}
        self._fallback_index[collection_name][doc_id] = {
            "id": doc_id,
            "text": text,
            "embedding": emb,
            "metadata": meta,
        }

    def query(self, collection_name: str, query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
        emb = self._get_embedding(query_text)

        if self._chroma_client is not None:
            try:
                coll = self._chroma_client.get_or_create_collection(name=collection_name)
                res = coll.query(
                    query_embeddings=[emb] if emb else None,
                    query_texts=[query_text] if not emb else None,
                    n_results=top_k,
                )
                results = []
                ids = res.get("ids", [[]])[0]
                docs = res.get("documents", [[]])[0]
                metas = res.get("metadatas", [[]])[0]
                for d_id, doc, meta in zip(ids, docs, metas):
                    results.append({"id": d_id, "text": doc, "metadata": meta})
                return results
            except Exception:
                pass

        # Fallback query with cosine similarity
        coll_data = self._fallback_index.get(collection_name, {})
        if not coll_data:
            return []

        scored = []
        for d_id, item in coll_data.items():
            sim = _cosine_similarity(emb, item["embedding"]) if emb and item["embedding"] else 0.0
            scored.append((sim, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"id": it["id"], "text": it["text"], "metadata": it["metadata"]} for _, it in scored[:top_k]]

    def delete(self, collection_name: str, doc_id: str) -> bool:
        if self._chroma_client is not None:
            try:
                coll = self._chroma_client.get_or_create_collection(name=collection_name)
                coll.delete(ids=[doc_id])
                return True
            except Exception:
                pass

        if collection_name in self._fallback_index:
            if doc_id in self._fallback_index[collection_name]:
                del self._fallback_index[collection_name][doc_id]
                return True
        return False
