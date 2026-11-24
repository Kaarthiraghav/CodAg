"""Tests for multi-project chat session management, CLI commands, and Web API."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from typer.testing import CliRunner

from codag.cli import app as cli_app
from codag.config import CodagConfig
from codag.core.agent import Agent
from codag.core.chats import ChatManager
from codag.llm import LLMClient


runner = CliRunner()


def test_chat_manager_crud(tmp_path: Path):
    db_file = tmp_path / "chats.db"
    manager = ChatManager(db_file)

    # 1. Create sessions
    s1 = manager.create_session("General Chat")
    assert s1.title == "General Chat"
    assert s1.project_path is None

    proj_dir = tmp_path / "proj_alpha"
    proj_dir.mkdir()
    s2 = manager.create_session("Alpha Project", project_path=str(proj_dir))
    assert s2.title == "Alpha Project"
    assert s2.project_path == str(proj_dir.resolve())

    # 2. List sessions
    sessions = manager.list_sessions()
    assert len(sessions) == 2
    assert {s.id for s in sessions} == {s1.id, s2.id}

    # 3. Add messages
    manager.add_message(s1.id, "user", "Hello world")
    manager.add_message(s1.id, "assistant", "Hi there!")

    msgs = manager.get_messages(s1.id)
    assert len(msgs) == 2
    assert msgs[0] == {"role": "user", "content": "Hello world"}
    assert msgs[1] == {"role": "assistant", "content": "Hi there!"}

    # 4. Get session
    retrieved = manager.get_session(s1.id)
    assert retrieved is not None
    assert retrieved.message_count == 2

    by_title = manager.get_session("Alpha Project")
    assert by_title is not None
    assert by_title.id == s2.id

    # 5. Delete session
    assert manager.delete_session(s1.id) is True
    assert manager.get_session(s1.id) is None
    assert len(manager.get_messages(s1.id)) == 0
    assert len(manager.list_sessions()) == 1


def test_agent_session_and_project_context(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    data_dir = tmp_path / "data"

    cfg = CodagConfig()
    cfg.paths.data_dir = str(data_dir)
    cfg.policy.workspace.roots = [str(ws)]
    cfg.policy.workspace.read_roots = [str(ws)]

    mock_llm_client = MagicMock()
    resp = MagicMock()
    resp.message.content = "I am ready to work on this project."
    resp.message.tool_calls = None
    resp.prompt_eval_count = 15
    resp.eval_count = 10
    mock_llm_client.chat.return_value = resp

    llm = LLMClient(cfg.ollama, client=mock_llm_client)
    agent = Agent(cfg, llm=llm)

    proj_dir = tmp_path / "client_portal"
    proj_dir.mkdir()

    # Create session with project
    session = agent.chat_manager.create_session("Client Portal", project_path=str(proj_dir))

    # Run turn with session_id
    chunks = list(agent.run_turn("What project are we on?", session_id=session.id))
    answer = "".join(chunks)
    assert "ready to work" in answer

    # Verify messages were persisted in the chat manager
    history = agent.chat_manager.get_messages(session.id)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "What project are we on?"
    assert history[1]["role"] == "assistant"
    assert "ready to work" in history[1]["content"]

    # Verify project path was injected into system content sent to LLM
    call_args = mock_llm_client.chat.call_args[1]
    messages_sent = call_args["messages"]
    system_prompt = next(m["content"] for m in messages_sent if m["role"] == "system")
    assert str(proj_dir.resolve()) in system_prompt
    assert "Active Project Workspace:" in system_prompt


def test_cli_chats_commands(tmp_path: Path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "codag.toml").write_text(f"""
[paths]
data_dir = "{tmp_path}/data"

[policy.workspace]
roots = ["{tmp_path}/ws"]
read_roots = ["{tmp_path}/ws"]
""")

    # 1. Create chat via CLI
    res = runner.invoke(cli_app, ["chats", "new", "CLI Test Project", "--config-dir", str(cfg_dir)])
    assert res.exit_code == 0
    assert "Created chat session 'CLI Test Project'" in res.output

    # 2. List chats via CLI
    res = runner.invoke(cli_app, ["chats", "list", "--config-dir", str(cfg_dir)])
    assert res.exit_code == 0
    assert "CLI Test Project" in res.output

    # Extract session ID from list output
    db_file = tmp_path / "data" / "chats.db"
    manager = ChatManager(db_file)
    session = manager.get_session("CLI Test Project")
    assert session is not None

    # 3. Add message and show transcript
    manager.add_message(session.id, "user", "How is the weather?")
    res = runner.invoke(cli_app, ["chats", "show", session.id, "--config-dir", str(cfg_dir)])
    assert res.exit_code == 0
    assert "How is the weather?" in res.output

    # 4. Delete chat via CLI
    res = runner.invoke(cli_app, ["chats", "delete", session.id, "--config-dir", str(cfg_dir)])
    assert res.exit_code == 0
    assert "Deleted chat session" in res.output
