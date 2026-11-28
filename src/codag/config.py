"""Configuration loader for CodAg using tomllib and pydantic."""

from pathlib import Path
import tomllib
from pydantic import BaseModel, Field


class ModelsConfig(BaseModel):
    main: str = "qwen3.5:9b"
    embedding: str = "nomic-embed-text"
    coder: str = "qwen3.5:9b"


class OllamaConfig(BaseModel):
    host: str = "http://localhost:11434"
    keep_alive: str = "15m"


class GeminiConfig(BaseModel):
    enabled: bool = True
    model: str = "gemini-3.5-flash"
    fallback_models: list[str] = Field(
        default_factory=lambda: ["gemini-3.5-flash-lite", "gemini-3.7-flash", "gemini-3.1-flash-lite", "gemini-3.8-flash"]
    )
    api_key_env: str = "GEMINI_API_KEY"


class OrchestratorConfig(BaseModel):
    mode: str = "auto"  # "auto" | "local" | "gemini"
    planning_skills: list[str] = Field(default_factory=lambda: ["code_plan", "router"])
    heavy_skills: list[str] = Field(
        default_factory=lambda: ["code_exec", "code", "files", "shell", "web", "custom_skills", "knowledge"]
    )
    light_max_chars: int = 10000
    prefer_local_for_private: bool = True


class MainModelConfig(BaseModel):
    temperature: float = 0.3
    num_ctx: int = 8192
    think: bool | None = False


class LimitsConfig(BaseModel):
    max_model_calls_per_turn: int = 8
    max_tool_calls_per_turn: int = 12
    tool_result_max_chars: int = 6000
    command_timeout_s: int = 60


class PathsConfig(BaseModel):
    data_dir: str = "~/.codag"

    @property
    def resolved_data_dir(self) -> Path:
        return Path(self.data_dir).expanduser().resolve()


class WebConfig(BaseModel):
    enabled: bool = True
    search_provider: str = "duckduckgo"
    fetch_max_bytes: int = 2000000


class WorkspacePolicy(BaseModel):
    roots: list[str] = Field(default_factory=lambda: ["~/CodAg/workspace"])
    read_roots: list[str] = Field(default_factory=lambda: ["~/Documents", "~/Downloads", "~/CodAg", "/Volumes"])


class PolicyLimits(BaseModel):
    max_files_per_action: int = 5
    max_bytes_per_write: int = 200000


class DenyPathsPolicy(BaseModel):
    patterns: list[str] = Field(default_factory=lambda: [
        "~/.ssh",
        "~/.aws",
        "~/.gnupg",
        "~/Library/Keychains",
        "~/Library/Application Support/Google/Chrome",
        "**/.env",
        "**/*.pem",
        "**/id_rsa*",
    ])


class ShellPolicy(BaseModel):
    allow: list[str] = Field(default_factory=lambda: [
        "ls", "cat", "pwd", "git status", "git diff", "git log", "python", "pytest", "ruff"
    ])
    forbidden: list[str] = Field(default_factory=lambda: [
        "sudo", "rm -rf /", "mkfs", "dd ", "chmod -R 777", "curl | sh"
    ])


class PolicyConfig(BaseModel):
    workspace: WorkspacePolicy = Field(default_factory=WorkspacePolicy)
    limits: PolicyLimits = Field(default_factory=PolicyLimits)
    deny_paths: DenyPathsPolicy = Field(default_factory=DenyPathsPolicy)
    shell: ShellPolicy = Field(default_factory=ShellPolicy)


class CodagConfig(BaseModel):
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    orchestrator: OrchestratorConfig = Field(default_factory=OrchestratorConfig)
    main: MainModelConfig = Field(default_factory=MainModelConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)


def load_codag_env(data_dir: Path | str | None = None) -> None:
    """Load key=value pairs from ~/.codag/.env into os.environ without overriding existing vars."""
    import os
    env_file = (Path(data_dir).expanduser() if data_dir else Path.home() / ".codag") / ".env"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def load_config(config_dir: Path | str | None = None) -> CodagConfig:
    load_codag_env()
    base_dir = Path(config_dir) if config_dir else Path("config")
    codag_file = base_dir / "codag.toml"
    policy_file = base_dir / "policy.toml"

    codag_data: dict = {}
    if codag_file.is_file():
        with open(codag_file, "rb") as f:
            codag_data = tomllib.load(f)

    policy_data: dict = {}
    if policy_file.is_file():
        with open(policy_file, "rb") as f:
            policy_data = tomllib.load(f)

    if policy_data:
        codag_data["policy"] = policy_data

    return CodagConfig.model_validate(codag_data)
