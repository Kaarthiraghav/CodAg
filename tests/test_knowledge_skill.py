from pathlib import Path
from unittest.mock import MagicMock
from codag.config import PolicyConfig
from codag.memory.vectors import ChromaVectorStore
from codag.safety.sandbox import Sandbox
from codag.skills.knowledge.tools import ask_documents, configure_knowledge, index_folder


def test_knowledge_indexing_and_incremental(tmp_path: Path):
    doc_dir = tmp_path / "docs"
    doc_dir.mkdir()

    file1 = doc_dir / "guide.md"
    file1.write_text("# Installation Guide\nRun brew install codag to get started.", encoding="utf-8")
    file2 = doc_dir / "architecture.txt"
    file2.write_text("CodAg uses a deterministic Python core with Ollama LLM.", encoding="utf-8")
    secret_file = doc_dir / ".env"
    secret_file.write_text("SECRET_KEY=123", encoding="utf-8")

    policy = PolicyConfig()
    policy.workspace.roots = [str(tmp_path / "workspace")]
    policy.workspace.read_roots = [str(tmp_path)]
    policy.deny_paths.patterns = ["**/.env"]
    sandbox = Sandbox(policy)

    mock_ollama = MagicMock()
    mock_ollama.embeddings.return_value = {"embedding": [0.1, 0.2, 0.3]}
    vs = ChromaVectorStore(tmp_path / "vectors", ollama_client=mock_ollama)

    configure_knowledge(sandbox, vs)

    # 1. Index folder
    res = index_folder(str(doc_dir))
    assert res.ok is True
    assert "Successfully indexed 2 files" in res.content

    # 2. Re-indexing immediately skips unchanged files
    res2 = index_folder(str(doc_dir))
    assert res2.ok is True
    assert "Skipped 2 unchanged files" in res2.content

    # 3. Query documents
    q_res = ask_documents("How to install?")
    assert q_res.ok is True
    assert "guide.md" in q_res.content
    assert "[Reference:" in q_res.content
    # Since docs folder is outside workspace roots, content must be marked untrusted!
    assert q_res.untrusted is True
    assert "<untrusted source=" in q_res.content
