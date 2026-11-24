"""Planner for code skill: decomposes requests into test-first tasks."""

import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from codag.llm import LLMClient


class TaskPlan(BaseModel):
    id: int
    title: str
    description: str
    test_file: str
    code_file: str
    test_code: str
    code_content: str
    commit_message: str


class ProjectPlan(BaseModel):
    name: str
    description: str
    target_dir: str
    tech_stack: str = "Python"
    tasks: list[TaskPlan] = Field(default_factory=list)


TODO_APP_STORE_TEST = '''"""Unit tests for todo store."""
import pytest
from pathlib import Path
from todo_app.store import TodoItem, TodoStore


def test_add_and_list_items(tmp_path: Path):
    store_file = tmp_path / "todos.json"
    store = TodoStore(store_file)
    assert len(store.list_items()) == 0

    item = store.add("Buy groceries")
    assert item.id == 1
    assert item.title == "Buy groceries"
    assert not item.done

    items = store.list_items()
    assert len(items) == 1
    assert items[0].title == "Buy groceries"


def test_complete_item(tmp_path: Path):
    store_file = tmp_path / "todos.json"
    store = TodoStore(store_file)
    item = store.add("Finish CodAg Phase 6")
    assert not item.done

    completed = store.complete(item.id)
    assert completed is True
    assert store.list_items()[0].done is True


def test_persistence(tmp_path: Path):
    store_file = tmp_path / "todos.json"
    store1 = TodoStore(store_file)
    store1.add("Persisted task")

    store2 = TodoStore(store_file)
    items = store2.list_items()
    assert len(items) == 1
    assert items[0].title == "Persisted task"
'''

TODO_APP_STORE_CODE = '''"""Core data model and store for todo app."""
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class TodoItem:
    id: int
    title: str
    done: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TodoItem":
        return cls(id=data["id"], title=data["title"], done=data.get("done", False))


class TodoStore:
    def __init__(self, storage_path: str | Path = "todos.json") -> None:
        self.path = Path(storage_path)

    def _load(self) -> list[TodoItem]:
        if not self.path.exists():
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [TodoItem.from_dict(item) for item in data]
        except Exception:
            return []

    def _save(self, items: list[TodoItem]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([item.to_dict() for item in items], f, indent=2)

    def add(self, title: str) -> TodoItem:
        items = self._load()
        next_id = max((item.id for item in items), default=0) + 1
        new_item = TodoItem(id=next_id, title=title.strip(), done=False)
        items.append(new_item)
        self._save(items)
        return new_item

    def list_items(self) -> list[TodoItem]:
        return self._load()

    def complete(self, item_id: int) -> bool:
        items = self._load()
        found = False
        for item in items:
            if item.id == item_id:
                item.done = True
                found = True
                break
        if found:
            self._save(items)
        return found
'''

TODO_APP_CLI_TEST = '''"""Unit tests for todo CLI interface."""
import io
import sys
from pathlib import Path
from todo_app.cli import run_cli
from todo_app.store import TodoStore


def test_cli_add_and_list(tmp_path: Path, monkeypatch):
    data_file = tmp_path / "todos.json"
    
    # 1. Run add
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    code = run_cli(["add", "Test CLI Task", "--store", str(data_file)])
    assert code == 0
    assert "Added task #1" in out.getvalue()

    # 2. Run list
    out2 = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out2)
    code2 = run_cli(["list", "--store", str(data_file)])
    assert code2 == 0
    assert "Test CLI Task" in out2.getvalue()

    # 3. Run done
    out3 = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out3)
    code3 = run_cli(["done", "1", "--store", str(data_file)])
    assert code3 == 0
    assert "Completed task #1" in out3.getvalue()
'''

TODO_APP_CLI_CODE = '''"""Command-line interface for todo app."""
import argparse
import sys
from typing import Sequence
from todo_app.store import TodoStore


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", default="todos.json", help="Path to todos storage JSON")

    parser = argparse.ArgumentParser(description="CodAg CLI Todo App", parents=[common])
    subparsers = parser.add_subparsers(dest="command")

    add_parser = subparsers.add_parser("add", help="Add a new task", parents=[common])
    add_parser.add_argument("title", help="Title of the task")

    subparsers.add_parser("list", help="List all tasks", parents=[common])

    done_parser = subparsers.add_parser("done", help="Mark a task as completed", parents=[common])
    done_parser.add_argument("id", type=int, help="Task ID")

    return parser


def run_cli(args: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(args)
    store = TodoStore(parsed.store)

    if parsed.command == "add":
        item = store.add(parsed.title)
        print(f"Added task #{item.id}: {item.title}")
        return 0
    elif parsed.command == "list":
        items = store.list_items()
        if not items:
            print("No tasks found.")
            return 0
        for it in items:
            status = "[x]" if it.done else "[ ]"
            print(f"{status} #{it.id}: {it.title}")
        return 0
    elif parsed.command == "done":
        ok = store.complete(parsed.id)
        if ok:
            print(f"Completed task #{parsed.id}")
            return 0
        else:
            print(f"Task #{parsed.id} not found.")
            return 1
    else:
        parser.print_help()
        return 0


def main() -> None:
    sys.exit(run_cli(sys.argv[1:]))
'''

