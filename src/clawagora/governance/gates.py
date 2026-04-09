from __future__ import annotations

from clawagora.governance.approval import ApprovalDecision, ApprovalTicket, HumanApprovalGate
from clawagora.governance.risk import RiskTier


class AutoApprovalGate(HumanApprovalGate):
    """Default synchronous gate — always approves.

    This is the production default so existing pipelines are unaffected.
    Operators swap this with a domain-specific implementation to enforce
    review for high-risk or regulated tasks.
    """

    def request(self, ticket: ApprovalTicket) -> ApprovalDecision:
        return ApprovalDecision.APPROVED


class RiskBasedApprovalGate(HumanApprovalGate):
    """Rejects tasks whose risk tier meets or exceeds *reject_at*.

    Useful for automated pipelines where tasks above a risk threshold must
    not proceed without explicit operator intervention.

    Args:
        reject_at: The minimum RiskTier that triggers rejection.
            Defaults to RiskTier.HIGH (only HIGH is rejected;
            LOW and MEDIUM pass through automatically).

    Example::

        gate = RiskBasedApprovalGate(reject_at=RiskTier.MEDIUM)
        # Now both MEDIUM and HIGH tasks are rejected.
    """

    _ORDER: dict[RiskTier, int] = {RiskTier.LOW: 0, RiskTier.MEDIUM: 1, RiskTier.HIGH: 2}

    def __init__(self, reject_at: RiskTier = RiskTier.HIGH) -> None:
        self._threshold = self._ORDER[reject_at]

    def request(self, ticket: ApprovalTicket) -> ApprovalDecision:
        tier_str = ticket.risk_tier
        try:
            tier = RiskTier(tier_str) if tier_str else RiskTier.LOW
        except ValueError:
            tier = RiskTier.LOW
        if self._ORDER.get(tier, 0) >= self._threshold:
            return ApprovalDecision.REJECTED
        return ApprovalDecision.APPROVED


class PendingHumanApprovalGate(HumanApprovalGate):
    """Returns PENDING for tasks whose risk tier meets or exceeds *review_at*.

    All other tasks are auto-approved. The OrchestrationService handles
    PENDING by persisting an ApprovalRequest record, setting the task to
    PENDING_APPROVAL, and returning — execution resumes only after an
    operator calls the approve or vote endpoint.

    Args:
        review_at: The minimum RiskTier that triggers human review.
            Defaults to RiskTier.HIGH.
        quorum: Number of approvers whose votes are needed to reach a
            decision. A simple majority (quorum//2 + 1) is required on
            either side to resolve. quorum=1 (default) reproduces the
            original single-operator behaviour. Use odd values (3, 5, 7)
            to avoid ties.
    """

    _ORDER: dict[RiskTier, int] = {RiskTier.LOW: 0, RiskTier.MEDIUM: 1, RiskTier.HIGH: 2}

    def __init__(self, review_at: RiskTier = RiskTier.HIGH, quorum: int = 1) -> None:
        if quorum < 1:
            raise ValueError("quorum must be >= 1")
        self._threshold = self._ORDER[review_at]
        self.quorum = quorum

    def request(self, ticket: ApprovalTicket) -> ApprovalDecision:
        tier_str = ticket.risk_tier
        try:
            tier = RiskTier(tier_str) if tier_str else RiskTier.LOW
        except ValueError:
            tier = RiskTier.LOW
        if self._ORDER.get(tier, 0) >= self._threshold:
            return ApprovalDecision.PENDING
        return ApprovalDecision.APPROVED
