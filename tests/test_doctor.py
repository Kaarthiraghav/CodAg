from typer.testing import CliRunner
from codag.cli import app

runner = CliRunner()


def test_doctor_command():
    result = runner.invoke(app, ["doctor"])
    assert "CodAg Doctor Checkup" in result.output
    assert "Python Runtime" in result.output
    assert "Ollama Service" in result.output
