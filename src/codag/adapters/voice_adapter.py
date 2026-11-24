"""Voice adapters (speech-to-text input, text-to-speech output) for Section 12."""

import re
import subprocess
from typing import Any, Generator

from codag.adapters.base import InputAdapter, OutputAdapter
from codag.core.types import AgentEvent

AFFIRMATIVE_RESPONSES = {
    "yes", "yeah", "yep", "sure", "ok", "okay", "proceed", "approve", "confirm", "go ahead", "do it"
}
NEGATIVE_RESPONSES = {
    "no", "nope", "cancel", "stop", "abort", "reject", "deny", "don't"
}


def parse_spoken_confirmation(spoken_text: str) -> bool:
    """Parse a spoken response to an approval request."""
    cleaned = re.sub(r"[^\w\s]", "", spoken_text.lower().strip())
    words = cleaned.split()
    for w in words:
        if w in AFFIRMATIVE_RESPONSES:
            return True
        if w in NEGATIVE_RESPONSES:
            return False
    return False


class VoiceInputAdapter(InputAdapter):
    """Speech-to-text input adapter."""

    def __init__(self, speakable_mode: bool = True) -> None:
        self.speakable_mode = speakable_mode

    def events(self) -> Generator[dict[str, Any], None, None]:
        # Yield input events transcribed from voice audio
        pass

    def transcribe_audio_phrase(self, phrase: str) -> dict[str, Any]:
        """Process transcribed speech text."""
        return {
            "type": "user_message",
            "content": phrase.strip(),
            "speakable": self.speakable_mode,
        }


class VoiceOutputAdapter(OutputAdapter):
    """Text-to-speech output adapter using macOS native `say`."""

    def __init__(self, enabled: bool = True, voice: str | None = None) -> None:
        self.enabled = enabled
        self.voice = voice

    def speak(self, text: str) -> None:
        """Synthesize spoken audio on macOS via the native `say` utility."""
        if not self.enabled or not text.strip():
            return

        # Strip markdown syntax and code blocks for speech clarity
        cleaned = re.sub(r"```[\s\S]*?```", " Code block omitted for speech. ", text)
        cleaned = re.sub(r"[*_`#~\[\]\(\)]", "", cleaned).strip()
        if not cleaned:
            return

        cmd = ["say"]
        if self.voice:
            cmd.extend(["-v", self.voice])
        cmd.append(cleaned[:1000])

        try:
            subprocess.run(cmd, check=True)
        except Exception:
            pass

    def emit(self, event: AgentEvent) -> None:
        if event.event_type == "text_delta":
            pass
        elif event.event_type == "turn_finished":
            # Speak final assistant content
            final_text = event.payload.get("content", "")
            if final_text:
                self.speak(final_text)
        elif event.event_type == "confirmation_requested":
            tool_name = event.payload.get("tool", "")
            reason = event.payload.get("reason", "")
            prompt = f"Approval required for {tool_name}. Reason: {reason}. Would you like to proceed?"
            self.speak(prompt)
