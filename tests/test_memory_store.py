from pathlib import Path
from codag.memory.store import MemoryStore


def test_memory_store_facts(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.db")

    # 1. Add fact
    fid = store.add_or_update_fact("editor", "VS Code", "preference")
    assert fid > 0

    # 2. Get fact
    fact = store.get_fact(fid)
    assert fact is not None
    assert fact["key"] == "editor"
    assert fact["value"] == "VS Code"

    # 3. Update existing fact
    store.add_or_update_fact("editor", "Cursor", "preference")
    updated = store.get_fact_by_key("editor")
    assert updated["value"] == "Cursor"

    # 4. List facts
    facts = store.list_facts()
    assert len(facts) == 1
    assert facts[0]["key"] == "editor"

    # 5. Delete fact (hard delete per spec 8.3)
    deleted = store.delete_fact("editor")
    assert deleted is True
    assert store.get_fact_by_key("editor") is None
    assert len(store.list_facts()) == 0


def test_memory_store_episodes(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.db")
    eid = store.add_episode("turn-1", "Hi CodAg", "Hello! How can I help?", "Greeting")
    assert eid > 0

    episodes = store.list_recent_episodes(limit=5)
    assert len(episodes) == 1
    assert episodes[0]["turn_id"] == "turn-1"
    assert episodes[0]["user_message"] == "Hi CodAg"
