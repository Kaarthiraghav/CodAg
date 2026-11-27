"""Core data types and schemas for CodAg."""

from enum import IntEnum
from typing import Any, Literal
from pydantic import BaseModel, Field


class RiskTier(IntEnum):
    READ = 0        # no side effects
    SAFE_WRITE = 1  # small, reversible, local
    CONFIRM = 2     # significant: requires explicit approval
    FORBIDDEN = 3   # never allowed by default


class ToolSpec(BaseModel):
    name: str                         # e.g. "files.read_file"
    description: str                  # shown to model; keep under 200 characters
    parameters: dict[str, Any]        # JSON schema
    base_tier: RiskTier
    skill: str


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    call_id: str
    ok: bool
    content: str                      # text returned to model; truncated to a budget
    untrusted: bool = False           # True if it contains external content
    undo_token: str | None = None     # set when the action can be undone


class Decision(BaseModel):
    action: Literal["allow", "ask", "deny"]
    tier: RiskTier
    reason: str


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class TurnContext(BaseModel):
    turn_id: str
    tainted: bool = False
    model_calls_count: int = 0
    tool_calls_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    models_used: list[str] = Field(default_factory=list)


class AgentEvent(BaseModel):
    event_type: Literal[
        "text_delta",
        "tool_started",
        "tool_finished",
        "confirmation_requested",
        "confirmation_resolved",
        "turn_finished",
        "error",
    ]
    turn_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
