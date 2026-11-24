"""Policy rules and risk escalation logic."""

from pathlib import Path
from typing import Any

from codag.config import PolicyConfig
from codag.core.types import RiskTier, ToolCall, ToolSpec
from codag.safety.sandbox import Sandbox


class PolicyEngine:
    def __init__(self, policy: PolicyConfig, sandbox: Sandbox | None = None) -> None:
        self.policy = policy
        self.sandbox = sandbox or Sandbox(policy)

    def is_forbidden(self, call: ToolCall, spec: ToolSpec) -> tuple[bool, str]:
        """Check whether the tool call violates hard forbidden constraints."""
        args = call.arguments

        # 1. Check path arguments against deny list
        for key in ("path", "source", "destination", "directory", "file"):
            if key in args and isinstance(args[key], str):
                resolved = self.sandbox.resolve_path(args[key])
                if self.sandbox.is_denied(resolved):
                    return True, f"Path {args[key]!r} matches forbidden deny pattern."

        # 2. Check shell commands
        if "shell" in call.name or "run" in call.name:
            cmd = args.get("command", "") or args.get("cmd", "")
            if isinstance(cmd, str):
                for bad in self.policy.shell.forbidden:
                    if bad in cmd:
                        return True, f"Shell command contains forbidden pattern: {bad!r}"

        return False, ""

    def escalate(self, call: ToolCall, spec: ToolSpec) -> tuple[RiskTier, str]:
        """Determine whether the tool call must be escalated to a higher risk tier."""
        tier = spec.base_tier
        reason = ""
        args = call.arguments

        # 1. File actions that inherently require confirmation
        if call.name in {"files.delete_file", "files.move_file"}:
            return RiskTier.CONFIRM, f"Action {call.name} requires confirmation."

        # 2. Overwriting an existing file or writing outside workspace
        if call.name in {"files.create_file", "files.edit_file"}:
            path_val = args.get("path")
            if path_val and isinstance(path_val, str):
                resolved = self.sandbox.resolve_path(path_val)
                # Outside workspace escalates to CONFIRM
                if not self.sandbox.is_in_workspace(resolved):
                    return RiskTier.CONFIRM, f"File {path_val!r} is outside workspace roots."

                # If creating a file that already exists, it is an overwrite
                if call.name == "files.create_file" and resolved.exists():
                    return RiskTier.CONFIRM, f"File {path_val!r} already exists and will be overwritten."

            # Size limit check
            content = args.get("content", "")
            if isinstance(content, str) and len(content.encode("utf-8")) > self.policy.limits.max_bytes_per_write:
                return RiskTier.CONFIRM, f"Content size exceeds max_bytes_per_write limit."

        # 3. File count check (e.g. if a tool takes a list of files)
        files_list = args.get("files") or args.get("paths")
        if isinstance(files_list, list) and len(files_list) > self.policy.limits.max_files_per_action:
            return RiskTier.CONFIRM, f"Action affects {len(files_list)} files, exceeding limit of {self.policy.limits.max_files_per_action}."

        # 4. Shell commands: must match allowlist to remain safe
        if "shell" in call.name:
            cmd = args.get("command", "") or args.get("cmd", "")
            if isinstance(cmd, str):
                tokens = cmd.strip().split()
                first_token = tokens[0] if tokens else ""
                if first_token not in self.policy.shell.allow:
                    return RiskTier.CONFIRM, f"Shell command {first_token!r} is not on allowlist."

        return tier, reason
