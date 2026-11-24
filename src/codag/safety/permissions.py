"""Permission engine deciding allow, ask, or deny."""

from codag.config import PolicyConfig
from codag.core.types import Decision, RiskTier, ToolCall, ToolSpec, TurnContext
from codag.safety.policy import PolicyEngine
from codag.safety.sandbox import Sandbox


class PermissionEngine:
    def __init__(
        self,
        policy: PolicyConfig,
        sandbox: Sandbox | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self.policy = policy
        self.sandbox = sandbox or Sandbox(policy)
        self.policy_engine = policy_engine or PolicyEngine(policy, self.sandbox)

    def decide(self, call: ToolCall, spec: ToolSpec, ctx: TurnContext) -> Decision:
        """Single deterministic gate through which every tool call must pass."""
        # 1. Check forbidden conditions
        forbidden, forbidden_reason = self.policy_engine.is_forbidden(call, spec)
        if forbidden:
            return Decision(action="deny", tier=RiskTier.FORBIDDEN, reason=forbidden_reason)

        # 2. Check risk tier and escalation
        tier = spec.base_tier
        escalated_tier, escalate_reason = self.policy_engine.escalate(call, spec)
        if escalated_tier > tier:
            tier = escalated_tier
            reason = escalate_reason
        else:
            reason = f"Base tier is {tier.name}."

        # 3. Taint escalation: if turn context is tainted, any action >= SAFE_WRITE escalates to CONFIRM
        if ctx.tainted and tier >= RiskTier.SAFE_WRITE:
            tier = max(tier, RiskTier.CONFIRM)
            reason = f"Untrusted content is present in this turn. {reason}".strip()

        # 4. Formulate decision
        if tier >= RiskTier.CONFIRM:
            return Decision(action="ask", tier=tier, reason=reason)

        return Decision(action="allow", tier=tier, reason=reason)
