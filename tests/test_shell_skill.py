from pathlib import Path
from codag.skills.shell.tools import configure_shell, run_command


def test_shell_operator_rejection():
    res = run_command("ls ; cat /etc/passwd")
    assert res.ok is False
    assert "prohibited shell operator ';'" in res.content

    res2 = run_command("pytest && rm -rf /")
    assert res2.ok is False
    assert "prohibited shell operator '&&'" in res2.content

    res3 = run_command("echo hello | grep h")
    assert res3.ok is False
    assert "prohibited shell operator '|'" in res3.content


def test_shell_valid_execution(tmp_path: Path):
    configure_shell(tmp_path)
    res = run_command("pwd")
    assert res.ok is True
    assert str(tmp_path) in res.content
