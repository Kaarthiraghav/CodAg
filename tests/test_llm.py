from unittest.mock import MagicMock
from codag.config import MainModelConfig, OllamaConfig
from codag.core.events import EventLogger
from codag.llm import LLMClient


def test_plain_chat(tmp_path):
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.message.content = "I am CodAg."
    mock_resp.message.tool_calls = None
    mock_resp.prompt_eval_count = 20
    mock_resp.eval_count = 5
    mock_client.chat.return_value = mock_resp

    log_file = tmp_path / "events.jsonl"
    logger = EventLogger(log_file)
    llm = LLMClient(OllamaConfig(), logger=logger, client=mock_client)

    settings = MainModelConfig(temperature=0.3, num_ctx=4096, think=False)
    resp = llm.chat(
        model="qwen3:8b",
        messages=[{"role": "user", "content": "Who are you?"}],
        settings=settings,
        turn_id="turn-1",
    )

    assert resp.message.content == "I am CodAg."
    assert mock_client.chat.called
    kwargs = mock_client.chat.call_args.kwargs
    assert kwargs["options"]["num_ctx"] == 4096
    assert kwargs["options"]["temperature"] == 0.3
    assert kwargs["think"] is False


def test_stream_chat(tmp_path):
    mock_client = MagicMock()
    chunk1 = MagicMock()
    chunk1.message.content = "Hello "
    chunk2 = MagicMock()
    chunk2.message.content = "world!"
    mock_client.chat.return_value = iter([chunk1, chunk2])

    log_file = tmp_path / "events.jsonl"
    logger = EventLogger(log_file)
    llm = LLMClient(OllamaConfig(), logger=logger, client=mock_client)

    settings = MainModelConfig()
    chunks = list(llm.stream_chat("qwen3:8b", [{"role": "user", "content": "Hi"}], settings))
    assert "".join(chunks) == "Hello world!"
    assert log_file.is_file()
