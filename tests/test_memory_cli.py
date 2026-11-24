from pathlib import Path
from typer.testing import CliRunner
from codag.cli import app
from codag.config import CodagConfig
from codag.memory.store import MemoryStore

runner = CliRunner()


def test_cli_memory_commands(tmp_path: Path):
    # Setup custom config directory
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (cfg_dir / "codag.toml").write_text(f'[paths]\ndata_dir = "{data_dir}"\n', encoding="utf-8")

    # Seed fact directly into store
    store = MemoryStore(data_dir / "memory.db")
    store.add_or_update_fact("machine", "Mac Mini M4", "system")

    # 1. codag memory list
    res_list = runner.invoke(app, ["memory", "list", "--config-dir", str(cfg_dir)])
    assert res_list.exit_code == 0
    assert "Mac Mini M4" in res_list.output
    assert "machine" in res_list.output

    # 2. codag memory export
    res_exp = runner.invoke(app, ["memory", "export", "--format", "json", "--config-dir", str(cfg_dir)])
    assert res_exp.exit_code == 0
    assert '"key": "machine"' in res_exp.output

    # 3. codag memory forget
    res_forg = runner.invoke(app, ["memory", "forget", "machine", "--config-dir", str(cfg_dir)])
    assert res_forg.exit_code == 0
    assert "Permanently forgot" in res_forg.output
    assert store.get_fact_by_key("machine") is None
