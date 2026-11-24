from codag.config import PolicyConfig
from codag.core.types import Decision, RiskTier, ToolCall, ToolSpec, TurnContext
from codag.safety.permissions import PermissionEngine


def test_permission_allow():
    policy = PolicyConfig()
    engine = PermissionEngine(policy)
    ctx = TurnContext(turn_id="t1", tainted=False)

    spec = ToolSpec(name="files.list_directory", description="", parameters={}, base_tier=RiskTier.READ, skill="files")
    call = ToolCall(id="c1", name="files.list_directory", arguments={"path": "."})

    dec = engine.decide(call, spec, ctx)
    assert dec.action == "allow"
    assert dec.tier == RiskTier.READ


def test_permission_taint_escalation():
    policy = PolicyConfig()
    engine = PermissionEngine(policy)
    ctx = TurnContext(turn_id="t2", tainted=True)  # Tainted turn!

    spec = ToolSpec(name="files.create_file", description="", parameters={}, base_tier=RiskTier.SAFE_WRITE, skill="files")
    call = ToolCall(id="c2", name="files.create_file", arguments={"path": "note.txt", "content": "hi"})

    dec = engine.decide(call, spec, ctx)
    assert dec.action == "ask"
    assert dec.tier == RiskTier.CONFIRM
    assert "Untrusted content" in dec.reason


def test_permission_forbidden():
    policy = PolicyConfig()
    policy.deny_paths.patterns = ["~/.ssh"]
    engine = PermissionEngine(policy)
    ctx = TurnContext(turn_id="t3", tainted=False)

    spec = ToolSpec(name="files.read_file", description="", parameters={}, base_tier=RiskTier.READ, skill="files")
    call = ToolCall(id="c3", name="files.read_file", arguments={"path": "~/.ssh/id_rsa"})

    dec = engine.decide(call, spec, ctx)
    assert dec.action == "deny"
    assert dec.tier == RiskTier.FORBIDDEN
