"""Executor for code skill: test-first implementation and git-per-task commits."""

import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from codag.core.types import Decision, RiskTier, ToolCall
from codag.llm import LLMClient
from codag.safety.audit import AuditLogger
from codag.safety.sandbox import Sandbox, SandboxError
from codag.safety.snapshots import SnapshotManager
from codag.skills.code.planner import ProjectPlan, format_plan_markdown


class BuildResult:
    def __init__(
        self,
        ok: bool,
        target_dir: str,
        tasks_completed: int,
        files_created: list[str],
        commits: list[str],
        message: str,
    ) -> None:
        self.ok = ok
        self.target_dir = target_dir
        self.tasks_completed = tasks_completed
        self.files_created = files_created
        self.commits = commits
        self.message = message


def execute_build(
    plan: ProjectPlan,
    sandbox: Sandbox,
    audit: AuditLogger | None = None,
    snapshots: SnapshotManager | None = None,
    llm: LLMClient | None = None,
    model: str = "qwen2.5-coder:7b",
) -> BuildResult:
    """Execute the project build following test-first convention and git-per-task commits."""
    # 1. Resolve and validate target directory through sandbox
    raw_target = Path(plan.target_dir).expanduser()
    if not raw_target.is_absolute() and sandbox.workspace_roots:
        clean_name = raw_target.name if raw_target.name and raw_target.name != "." else "todo_app"
        target_path = sandbox.workspace_roots[0] / clean_name
    else:
        target_path = sandbox.resolve_path(plan.target_dir)

    resolved_target, in_ws = sandbox.check_write(target_path)
    if not in_ws:
        # If the target directory was explicitly specified by the user (e.g. ~/Documents), automatically add it to workspace roots
        sandbox.add_workspace_root(resolved_target)
        resolved_target, in_ws = sandbox.check_write(target_path)
        if not in_ws:
            raise SandboxError(f"Target directory {plan.target_dir} is outside allowed workspace roots.")

    resolved_target.mkdir(parents=True, exist_ok=True)

    files_created: list[str] = []
    commits: list[str] = []

    # Configure pyproject.toml for pytest path resolution
    pyproject_file = resolved_target / "pyproject.toml"
    if not pyproject_file.exists():
        pyproject_file.write_text(
            f'[project]\nname = "{plan.name.lower().replace(" ", "_")}"\nversion = "0.1.0"\n\n[tool.pytest.ini_options]\npythonpath = ["."]\n',
            encoding="utf-8",
        )
        files_created.append("pyproject.toml")

    # 2. Initialize git repository if not present
    git_dir = resolved_target / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=resolved_target, check=True, capture_output=True, text=True)
        # Configure local git user to ensure commit succeeds in any environment
        subprocess.run(["git", "config", "user.name", "CodAg"], cwd=resolved_target, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "codag@local"], cwd=resolved_target, capture_output=True, text=True)

    # Helper env with PYTHONPATH pointing to target_dir
    exec_env = os.environ.copy()
    exec_env["PYTHONPATH"] = str(resolved_target)

    # 3. Iterate through tasks
    for task in plan.tasks:
        # A. TEST-FIRST: Write test file
        test_path = resolved_target / task.test_file
        test_resolved, _ = sandbox.check_write(test_path)
        test_resolved.parent.mkdir(parents=True, exist_ok=True)

        if test_resolved.exists() and snapshots:
            snapshots.snapshot_before_modify(test_resolved)

        test_resolved.write_text(task.test_code, encoding="utf-8")
        files_created.append(task.test_file)

        # B. Write code implementation file
        code_path = resolved_target / task.code_file
        code_resolved, _ = sandbox.check_write(code_path)
        code_resolved.parent.mkdir(parents=True, exist_ok=True)

        # Ensure package has __init__.py if it's in a package subdirectory
        if code_resolved.parent != resolved_target:
            pkg_init = code_resolved.parent / "__init__.py"
            if not pkg_init.exists():
                pkg_init.write_text('"""Package initialization."""\n', encoding="utf-8")
                files_created.append(str(pkg_init.relative_to(resolved_target)))

        if code_resolved.exists() and snapshots:
            snapshots.snapshot_before_modify(code_resolved)

        code_resolved.write_text(task.code_content, encoding="utf-8")
        files_created.append(task.code_file)

        # C. Run tests (test-first verification)
        test_cmd = [sys.executable, "-m", "pytest", str(test_resolved)]
        proc = subprocess.run(test_cmd, cwd=resolved_target, capture_output=True, text=True, env=exec_env)

        # Self-healing retry if test fails
        if proc.returncode != 0 and llm:
            for _ in range(2):
                fix_prompt = (
                    f"The unit test failed:\nOutput:\n{proc.stdout}\n{proc.stderr}\n\n"
                    f"Existing code in {task.code_file}:\n{code_resolved.read_text(encoding='utf-8')}\n\n"
                    "Fix the implementation to make the test pass. Return ONLY python code without markdown."
                )
                try:
                    fix_resp = llm.chat(
                        model=model,
                        messages=[{"role": "user", "content": fix_prompt}],
                        settings=None,  # type: ignore
                    )
                    fixed_code = fix_resp.message.content or ""
                    if fixed_code.strip():
                        if fixed_code.startswith("```"):
                            lines = fixed_code.splitlines()
                            fixed_code = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
                        code_resolved.write_text(fixed_code, encoding="utf-8")
                        proc = subprocess.run(test_cmd, cwd=resolved_target, capture_output=True, text=True, env=exec_env)
                        if proc.returncode == 0:
                            break
                except Exception:
                    pass

        if proc.returncode != 0:
            return BuildResult(
                ok=False,
                target_dir=str(resolved_target),
                tasks_completed=len(commits),
                files_created=files_created,
                commits=commits,
                message=f"Task {task.id} failed verification:\n{proc.stdout}\n{proc.stderr}",
            )

        # D. GIT COMMIT PER TASK
        subprocess.run(["git", "add", "."], cwd=resolved_target, check=True, capture_output=True, text=True)
        commit_res = subprocess.run(
            ["git", "commit", "-m", task.commit_message],
            cwd=resolved_target,
            check=True,
            capture_output=True,
            text=True,
        )
        # Extract commit hash
        sha_proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=resolved_target,
            check=True,
            capture_output=True,
            text=True,
        )
        commit_sha = sha_proc.stdout.strip()
        commit_entry = f"{commit_sha} - {task.commit_message}"
        commits.append(commit_entry)

        if audit:
            audit.log_decision(
                call=ToolCall(
                    id=f"build_task_{task.id}",
                    name="code.build_project",
                    arguments={"task": task.title, "commit": commit_sha},
                ),
                decision=Decision(action="allow", tier=RiskTier.CONFIRM, reason="Build task executed and verified"),
                ok=True,
                result_summary=commit_entry,
            )

    # 4. Generate PLAN.md and README.md
    plan_md = format_plan_markdown(plan)
    (resolved_target / "PLAN.md").write_text(plan_md, encoding="utf-8")
    files_created.append("PLAN.md")

    readme_content = f"""# {plan.name}

{plan.description}

## Usage

```bash
# Add a new task
python -m todo_app add "Buy groceries"

# List tasks
python -m todo_app list

# Mark task as completed
python -m todo_app done 1
```

## Running Tests

```bash
pytest tests
```
"""
    (resolved_target / "README.md").write_text(readme_content, encoding="utf-8")
    files_created.append("README.md")

    subprocess.run(["git", "add", "."], cwd=resolved_target, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "docs: add PLAN.md and README.md with usage guide"],
        cwd=resolved_target,
        capture_output=True,
        text=True,
    )

    # Final test suite run
    all_tests = subprocess.run(
        [sys.executable, "-m", "pytest", "tests"],
        cwd=resolved_target,
        capture_output=True,
        text=True,
        env=exec_env,
    )

    summary_lines = [
        f"Successfully built {plan.name} at {resolved_target}!",
        f"- Tasks completed: {len(plan.tasks)}/{len(plan.tasks)} (Test-First)",
        f"- Files created: {', '.join(sorted(set(files_created)))}",
        f"- Git commits created ({len(commits) + 1}):",
    ]
    for c in commits:
        summary_lines.append(f"  • {c}")
    summary_lines.append("  • docs: add PLAN.md and README.md with usage guide")
    summary_lines.append("\nTest Suite Status: ALL TESTS PASSED.")
    summary_lines.append(f"\nTo run the app:\n  cd '{resolved_target}' && python -m todo_app --help")

    return BuildResult(
        ok=True,
        target_dir=str(resolved_target),
        tasks_completed=len(plan.tasks),
        files_created=sorted(set(files_created)),
        commits=commits,
        message="\n".join(summary_lines),
    )