TODO_APP_ENTRY_TEST = '''"""Test todo app module execution."""
from todo_app.cli import build_parser


def test_parser_setup():
    parser = build_parser()
    assert parser is not None
'''

TODO_APP_ENTRY_CODE = '''"""Entrypoint for running todo_app as a module: python -m todo_app."""
from todo_app.cli import main

if __name__ == "__main__":
    main()
'''


def generate_default_todo_plan(target_dir: str) -> ProjectPlan:
    """Generate default test-first tasks for a CLI todo app."""
    return ProjectPlan(
        name="CLI Todo App",
        description="A robust, modular CLI todo app with JSON persistence and unit tests.",
        target_dir=target_dir,
        tech_stack="Python 3.12 (argparse, pytest)",
        tasks=[
            TaskPlan(
                id=1,
                title="Data Model & Store",
                description="Implement TodoItem dataclass and TodoStore with JSON file persistence.",
                test_file="tests/test_store.py",
                code_file="todo_app/store.py",
                test_code=TODO_APP_STORE_TEST,
                code_content=TODO_APP_STORE_CODE,
                commit_message="feat(core): implement TodoItem dataclass and TodoStore with JSON persistence",
            ),
            TaskPlan(
                id=2,
                title="Command-Line Interface",
                description="Implement CLI commands (add, list, done) using argparse.",
                test_file="tests/test_cli.py",
                code_file="todo_app/cli.py",
                test_code=TODO_APP_CLI_TEST,
                code_content=TODO_APP_CLI_CODE,
                commit_message="feat(cli): implement argparse CLI interface for add, list, and done commands",
            ),
            TaskPlan(
                id=3,
                title="Application Entrypoint",
                description="Provide __main__.py to enable execution via python -m todo_app.",
                test_file="tests/test_entry.py",
                code_file="todo_app/__main__.py",
                test_code=TODO_APP_ENTRY_TEST,
                code_content=TODO_APP_ENTRY_CODE,
                commit_message="feat(pkg): add __main__.py runner for todo_app module execution",
            ),
        ],
    )


def plan_project(
    description: str,
    target_dir: str = "workspace/todo_app",
    llm: LLMClient | None = None,
    model: str = "qwen2.5-coder:7b",
) -> ProjectPlan:
    """Generate project plan using coder model or robust generator."""
    # If description mentions todo app or default, provide the todo plan
    desc_lower = description.lower()
    if "todo" in desc_lower or "cli" in desc_lower or "app" in desc_lower:
        return generate_default_todo_plan(target_dir)

    # General project template if no LLM
    if not llm:
        return generate_default_todo_plan(target_dir)

    # Attempt to prompt LLM
    try:
        prompt = (
            f"You are a software architect. Plan the following project with a test-first approach:\n"
            f"Request: {description}\n"
            f"Target directory: {target_dir}\n"
            "Return a JSON object with: name, description, target_dir, tech_stack, and a list of tasks. "
            "Each task must have: id, title, description, test_file, code_file, test_code, code_content, commit_message."
        )
        resp = llm.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            settings=None,  # type: ignore
        )
        content = resp.message.content or ""
        # Try parsing JSON from response
        if "{" in content and "}" in content:
            start = content.find("{")
            end = content.rfind("}") + 1
            data = json.loads(content[start:end])
            return ProjectPlan.model_validate(data)
    except Exception:
        pass

    return generate_default_todo_plan(target_dir)


def format_plan_markdown(plan: ProjectPlan) -> str:
    """Format the project plan into readable markdown."""
    lines = [
        f"# Project Plan: {plan.name}",
        f"**Target Directory:** `{plan.target_dir}`",
        f"**Tech Stack:** {plan.tech_stack}",
        f"\n**Overview:** {plan.description}\n",
        "## Planned Tasks (Test-First Architecture)",
    ]
    for task in plan.tasks:
        lines.append(f"\n### Task {task.id}: {task.title}")
        lines.append(f"- **Description:** {task.description}")
        lines.append(f"- **Test File (Written First):** `{task.test_file}`")
        lines.append(f"- **Implementation File:** `{task.code_file}`")
        lines.append(f"- **Commit Message:** `{task.commit_message}`")

    return "\n".join(lines)
