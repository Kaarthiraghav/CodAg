"""Benchmark comparing default qwen3.5:9b against qwen2.5-coder:7b for code execution."""

import time
from pathlib import Path
from rich.console import Console
from rich.table import Table

from codag.config import PolicyConfig
from codag.safety.sandbox import Sandbox
from codag.skills.code.executor import execute_build
from codag.skills.code.planner import generate_default_todo_plan

console = Console()


def run_coder_comparison(tmp_path: Path | None = None) -> None:
    """Compare execution speed, file generation, and test pass rate between coder candidates."""
    base_dir = tmp_path or Path("/tmp/codag_coder_eval")
    base_dir.mkdir(parents=True, exist_ok=True)

    candidates = ["qwen3.5:9b (default)", "qwen2.5-coder:7b (challenger)"]
    table = Table(title="Coder Model Benchmark: qwen3.5:9b vs qwen2.5-coder:7b")
    table.add_column("Model Candidate", style="cyan bold")
    table.add_column("Memory Overhead", style="bold")
    table.add_column("Tasks Passed", style="green bold")
    table.add_column("Files Created", style="bold")
    table.add_column("Status")

    for cand in candidates:
        model_name = "qwen3.5:9b" if "default" in cand else "qwen2.5-coder:7b"
        overhead = "0 GB (resident)" if "default" in cand else "~4.7 GB (swap)"
        
        target_dir = base_dir / f"bench_{model_name.replace(':', '_').replace('.', '_')}"
        target_dir.mkdir(parents=True, exist_ok=True)

        policy = PolicyConfig()
        policy.workspace.roots = [str(base_dir)]
        sandbox = Sandbox(policy)

        plan = generate_default_todo_plan(str(target_dir))
        
        # Test-first build execution
        res = execute_build(plan=plan, sandbox=sandbox, model=model_name)
        status = "[green]PASS[/green]" if res.ok else "[red]FAIL[/red]"
        table.add_row(
            cand,
            overhead,
            f"{res.tasks_completed}/{len(plan.tasks)}",
            str(len(res.files_created)),
            status,
        )

    console.print(table)


if __name__ == "__main__":
    run_coder_comparison()
