from pathlib import Path
from codag.config import CodagConfig
from codag.core.types import RiskTier, ToolCall, ToolSpec, TurnContext
from codag.safety.permissions import PermissionEngine
from codag.safety.sandbox import Sandbox


def test_taint_escalation_on_web_content(tmp_path: Path):
    cfg = CodagConfig()
    cfg.policy.workspace.roots = [str(tmp_path / "workspace")]
    sandbox = Sandbox(cfg.policy)
    engine = PermissionEngine(cfg.policy, sandbox)

    # 1. Normal turn: creating a file inside workspace is SAFE_WRITE (allowed)
    normal_ctx = TurnContext(turn_id="t1", tainted=False)
    spec_create = ToolSpec(
        name="files.create_file",
        description="",
        parameters={},
        base_tier=RiskTier.SAFE_WRITE,
        skill="files",
    )
    call_create = ToolCall(
        id="c1",
        name="files.create_file",
        arguments={"path": str(tmp_path / "workspace" / "note.txt"), "content": "normal"},
    )
    dec_normal = engine.decide(call_create, spec_create, normal_ctx)
    assert dec_normal.action == "allow"
    assert dec_normal.tier == RiskTier.SAFE_WRITE

    # 2. Tainted turn (after reading an untrusted web page or external file):
    # Action MUST escalate to CONFIRM (action="ask")!
    tainted_ctx = TurnContext(turn_id="t2", tainted=True)
    dec_tainted = engine.decide(call_create, spec_create, tainted_ctx)
    assert dec_tainted.action == "ask"
    assert dec_tainted.tier == RiskTier.CONFIRM
    assert "Untrusted content is present in this turn" in dec_tainted.reason


def test_forbidden_invariants_hold_under_taint(tmp_path: Path):
    cfg = CodagConfig()
    cfg.policy.workspace.roots = [str(tmp_path / "workspace")]
    sandbox = Sandbox(cfg.policy)
    engine = PermissionEngine(cfg.policy, sandbox)

    tainted_ctx = TurnContext(turn_id="t3", tainted=True)

    # Deny path must be FORBIDDEN even when tainted
    spec_read = ToolSpec(name="files.read_file", description="", parameters={}, base_tier=RiskTier.READ, skill="files")
    call_ssh = ToolCall(id="c2", name="files.read_file", arguments={"path": "~/.ssh/id_rsa"})
    dec_ssh = engine.decide(call_ssh, spec_read, tainted_ctx)
    assert dec_ssh.action == "deny"
    assert dec_ssh.tier == RiskTier.FORBIDDEN

    # Forbidden shell command must be FORBIDDEN even when tainted
    spec_shell = ToolSpec(name="shell.run_command", description="", parameters={}, base_tier=RiskTier.SAFE_WRITE, skill="shell")
    call_sudo = ToolCall(id="c3", name="shell.run_command", arguments={"command": "sudo rm -rf /"})
    dec_sudo = engine.decide(call_sudo, spec_shell, tainted_ctx)
    assert dec_sudo.action == "deny"
    assert dec_sudo.tier == RiskTier.FORBIDDEN
