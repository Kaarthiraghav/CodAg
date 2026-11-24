from pathlib import Path
from unittest.mock import MagicMock
from codag.config import CodagConfig
from codag.core.agent import Agent
from codag.llm import LLMClient


def test_agent_run_turn_with_tool_call(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    data_dir = tmp_path / "data"

    cfg = CodagConfig()
    cfg.paths.data_dir = str(data_dir)
    cfg.policy.workspace.roots = [str(ws)]
    cfg.policy.workspace.read_roots = [str(ws)]

    # Mock Ollama client:
    # 1st call: returns tool_call to files.create_file
    # 2nd call: returns final assistant text
    mock_llm_client = MagicMock()

    # Tool call response
    tc_mock = MagicMock()
    tc_mock.id = "c_1"
    tc_mock.function.name = "files.create_file"
    target_file = str(ws / "notes.txt")
    tc_mock.function.arguments = {"path": target_file, "content": "Antigravity rocks"}

    resp1 = MagicMock()
    resp1.message.content = ""
    resp1.message.tool_calls = [tc_mock]
    resp1.prompt_eval_count = 10
    resp1.eval_count = 10

    # Final answer response
    resp2 = MagicMock()
    resp2.message.content = "Created notes.txt for you."
    resp2.message.tool_calls = None
    resp2.prompt_eval_count = 20
    resp2.eval_count = 8

    mock_llm_client.chat.side_effect = [resp1, resp2]
    llm = LLMClient(cfg.ollama, client=mock_llm_client)

    agent = Agent(cfg, llm=llm)
    chunks = list(agent.run_turn("Create notes.txt containing Antigravity rocks"))

    assert Path(target_file).is_file()
    assert Path(target_file).read_text(encoding="utf-8") == "Antigravity rocks"
    assert "Created notes.txt for you." in "".join(chunks)

    # Verify audit log was created
    audit_files = list((data_dir / "audit").glob("*.jsonl"))
    assert len(audit_files) >= 1
    content = audit_files[0].read_text(encoding="utf-8")
    assert "files.create_file" in content
