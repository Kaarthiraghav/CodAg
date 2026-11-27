"""Unit tests for GeminiClient (google-genai) and ModelOrchestrator."""

from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from codag.config import CodagConfig, GeminiConfig, MainModelConfig
from codag.core.events import EventLogger
from codag.core.orchestrator import ModelOrchestrator
from codag.llm import GeminiClient


def test_gemini_client_chat_and_tool_calls(tmp_path):
    mock_genai = MagicMock()
    mock_part = SimpleNamespace(
        text="Checking web...",
        function_call=SimpleNamespace(name="web.research_and_verify", args={"query": "M4 specs"}),
    )
    mock_resp = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[mock_part]))],
        text="",
        usage_metadata=SimpleNamespace(prompt_token_count=120, candidates_token_count=30),
    )
    mock_genai.models.generate_content.return_value = mock_resp

    logger = EventLogger(tmp_path / "events.jsonl")
    client = GeminiClient(GeminiConfig(enabled=True, model="gemini-2.5-flash"), logger=logger, api_key="test-key", client=mock_genai)
    assert client.is_available is True

    tools = [{
        "type": "function",
        "function": {
            "name": "web.research_and_verify",
            "description": "Search and verify",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    }]
    res = client.chat(
        model="gemini-2.5-flash",
        messages=[
            {"role": "system", "content": "You are CodAg."},
            {"role": "user", "content": "Verify M4 specs"},
        ],
        settings=MainModelConfig(),
        tools=tools,
        turn_id="t-gem-1",
    )

    assert res.provider == "gemini"
    assert res.message.content == "Checking web..."
    assert len(res.message.tool_calls) == 1
    assert res.message.tool_calls[0].function.name == "web.research_and_verify"
    assert res.message.tool_calls[0].function.arguments == {"query": "M4 specs"}
    assert res.prompt_eval_count == 120
    assert res.eval_count == 30


def test_orchestrator_auto_routing_and_fallback(tmp_path):
    cfg = CodagConfig()
    cfg.orchestrator.mode = "auto"
    cfg.orchestrator.context_overflow_chars = 100

    mock_ollama = MagicMock()
    mock_ollama.chat.return_value = SimpleNamespace(message=SimpleNamespace(content="local reply", tool_calls=None))

    mock_gemini = MagicMock()
    mock_gemini.is_available = True
    mock_gemini.chat.return_value = SimpleNamespace(message=SimpleNamespace(content="gemini reply", tool_calls=None))

    logger = EventLogger(tmp_path / "events.jsonl")
    orch = ModelOrchestrator(cfg, ollama_client=mock_ollama, gemini_client=mock_gemini, logger=logger)

    # 1. Simple chat -> local Ollama
    provider, _ = orch.select_backend(messages=[{"role": "user", "content": "Hi"}])
    assert provider == "ollama"

    # 2. Complex skill (web/code) -> Gemini
    provider, _ = orch.select_backend(
        messages=[{"role": "user", "content": "Research chess"}],
        tools=[{"type": "function", "function": {"name": "web.research_and_verify"}}],
    )
    assert provider == "gemini"

    # 3. Large context -> Gemini
    provider, _ = orch.select_backend(messages=[{"role": "user", "content": "x" * 150}])
    assert provider == "gemini"

    # 4. Explicit local mode overrides complex skill
    orch.set_mode("local")
    provider, _ = orch.select_backend(
        messages=[{"role": "user", "content": "x" * 150}],
        skill_name="code",
    )
    assert provider == "ollama"

    # 5. Gemini error triggers automatic fallback to Ollama
    orch.set_mode("gemini")
    mock_gemini.chat.side_effect = RuntimeError("API quota exceeded")
    resp = orch.chat(
        model="qwen3.5:9b",
        messages=[{"role": "user", "content": "Build app"}],
        settings=MainModelConfig(),
        turn_id="t-fb-1",
    )
    assert resp.message.content == "local reply"
    assert mock_ollama.chat.called

    with pytest.raises(ValueError):
        orch.set_mode("invalid-mode")
