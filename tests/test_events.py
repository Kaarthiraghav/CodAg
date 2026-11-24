import json
from pathlib import Path
from codag.core.events import EventLogger


def test_event_logger_in_memory():
    logger = EventLogger()
    event = logger.log("text_delta", turn_id="t1", text="Hello")
    assert event.event_type == "text_delta"
    assert event.turn_id == "t1"
    assert event.data["text"] == "Hello"


def test_event_logger_to_file(tmp_path: Path):
    log_file = tmp_path / "events.jsonl"
    logger = EventLogger(log_file)
    logger.log("model_call", turn_id="t2", model="qwen3:8b", latency_s=0.5)

    assert log_file.is_file()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["event_type"] == "model_call"
    assert data["turn_id"] == "t2"
    assert data["data"]["model"] == "qwen3:8b"
