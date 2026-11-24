"""Dynamic custom skill loader, synthesis, and execution engine.

Supports Hermes-style autonomous skill creation:
- Loads custom tools dynamically from `~/.codag/skills/<skill_name>/`
- Provides built-in meta-tools for the agent to create, list, and modify custom skills on the fly.
"""

import importlib.util
import inspect
from pathlib import Path
import re
import shutil
import sys
import tomllib
from typing import Any

from codag.core.types import RiskTier, ToolResult, ToolSpec
from codag.skills.base import ToolDefinition, tool
from codag.skills.registry import SkillRegistry, default_registry

_skills_dir: Path | None = None
_custom_registry: SkillRegistry = default_registry


def configure_custom_skills(skills_dir: Path | str | None = None, registry: SkillRegistry | None = None) -> None:
    """Configure and load custom user skills into the registry."""
    global _skills_dir, _custom_registry
    base = Path(skills_dir).expanduser() if skills_dir else Path.home() / ".codag" / "skills"
    _skills_dir = base
    _skills_dir.mkdir(parents=True, exist_ok=True)
    if registry:
        _custom_registry = registry
    load_all_custom_skills()


def load_all_custom_skills() -> list[str]:
    """Scan and import all custom skills from the skills directory."""
    if not _skills_dir or not _skills_dir.exists():
        return []

    loaded: list[str] = []
    for skill_path in _skills_dir.iterdir():
        if skill_path.is_dir() and (skill_path / "tools.py").exists():
            try:
                name = _load_single_skill(skill_path)
                if name:
                    loaded.append(name)
            except Exception:
                pass
    return loaded


def _load_single_skill(skill_path: Path) -> str | None:
    """Dynamically import a skill's tools.py and register its tools."""
    tools_file = skill_path / "tools.py"
    if not tools_file.exists():
        return None

    skill_name = skill_path.name
    module_name = f"codag_custom_skill_{skill_name}"

    spec = importlib.util.spec_from_file_location(module_name, tools_file)
    if not spec or not spec.loader:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Register all ToolDefinitions found in the module
    count = 0
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, ToolDefinition):
            _custom_registry.register(attr)
            count += 1

    return f"{skill_name} ({count} tools)" if count > 0 else skill_name


# --- Meta Tools for Agent Self-Expansion ---

@tool(
    name="custom_skills.create",
    tier=RiskTier.SAFE_WRITE,
    description="Create or update a new custom skill with Python tool functions. The Python code must define functions decorated with @tool.",
)
def create_custom_skill(
    skill_name: str,
    description: str,
    python_code: str,
    router_keywords: list[str] | None = None,
) -> ToolResult:
    """Create a new custom skill and load it immediately into the runtime."""
    if not _skills_dir:
        return ToolResult(call_id="", ok=False, content="Custom skills directory not configured.")

    clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", skill_name.strip().lower())
    if not clean_name:
        return ToolResult(call_id="", ok=False, content="Invalid skill name.")

    skill_dir = _skills_dir / clean_name
    skill_dir.mkdir(parents=True, exist_ok=True)

    manifest_file = skill_dir / "manifest.toml"
    tools_file = skill_dir / "tools.py"

    # Write manifest
    kw_list = router_keywords or [clean_name]
    kw_str = ", ".join(f'"{kw}"' for kw in kw_list)
    manifest_content = f"""name = "{clean_name}"
description = "{description.strip()}"
router_keywords = [{kw_str}]
"""
    manifest_file.write_text(manifest_content, encoding="utf-8")

    # If code doesn't import tool, ensure imports are present
    code = python_code.strip()
    required_header = "from codag.skills.base import tool\nfrom codag.core.types import RiskTier, ToolResult\n\n"
    if "from codag.skills.base import tool" not in code and "@tool" in code:
        code = required_header + code

    tools_file.write_text(code, encoding="utf-8")

    # Try loading the newly created skill immediately
    try:
        loaded = _load_single_skill(skill_dir)
        return ToolResult(
            call_id="",
            ok=True,
            content=f"Successfully created and activated custom skill '{clean_name}'. Tools loaded: {loaded}",
        )
    except Exception as exc:
        return ToolResult(
            call_id="",
            ok=False,
            content=f"Created files at {skill_dir}, but encountered error while loading: {exc}",
        )


@tool(
    name="custom_skills.list",
    tier=RiskTier.READ,
    description="List all available custom skills created by or for the user.",
)
def list_custom_skills() -> ToolResult:
    """List all custom skills in ~/.codag/skills/."""
    if not _skills_dir or not _skills_dir.exists():
        return ToolResult(call_id="", ok=True, content="No custom skills directory exists.")

    skills: list[str] = []
    for p in sorted(_skills_dir.iterdir()):
        if p.is_dir() and (p / "tools.py").exists():
            desc = ""
            manifest = p / "manifest.toml"
            if manifest.exists():
                try:
                    with open(manifest, "rb") as f:
                        data = tomllib.load(f)
                        desc = f": {data.get('description', '')}"
                except Exception:
                    pass
            skills.append(f"- **{p.name}**{desc} (`{p}`)")

    if not skills:
        return ToolResult(call_id="", ok=True, content="No custom skills created yet.")

    return ToolResult(
        call_id="",
        ok=True,
        content="Custom Skills:\n" + "\n".join(skills),
    )


@tool(
    name="custom_skills.delete",
    tier=RiskTier.CONFIRM,
    description="Delete a custom skill by name.",
)
def delete_custom_skill(skill_name: str) -> ToolResult:
    """Delete a custom skill directory."""
    if not _skills_dir:
        return ToolResult(call_id="", ok=False, content="Custom skills directory not configured.")

    clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", skill_name.strip().lower())
    target = _skills_dir / clean_name
    if not target.exists() or not target.is_dir():
        return ToolResult(call_id="", ok=False, content=f"Custom skill '{clean_name}' does not exist.")

    try:
        shutil.rmtree(target)
        return ToolResult(call_id="", ok=True, content=f"Deleted custom skill '{clean_name}'.")
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to delete custom skill '{clean_name}': {exc}")


default_registry.register(create_custom_skill)
default_registry.register(list_custom_skills)
default_registry.register(delete_custom_skill)
