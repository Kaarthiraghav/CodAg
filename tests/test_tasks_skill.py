from pathlib import Path
from codag.skills.tasks.tools import add_task, complete_task, configure_tasks, list_tasks


def test_tasks_lifecycle(tmp_path: Path):
    db_file = tmp_path / "tasks.db"
    configure_tasks(db_file)

    # 1. Add tasks
    res1 = add_task("Buy groceries")
    assert res1.ok is True
    assert "#1" in res1.content

    res2 = add_task("Clean workspace")
    assert res2.ok is True
    assert "#2" in res2.content

    # 2. List pending
    list_res = list_tasks("pending")
    assert list_res.ok is True
    assert "Buy groceries" in list_res.content
    assert "Clean workspace" in list_res.content

    # 3. Complete task
    comp_res = complete_task(1)
    assert comp_res.ok is True
    assert "Task #1 marked as completed" in comp_res.content

    # 4. Verify completed list
    comp_list = list_tasks("completed")
    assert "Buy groceries" in comp_list.content
