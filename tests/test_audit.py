from pathlib import Path
from codag.core.types import Decision, RiskTier, ToolCall
from codag.safety.audit import AuditLogger


def test_audit_logging_and_scrubbing(tmp_path: Path):
    logger = AuditLogger(tmp_path)
    call = ToolCall(id="c1", name="auth.login", arguments={"user": "alice", "api_key": "secret123", "password": "pass"})
    decision = Decision(action="allow", tier=RiskTier.READ, reason="Safe")

    entry = logger.log_decision(call, decision, turn_id="t1", ok=True, result_summary="Logged in")
    assert entry.arguments["user"] == "alice"
    assert entry.arguments["api_key"] == "******"
    assert entry.arguments["password"] == "******"

    entries = logger.list_entries(limit=10)
    assert len(entries) == 1
    assert entries[0].tool == "auth.login"
    assert entries[0].decision == "allow"
