from pathlib import Path
from codag.safety.snapshots import SnapshotManager


def test_snapshot_modify_and_undo(tmp_path: Path):
    mgr = SnapshotManager(tmp_path / "data")
    test_file = tmp_path / "app.py"
    test_file.write_text("initial content", encoding="utf-8")

    # Snapshot before edit
    token = mgr.snapshot_before_modify(test_file, turn_id="turn_test")
    assert token.startswith("undo-")

    # Modify file
    test_file.write_text("corrupted content", encoding="utf-8")

    # Undo
    ok, msg = mgr.undo(token)
    assert ok is True
    assert test_file.read_text(encoding="utf-8") == "initial content"


def test_trash_delete_and_undo(tmp_path: Path):
    mgr = SnapshotManager(tmp_path / "data")
    test_file = tmp_path / "document.txt"
    test_file.write_text("important doc", encoding="utf-8")

    # Move to trash
    token = mgr.move_to_trash(test_file)
    assert not test_file.exists()

    # Undo restores from trash
    ok, msg = mgr.undo(token)
    assert ok is True
    assert test_file.exists()
    assert test_file.read_text(encoding="utf-8") == "important doc"
