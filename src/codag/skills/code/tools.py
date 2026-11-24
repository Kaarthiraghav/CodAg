"""Tools for the code skill: plan_project and build_project."""

from pathlib import Path
from typing import Any

from codag.core.types import RiskTier, ToolResult
from codag.llm import LLMClient
from codag.safety.audit import AuditLogger
from codag.safety.sandbox import Sandbox, SandboxError
from codag.safety.snapshots import SnapshotManager
from codag.skills.base import tool
from codag.skills.code.executor import execute_build
from codag.skills.code.planner import (
    ProjectPlan,
    format_plan_markdown,
    plan_project as planner_plan_project,
)
from codag.skills.registry import default_registry


class CodeEnvironment:
    def __init__(
        self,
        sandbox: Sandbox | None = None,
        audit: AuditLogger | None = None,
        snapshots: SnapshotManager | None = None,
        llm: LLMClient | None = None,
        coder_model: str = "qwen2.5-coder:7b",
        main_model: str = "qwen3.5:9b",
    ) -> None:
        self.sandbox = sandbox
        self.audit = audit
        self.snapshots = snapshots
        self.llm = llm
        self.coder_model = coder_model
        self.main_model = main_model


_code_env = CodeEnvironment()


def configure_code(
    sandbox: Sandbox,
    audit: AuditLogger | None = None,
    snapshots: SnapshotManager | None = None,
    llm: LLMClient | None = None,
    coder_model: str = "qwen2.5-coder:7b",
    main_model: str = "qwen3.5:9b",
) -> None:
    global _code_env
    _code_env.sandbox = sandbox
    _code_env.audit = audit
    _code_env.snapshots = snapshots
    _code_env.llm = llm
    _code_env.coder_model = coder_model
    _code_env.main_model = main_model


@tool(
    name="code.plan_project",
    tier=RiskTier.SAFE_WRITE,
    description="Plan a software project by decomposing requirements into test-first implementation tasks.",
)
def plan_project(
    description: str,
    target_dir: str = "workspace/todo_app",
) -> ToolResult:
    """Generate a structured, test-first development plan for a project."""
    try:
        plan = planner_plan_project(
            description=description,
            target_dir=target_dir,
            llm=_code_env.llm,
            model=_code_env.coder_model,
        )
        md = format_plan_markdown(plan)
        return ToolResult(
            call_id="",
            ok=True,
            content=md,
        )
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Failed to plan project: {exc}")


@tool(
    name="code.build_project",
    tier=RiskTier.CONFIRM,
    description="Build a software project end-to-end with tests and git-per-task commits (CONFIRM tier).",
)
def build_project(
    description: str = "build a small CLI todo app",
    target_dir: str = "workspace/todo_app",
    plan: str = "",
) -> ToolResult:
    """Build a project following test-first convention, self-healing, and git-per-task commits."""
    if not _code_env.sandbox:
        return ToolResult(call_id="", ok=False, content="Code environment not configured with sandbox.")

    try:
        # Generate plan
        project_plan = planner_plan_project(
            description=description,
            target_dir=target_dir,
            llm=_code_env.llm,
            model=_code_env.coder_model,
        )

        build_res = execute_build(
            plan=project_plan,
            sandbox=_code_env.sandbox,
            audit=_code_env.audit,
            snapshots=_code_env.snapshots,
            llm=_code_env.llm,
            model=_code_env.coder_model,
        )

        return ToolResult(
            call_id="",
            ok=build_res.ok,
            content=build_res.message,
        )
    except SandboxError as sbe:
        return ToolResult(call_id="", ok=False, content=f"Sandbox error: {sbe}")
    except Exception as exc:
        return ToolResult(call_id="", ok=False, content=f"Build failed: {exc}")


# Auto-register tools
default_registry.register(plan_project)
default_registry.register(build_project)
