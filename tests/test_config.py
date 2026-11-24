from pathlib import Path
from codag.config import CodagConfig, load_config


def test_default_config():
    cfg = CodagConfig()
    assert cfg.models.main == "qwen3.5:9b"
    assert cfg.models.embedding == "nomic-embed-text"
    assert cfg.models.coder == "qwen3.5:9b"
    assert cfg.ollama.host == "http://localhost:11434"
    assert cfg.main.temperature == 0.3
    assert cfg.main.num_ctx == 8192
    assert cfg.limits.max_model_calls_per_turn == 8
    assert cfg.policy.limits.max_files_per_action == 5
    assert "sudo" in cfg.policy.shell.forbidden


def test_load_config_from_dir(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "codag.toml").write_text("""
[models]
main = "custom-main"
embedding = "custom-embed"
coder = "custom-coder"
""", encoding="utf-8")
    (config_dir / "policy.toml").write_text("""
[limits]
max_files_per_action = 10
""", encoding="utf-8")

    cfg = load_config(config_dir)
    assert cfg.models.main == "custom-main"
    assert cfg.models.embedding == "custom-embed"
    assert cfg.policy.limits.max_files_per_action == 10
