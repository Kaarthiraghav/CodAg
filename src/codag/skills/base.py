"""Base skill abstractions, manifest loading, and @tool decorator."""

import functools
import inspect
from pathlib import Path
import tomllib
from typing import Any, Callable, get_type_hints
from pydantic import BaseModel, Field

from codag.core.types import RiskTier, ToolResult, ToolSpec


def _python_type_to_json_type(py_type: Any) -> str:
    if py_type in (str, Path):
        return "string"
    if py_type in (int, float):
        return "number"
    if py_type is bool:
        return "boolean"
    if py_type in (list, tuple, set):
        return "array"
    if py_type is dict:
        return "object"
    return "string"


class ToolDefinition:
    def __init__(self, func: Callable, spec: ToolSpec) -> None:
        self.func = func
        self.spec = spec

    def __call__(self, *args: Any, **kwargs: Any) -> ToolResult:
        try:
            return self.func(*args, **kwargs)
        except Exception as exc:
            return ToolResult(
                call_id=kwargs.get("call_id", ""),
                ok=False,
                content=f"Tool error: {exc}",
            )


def tool(name: str, tier: RiskTier, description: str) -> Callable:
    """Decorator to declare an agent tool with risk tier and schema."""
    def decorator(fn: Callable) -> ToolDefinition:
        sig = inspect.signature(fn)
        type_hints = get_type_hints(fn)

        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in {"self", "cls", "call_id", "ctx", "sandbox", "snapshots"}:
                continue
            p_type = type_hints.get(param_name, str)
            json_type = _python_type_to_json_type(p_type)
            prop_def: dict[str, Any] = {"type": json_type}
            if param.default is inspect.Parameter.empty:
                required.append(param_name)
            properties[param_name] = prop_def

        skill_name = name.split(".")[0] if "." in name else "core"
        spec = ToolSpec(
            name=name,
            description=description[:200],
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
            base_tier=tier,
            skill=skill_name,
        )
        return ToolDefinition(fn, spec)

    return decorator


class SkillManifest(BaseModel):
    name: str
    description: str
    router_keywords: list[str] = Field(default_factory=list)


def load_manifest(manifest_path: Path | str) -> SkillManifest:
    p = Path(manifest_path)
    with open(p, "rb") as f:
        data = tomllib.load(f)
    return SkillManifest.model_validate(data)
