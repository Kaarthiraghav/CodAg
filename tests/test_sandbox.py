from pathlib import Path
import pytest
from codag.config import PolicyConfig
from codag.safety.sandbox import Sandbox, SandboxError


def test_sandbox_path_resolution(tmp_path: Path):
    policy = PolicyConfig()
    policy.workspace.roots = [str(tmp_path / "workspace")]
    policy.workspace.read_roots = [str(tmp_path / "docs")]
    sandbox = Sandbox(policy)

    ws_file = tmp_path / "workspace" / "sub" / "file.txt"
    resolved = sandbox.resolve_path(ws_file)
    assert resolved == ws_file.resolve()


def test_sandbox_escape_attempt(tmp_path: Path):
    policy = PolicyConfig()
    ws = tmp_path / "workspace"
    ws.mkdir()
    policy.workspace.roots = [str(ws)]
    policy.workspace.read_roots = []
    sandbox = Sandbox(policy)

    # Path outside workspace
    outside = tmp_path / "secret.txt"
    with pytest.raises(SandboxError, match="outside allowed read roots"):
        sandbox.check_read(outside)


def test_sandbox_deny_paths(tmp_path: Path):
    policy = PolicyConfig()
    policy.workspace.roots = [str(tmp_path)]
    policy.workspace.read_roots = [str(tmp_path)]
    policy.deny_paths.patterns = ["**/.env", "~/.ssh", "**/*.pem"]
    sandbox = Sandbox(policy)

    env_file = tmp_path / ".env"
    with pytest.raises(SandboxError, match="forbidden by policy"):
        sandbox.check_read(env_file)

    pem_file = tmp_path / "certs" / "key.pem"
    with pytest.raises(SandboxError, match="forbidden by policy"):
        sandbox.check_write(pem_file)


def test_sandbox_symlink_traversal(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    secret_dir = tmp_path / "hidden"
    secret_dir.mkdir()
    secret_file = secret_dir / "passwords.txt"
    secret_file.write_text("secret")

    # Create symlink inside workspace pointing outside
    link = ws / "leak.txt"
    link.symlink_to(secret_file)

    policy = PolicyConfig()
    policy.workspace.roots = [str(ws)]
    policy.workspace.read_roots = []
    sandbox = Sandbox(policy)

    # Resolving symlink should reveal it is outside read roots
    with pytest.raises(SandboxError, match="outside allowed read roots"):
        sandbox.check_read(link)
