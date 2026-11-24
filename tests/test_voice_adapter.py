"""Tests for the Voice Adapters (STT, TTS, confirmation parsing)."""

from unittest.mock import MagicMock, patch
import pytest

from codag.adapters.voice_adapter import (
    VoiceInputAdapter,
    VoiceOutputAdapter,
    parse_spoken_confirmation,
)
from codag.core.types import AgentEvent


def test_parse_spoken_confirmation():
    # Affirmatives
    assert parse_spoken_confirmation("yes") is True
    assert parse_spoken_confirmation("yeah, do it") is True
    assert parse_spoken_confirmation("sure") is True
    assert parse_spoken_confirmation("ok, go ahead") is True
    assert parse_spoken_confirmation("approve this") is True

    # Negatives
    assert parse_spoken_confirmation("no") is False
    assert parse_spoken_confirmation("cancel") is False
    assert parse_spoken_confirmation("stop that") is False
    assert parse_spoken_confirmation("nope, don't do it") is False

    # Ambiguous or unknown
    assert parse_spoken_confirmation("maybe tomorrow") is False


def test_voice_input_adapter():
    adapter = VoiceInputAdapter(speakable_mode=True)
    evt = adapter.transcribe_audio_phrase("What is on my calendar today?")
    assert evt["type"] == "user_message"
    assert evt["content"] == "What is on my calendar today?"
    assert evt["speakable"] is True


@patch("subprocess.run")
def test_voice_output_adapter_speak(mock_run):
    adapter = VoiceOutputAdapter(enabled=True)
    adapter.speak("Hello from CodAg")
    mock_run.assert_called_once_with(["say", "Hello from CodAg"], check=True)


@patch("subprocess.run")
def test_voice_output_adapter_events(mock_run):
    adapter = VoiceOutputAdapter(enabled=True)
    # Turn finished event
    adapter.emit(
        AgentEvent(
            event_type="turn_finished",
            turn_id="t1",
            payload={"content": "Here is your summary."},
        )
    )
    mock_run.assert_called_once_with(["say", "Here is your summary."], check=True)
