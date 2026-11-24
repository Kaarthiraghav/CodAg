from pathlib import Path
from codag.skills.notes.tools import append_note, configure_notes, create_note, list_notes, search_notes


def test_notes_lifecycle(tmp_path: Path):
    notes_dir = tmp_path / "notes"
    configure_notes(notes_dir)

    # 1. Create note
    res = create_note("Project Ideas", "Build a local agent.")
    assert res.ok is True
    assert (notes_dir / "project_ideas.md").exists()

    # 2. Append note
    res_app = append_note("Project Ideas", "Add memory support.")
    assert res_app.ok is True
    content = (notes_dir / "project_ideas.md").read_text(encoding="utf-8")
    assert "Add memory support" in content

    # 3. Search notes
    res_search = search_notes("agent")
    assert res_search.ok is True
    assert "project_ideas" in res_search.content

    # 4. List notes
    res_list = list_notes()
    assert res_list.ok is True
    assert "project_ideas" in res_list.content
