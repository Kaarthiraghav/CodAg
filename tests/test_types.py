from codag.core.types import Decision, RiskTier, ToolCall, ToolResult, ToolSpec


def test_types_creation():
    spec = ToolSpec(
        name="files.read_file",
        description="Read file",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        base_tier=RiskTier.READ,
        skill="files",
    )
    assert spec.base_tier == RiskTier.READ

    call = ToolCall(id="c1", name="files.read_file", arguments={"path": "test.txt"})
    assert call.id == "c1"

    result = ToolResult(call_id="c1", ok=True, content="sample text", untrusted=False)
    assert result.ok is True

    dec = Decision(action="allow", tier=RiskTier.READ, reason="Safe read")
    assert dec.action == "allow"
