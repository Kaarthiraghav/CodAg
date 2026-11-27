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


def test_token_usage_extraction_and_cli_formatting(tmp_path):
    from codag.cli import _format_token_usage
    from codag.core.agent import Agent
    from codag.llm import LLMClient, extract_token_usage

    # 1. Gemini usage with explicit thoughts_token_count
    mock_genai = MagicMock()
    mock_resp = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text="Done", function_call=None)]))],
        text="Done",
        usage_metadata=SimpleNamespace(prompt_token_count=200, candidates_token_count=50, thoughts_token_count=75),
    )
    mock_genai.models.generate_content.return_value = mock_resp
    gem = GeminiClient(GeminiConfig(enabled=True, model="gemini-2.5-flash"), api_key="k", client=mock_genai)
    gem_resp = gem.chat("gemini-2.5-flash", [{"role": "user", "content": "hi"}], MainModelConfig())
    gem_usage = extract_token_usage(gem_resp)
    assert gem_usage["input_tokens"] == 200
    assert gem_usage["output_tokens"] == 50
    assert gem_usage["thinking_tokens"] == 75
    assert gem_usage["total_tokens"] == 325

    # 2. Ollama response with thinking text splits eval_count into thinking + output
    ollama_resp = SimpleNamespace(
        message=SimpleNamespace(content="Final answer", thinking="Step 1: analyze the question carefully."),
        prompt_eval_count=100,
        eval_count=40,
        model="qwen3.5:9b",
    )
    ol_usage = extract_token_usage(ollama_resp)
    assert ol_usage["input_tokens"] == 100
    assert ol_usage["thinking_tokens"] > 0
    assert ol_usage["output_tokens"] + ol_usage["thinking_tokens"] == 40

    # 3. Agent turn accumulates usage and _format_token_usage formats cleanly
    cfg = CodagConfig()
    cfg.paths.data_dir = str(tmp_path / "data")
    mock_ol = MagicMock()
    mock_ol.chat.return_value = ollama_resp
    agent = Agent(cfg, llm=LLMClient(cfg.ollama, client=mock_ol))
    list(agent.run_turn("Hello"))
    assert agent.last_turn_usage["input_tokens"] == 100
    assert agent.last_turn_usage["total_tokens"] == 140
    formatted = _format_token_usage(agent.last_turn_usage)
    assert "input 100" in formatted
    assert f"output {agent.last_turn_usage['output_tokens']}" in formatted
    assert f"thinking {agent.last_turn_usage['thinking_tokens']}" in formatted
