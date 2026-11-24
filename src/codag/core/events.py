"""Event types and JSONL event logger for CodAg."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field


class AgentEvent(BaseModel):
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_type: str
    turn_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class EventLogger:
    def __init__(self, log_path: Path | str | None = None) -> None:
        self.log_path = Path(log_path).expanduser() if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event_type: str, turn_id: str | None = None, **kwargs: Any) -> AgentEvent:
        event = AgentEvent(
            event_type=event_type,
            turn_id=turn_id,
            data=kwargs,
        )
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.model_dump()) + "\n")
        return event
