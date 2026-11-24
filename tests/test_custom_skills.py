"""Unit tests for autonomous custom skill creation, hot loading, and deletion."""

from pathlib import Path
from codag.skills.base import ToolDefinition
from codag.skills.custom import (
    configure_custom_skills,
    create_custom_skill,
    delete_custom_skill,
    list_custom_skills,
    load_all_custom_skills,
)
from codag.skills.registry import SkillRegistry


def test_custom_skill_lifecycle(tmp_path: Path):
    registry = SkillRegistry()
    skills_dir = tmp_path / "skills"
    configure_custom_skills(skills_dir, registry=registry)

    # 1. Initial listing
    res = list_custom_skills()
    assert res.ok
    assert "No custom skills created yet" in res.content

    # 2. Synthesize new custom skill
    sample_code = '''
from codag.skills.base import tool
from codag.core.types import RiskTier, ToolResult

@tool(
    name="calculator.add",
    tier=RiskTier.READ,
    description="Add two numbers together."
)
def add_numbers(a: int, b: int) -> ToolResult:
    return ToolResult(call_id="", ok=True, content=str(a + b))
'''

    create_res = create_custom_skill(
        skill_name="calculator",
        description="Math and arithmetic calculation tools",
        python_code=sample_code,
        router_keywords=["add", "sum", "math"],
    )

    assert create_res.ok
    assert "calculator" in create_res.content

    # 3. Verify tool is in the registry
    tool_def = registry.get_tool("calculator.add")
    assert tool_def is not None
    assert isinstance(tool_def, ToolDefinition)

    # 4. Execute tool
    exec_res = tool_def(a=15, b=27)
    assert exec_res.ok
    assert exec_res.content == "42"

    # 5. List skills should now include calculator
    list_res = list_custom_skills()
    assert list_res.ok
    assert "calculator" in list_res.content

    # 6. Delete custom skill
    del_res = delete_custom_skill("calculator")
    assert del_res.ok
    assert "Deleted custom skill 'calculator'" in del_res.content
    assert not (skills_dir / "calculator").exists()
