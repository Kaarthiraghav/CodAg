"""Audit logging for all tool calls and permission decisions."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from codag.core.types import Decision, RiskTier, ToolCall


class AuditEntry(BaseModel):
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    turn_id: str | None = None
    tool: str
    arguments: dict[str, Any]
    tier: int
    decision: str
    user_approved: bool | None = None
    ok: bool | None = None
    result_summary: str | None = None
    undo_token: str | None = None


class AuditLogger:
    def __init__(self, data_dir: Path | str | None = None) -> None:
        base = Path(data_dir).expanduser() if data_dir else Path.home() / ".codag"
        self.audit_dir = base / "audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def _get_log_file(self) -> Path:
        month_str = datetime.now(timezone.utc).strftime("%Y-%m")
        return self.audit_dir / f"{month_str}.jsonl"

    def log_decision(
        self,
        call: ToolCall,
        decision: Decision,
        turn_id: str | None = None,
        user_approved: bool | None = None,
        ok: bool | None = None,
        result_summary: str | None = None,
        undo_token: str | None = None,
    ) -> AuditEntry:
        scrubbed_args = {}
        for k, v in call.arguments.items():
            if any(secret in k.lower() for secret in ("key", "secret", "password", "token")):
                scrubbed_args[k] = "******"
            else:
                scrubbed_args[k] = v

        entry = AuditEntry(
            turn_id=turn_id,
            tool=call.name,
            arguments=scrubbed_args,
            tier=int(decision.tier),
            decision=decision.action,
            user_approved=user_approved,
            ok=ok,
            result_summary=result_summary[:200] if result_summary else None,
            undo_token=undo_token,
        )

        with open(self._get_log_file(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.model_dump()) + "\n")

        return entry

    def list_entries(self, limit: int = 50) -> list[AuditEntry]:
        """List recent audit entries across log files."""
        files = sorted(self.audit_dir.glob("*.jsonl"), reverse=True)
        entries: list[AuditEntry] = []
        for file in files:
            lines = file.read_text(encoding="utf-8").strip().splitlines()
            for line in reversed(lines):
                if line.strip():
                    entries.append(AuditEntry.model_validate(json.loads(line)))
                    if len(entries) >= limit:
                        return entries
        return entries
