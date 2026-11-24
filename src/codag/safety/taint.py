"""Untrusted content and context taint tracking."""

from codag.core.types import TurnContext


class TaintTracker:
    @staticmethod
    def mark_tainted(ctx: TurnContext, reason: str = "") -> None:
        """Mark context as tainted due to external untrusted content."""
        ctx.tainted = True

    @staticmethod
    def reset(ctx: TurnContext) -> None:
        """Reset context taint state."""
        ctx.tainted = False
