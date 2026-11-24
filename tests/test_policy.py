from pathlib import Path
from codag.config import PolicyConfig
from codag.core.types import RiskTier, ToolCall, ToolSpec
from codag.safety.policy import PolicyEngine


def test_policy_forbidden_deny_pattern(tmp_path: Path):
    policy = PolicyConfig()
    policy.deny_paths.patterns = ["**/.env"]
    engine = PolicyEngine(policy)

    spec = ToolSpec(name="files.read_file", description="", parameters={}, base_tier=RiskTier.READ, skill="files")
    call = ToolCall(id="c1", name="files.read_file", arguments={"path": str(tmp_path / ".env")})

    forbidden, reason = engine.is_forbidden(call, spec)
    assert forbidden is True
    assert "matches forbidden deny pattern" in reason


def test_policy_forbidden_shell():
    policy = PolicyConfig()
    engine = PolicyEngine(policy)

    spec = ToolSpec(name="shell.run", description="", parameters={}, base_tier=RiskTier.CONFIRM, skill="shell")
    call = ToolCall(id="c2", name="shell.run", arguments={"command": "sudo rm -rf /"})

    forbidden, reason = engine.is_forbidden(call, spec)
    assert forbidden is True
    assert "forbidden pattern" in reason


def test_policy_escalation_delete_and_move():
    policy = PolicyConfig()
    engine = PolicyEngine(policy)

    spec = ToolSpec(name="files.delete_file", description="", parameters={}, base_tier=RiskTier.READ, skill="files")
    call = ToolCall(id="c3", name="files.delete_file", arguments={"path": "some.txt"})

    tier, reason = engine.escalate(call, spec)
    assert tier == RiskTier.CONFIRM
    assert "requires confirmation" in reason


def test_policy_escalation_file_count():
    policy = PolicyConfig()
    policy.limits.max_files_per_action = 3
    engine = PolicyEngine(policy)

    spec = ToolSpec(name="files.clean", description="", parameters={}, base_tier=RiskTier.SAFE_WRITE, skill="files")
    call = ToolCall(id="c4", name="files.clean", arguments={"files": ["a", "b", "c", "d"]})

    tier, reason = engine.escalate(call, spec)
    assert tier == RiskTier.CONFIRM
    assert "exceeding limit of 3" in reason
