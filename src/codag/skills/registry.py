"""Skill and tool registry."""

from typing import Callable
from codag.core.types import ToolSpec
from codag.skills.base import ToolDefinition


class SkillRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool_def: ToolDefinition) -> None:
        self._tools[tool_def.spec.name] = tool_def

    def get_tool(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def get_spec(self, name: str) -> ToolSpec | None:
        tool_def = self._tools.get(name)
        return tool_def.spec if tool_def else None

    def get_specs_for_skill(self, skill_name: str) -> list[ToolSpec]:
        return [
            tool_def.spec
            for tool_def in self._tools.values()
            if tool_def.spec.skill == skill_name
        ]

    def get_all_specs(self) -> list[ToolSpec]:
        return [tool_def.spec for tool_def in self._tools.values()]


# Default shared registry
default_registry = SkillRegistry()
