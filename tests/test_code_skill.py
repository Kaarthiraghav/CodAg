"""Tests for the code skill: planner, executor, permissions, and tool registration."""

import subprocess
import sys
from pathlib import Path

import pytest

from codag.config import CodagConfig, PolicyConfig
from codag.core.router import SkillRouter
from codag.core.types import RiskTier, ToolCall, TurnContext
from codag.safety.audit import AuditLogger
from codag.safety.permissions import PermissionEngine
from codag.safety.sandbox import Sandbox
from codag.safety.snapshots import SnapshotManager
from codag.skills.code.executor import execute_build
from codag.skills.code.planner import (
    ProjectPlan,
    format_plan_markdown,
    generate_default_todo_plan,
    plan_project,
)
from codag.skills.code.tools import configure_code
from codag.skills.registry import default_registry


def test_code_tools_registered():
    plan_spec = default_registry.get_spec("code.plan_project")
    build_spec = default_registry.get_spec("code.build_project")

    assert plan_spec is not None
    assert plan_spec.base_tier == RiskTier.SAFE_WRITE
    assert plan_spec.skill == "code"

    assert build_spec is not None
    assert build_spec.base_tier == RiskTier.CONFIRM
    assert build_spec.skill == "code"


def test_code_planner_default():
    plan = generate_default_todo_plan(target_dir="workspace/test_todo")
    assert plan.name == "CLI Todo App"
    assert len(plan.tasks) >= 3

    # Check test-first structure
    for t in plan.tasks:
        assert t.test_file.startswith("tests/")
        assert t.code_file.startswith("todo_app/")
        assert len(t.test_code) > 0
        assert len(t.code_content) > 0
        assert len(t.commit_message) > 0


def test_format_plan_markdown():
    plan = generate_default_todo_plan(target_dir="workspace/my_app")
    md = format_plan_markdown(plan)
    assert "# Project Plan: CLI Todo App" in md
    assert "Task 1:" in md
    assert "Test File (Written First):" in md


def test_code_router_keyword_matching():
    router = SkillRouter()
    assert router.route_fast_path("build a small CLI todo app") == "code"
    assert router.route_fast_path("plan project for a microservice") == "code"
    assert router.route_fast_path("write code for an app") == "code"
    assert router.route_fast_path("create project for cli app") == "code"


def test_code_build_permission_requires_confirm(tmp_path: Path):
    policy = PolicyConfig()
    policy.workspace.roots = [str(tmp_path)]
    sandbox = Sandbox(policy)
    permissions = PermissionEngine(policy, sandbox)

    spec = default_registry.get_spec("code.build_project")
    assert spec is not None

    call = ToolCall(
        id="c1",
        name="code.build_project",
        arguments={"description": "build a small CLI todo app", "target_dir": str(tmp_path / "todo_app")},
    )
    decision = permissions.decide(call, spec, TurnContext(turn_id="t1"))
    assert decision.action == "ask"
    assert decision.tier == RiskTier.CONFIRM


def test_execute_build_end_to_end(tmp_path: Path):
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir(parents=True, exist_ok=True)
    target_dir = ws_dir / "todo_app"

    policy = PolicyConfig()
    policy.workspace.roots = [str(ws_dir)]
    sandbox = Sandbox(policy)
    audit = AuditLogger(tmp_path / ".codag")
    snapshots = SnapshotManager(tmp_path / ".codag")

    plan = generate_default_todo_plan(target_dir=str(target_dir))
    result = execute_build(
        plan=plan,
        sandbox=sandbox,
        audit=audit,
        snapshots=snapshots,
    )

    assert result.ok is True
    assert result.tasks_completed == len(plan.tasks)
    assert (target_dir / ".git").exists()
    assert (target_dir / "tests" / "test_store.py").exists()
    assert (target_dir / "todo_app" / "store.py").exists()
    assert (target_dir / "PLAN.md").exists()
    assert (target_dir / "README.md").exists()

    # Verify git commits were created
    log_proc = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=target_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "feat(core):" in log_proc.stdout
    assert "feat(cli):" in log_proc.stdout

    # Verify all tests pass inside the newly built project
    test_run = subprocess.run(
        [sys.executable, "-m", "pytest", "tests"],
        cwd=target_dir,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(target_dir)},
    )
    assert test_run.returncode == 0
    assert "passed" in test_run.stdout
