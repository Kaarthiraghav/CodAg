"""Unit tests for user profile synthesis and implicit habit reflection."""

from pathlib import Path
from unittest.mock import MagicMock

from codag.memory.profile import ProfileEngine


def test_profile_engine_crud(tmp_path: Path):
    db_file = tmp_path / "memory.db"
    engine = ProfileEngine(db_file)

    # Initially empty
    assert engine.get_full_profile() == {}
    assert engine.format_profile_for_prompt() == ""

    # Add aspect
    engine.update_aspect(
        aspect="work_style",
        summary="Prefers structured documentation and PDF study sheets",
        details=["Requests detailed lecture notes", "Uses macOS Preview for reading"],
    )

    prof = engine.get_full_profile()
    assert "work_style" in prof
    assert len(prof["work_style"]["details"]) == 2
    assert "Requests detailed lecture notes" in prof["work_style"]["details"]

    formatted = engine.format_profile_for_prompt()
    assert "<user_profile_and_habits>" in formatted
    assert "Work Style" in formatted
    assert "Requests detailed lecture notes" in formatted


def test_profile_reflection_with_mock_llm(tmp_path: Path):
    db_file = tmp_path / "memory.db"
    engine = ProfileEngine(db_file)

    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.message.content = '{"traits": [{"aspect": "projects", "observation": "Working on Web Mining module on external drive"}, {"aspect": "work_style", "observation": "Prefers comprehensive 5-day structured study plans"}]}'
    mock_llm.chat.return_value = mock_resp

    obs = engine.reflect_on_interaction(
        turn_id="turn_123",
        user_message="In the Black Hole Hard Disk there is a folder called Web Mining. Make a study plan for 5 days.",
        assistant_message="Here is your 5-day study plan covering all topics.",
        tools_used=["files.read_file", "files.list_directory"],
        llm=mock_llm,
        model="qwen3.5:9b",
    )

    assert len(obs) == 2
    assert "Working on Web Mining module on external drive" in obs

    # Verify profile was populated
    full = engine.get_full_profile()
    assert "projects" in full
    assert "work_style" in full
    assert "Working on Web Mining module on external drive" in full["projects"]["details"]
