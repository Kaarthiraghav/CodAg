"""Filesystem sandbox, path resolution, and boundary enforcement."""

import fnmatch
from pathlib import Path

from codag.config import PolicyConfig


class SandboxError(Exception):
    """Raised when a path violates sandbox constraints."""


class Sandbox:
    def __init__(self, policy: PolicyConfig) -> None:
        self.policy = policy
        self.workspace_roots = [
            Path(r).expanduser().resolve() for r in policy.workspace.roots
        ]
        self.read_roots = [
            Path(r).expanduser().resolve() for r in policy.workspace.read_roots
        ]
        self.deny_patterns = policy.deny_paths.patterns

    def add_workspace_root(self, path: str | Path) -> Path:
        """Add a dynamic workspace root (e.g. active project workspace)."""
        resolved = self.resolve_path(path)
        if resolved not in self.workspace_roots:
            self.workspace_roots.append(resolved)
        if resolved not in self.read_roots:
            self.read_roots.append(resolved)
        return resolved

    def add_read_root(self, path: str | Path) -> Path:
        """Add a dynamic read root (e.g. user-specified folder or drive)."""
        resolved = self.resolve_path(path)
        if resolved not in self.read_roots:
            self.read_roots.append(resolved)
        return resolved

    def resolve_path(self, path: str | Path) -> Path:
        """Resolve path to absolute real path, resolving symlinks and volume aliases."""
        raw = Path(path).expanduser()

        # Check volume aliasing on macOS if path doesn't exist directly
        if not raw.exists():
            path_str = str(raw)
            vol_dir = Path("/Volumes")
            if vol_dir.is_dir():
                try:
                    for v in vol_dir.iterdir():
                        if v.name in ("Recovery", "Macintosh HD"):
                            continue
                        v_lower = v.name.lower()
                        if v_lower in path_str.lower():
                            idx = path_str.lower().find(v_lower)
                            sub = path_str[idx:]
                            parts = sub.split("/", 1)
                            rest = parts[1] if len(parts) > 1 else ""
                            cand = (v / rest) if rest else v
                            if cand.exists():
                                raw = cand
                                break
                except Exception:
                    pass

        try:
            return raw.resolve(strict=False)
        except Exception as exc:
            raise SandboxError(f"Cannot resolve path {path!r}: {exc}") from exc

    def is_denied(self, resolved: Path) -> bool:
        """Check whether path matches any deny patterns."""
        path_str = str(resolved)
        home_str = str(Path.home())
        
        candidates = [path_str]
        if path_str.startswith(home_str):
            candidates.append("~" + path_str[len(home_str):])

        for pat in self.deny_patterns:
            expanded_pat = str(Path(pat).expanduser())
            # Check if resolved is inside pattern directory (e.g. ~/.ssh or ~/.aws)
            try:
                exp_p = Path(pat).expanduser().resolve()
                resolved.relative_to(exp_p)
                return True
            except (ValueError, RuntimeError):
                pass

            for cand in candidates:
                if fnmatch.fnmatch(cand, pat) or fnmatch.fnmatch(cand, expanded_pat):
                    return True
                if fnmatch.fnmatch(cand, pat.rstrip("/") + "/*") or fnmatch.fnmatch(cand, expanded_pat.rstrip("/") + "/*"):
                    return True
                for part in resolved.parts:
                    if fnmatch.fnmatch(part, pat):
                        return True
        return False

    def is_in_workspace(self, resolved: Path) -> bool:
        """Check whether path is inside any allowed workspace root."""
        for root in self.workspace_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def is_in_read_roots(self, resolved: Path) -> bool:
        """Check whether path is inside any allowed read root (or workspace root)."""
        if self.is_in_workspace(resolved):
            return True
        for root in self.read_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def check_read(self, path: str | Path) -> Path:
        """Validate path for read operation."""
        resolved = self.resolve_path(path)
        if self.is_denied(resolved):
            raise SandboxError(f"Access to path is forbidden by policy: {path!r}")
        if not self.is_in_read_roots(resolved):
            raise SandboxError(f"Path is outside allowed read roots: {path!r}")
        return resolved

    def check_write(self, path: str | Path) -> tuple[Path, bool]:
        """Validate path for write operation.
        
        Returns (resolved_path, in_workspace).
        """
        resolved = self.resolve_path(path)
        if self.is_denied(resolved):
            raise SandboxError(f"Access to path is forbidden by policy: {path!r}")
        
        in_workspace = self.is_in_workspace(resolved)
        return resolved, in_workspace
