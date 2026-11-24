from pathlib import Path
from codag.core.types import RiskTier
from codag.memory.retrieve import configure_memory, forget, recall, remember
from codag.memory.store import MemoryStore
from codag.skills.registry import default_registry


def test_memory_tools_lifecycle(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.db")
    configure_memory(store)

    # 1. remember tool
    rem_res = remember(key="language", value="Python 3.12", category="preference")
    assert rem_res.ok is True
    assert "Remembered fact" in rem_res.content

    # Verify sensitive data rejection
    bad_res = remember(key="secret_token", value="sk-abcdef1234567890abcdef1234")
    assert bad_res.ok is False
    assert "Cannot store sensitive" in bad_res.content

    # 2. recall tool
    rec_res = recall(query="language")
    assert rec_res.ok is True
    assert "Python 3.12" in rec_res.content

    # 3. forget tool has CONFIRM tier in registry
    forget_spec = default_registry.get_spec("memory.forget")
    assert forget_spec is not None
    assert forget_spec.base_tier == RiskTier.CONFIRM

    # 4. forget execution
    forg_res = forget("language")
    assert forg_res.ok is True
    assert "Permanently forgot" in forg_res.content
    assert store.get_fact_by_key("language") is None
