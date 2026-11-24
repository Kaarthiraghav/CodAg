"""InputAdapter and OutputAdapter interfaces (Section 12 of spec)."""

from abc import ABC, abstractmethod
from typing import Any, Generator

from codag.core.types import AgentEvent


class InputAdapter(ABC):
    """Abstract interface yielding user input events."""

    @abstractmethod
    def events(self) -> Generator[dict[str, Any], None, None]:
        """Yield input events (e.g. {"type": "user_message", "content": ...})."""
        pass


class OutputAdapter(ABC):
    """Abstract interface receiving streamed agent execution events."""

    @abstractmethod
    def emit(self, event: AgentEvent) -> None:
        """Receive an agent event (text_delta, tool_activity, confirmation, etc.)."""
        pass
