from pathlib import Path
from unittest.mock import MagicMock
from codag.memory.vectors import ChromaVectorStore


def test_vector_store_operations(tmp_path: Path):
    mock_ollama = MagicMock()
    # Mock embedding returns 3-dim vectors
    mock_ollama.embeddings.side_effect = lambda model, prompt: {
        "embedding": [0.1, 0.2, 0.3] if "editor" in prompt else [0.9, 0.1, 0.0]
    }

    vs = ChromaVectorStore(tmp_path / "vectors", ollama_client=mock_ollama)

    vs.upsert("facts", "fact_1", "editor: VS Code", metadata={"key": "editor"})
    vs.upsert("facts", "fact_2", "os: macOS", metadata={"key": "os"})

    # Query
    results = vs.query("facts", "what editor do I use?", top_k=1)
    assert len(results) >= 1
    assert "fact_1" in [r["id"] for r in results]

    # Delete
    del_ok = vs.delete("facts", "fact_1")
    assert del_ok is True
