from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic import BaseModel


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"  # human review required; execution paused


class ApprovalTicket(BaseModel):
    ticket_id: str
    task_id: str
    summary: str
    # Populated from Task.risk_tier so gate implementations can make
    # risk-aware decisions without a separate DB lookup.
    risk_tier: str = ""


class HumanApprovalGate(ABC):
    @abstractmethod
    def request(self, ticket: ApprovalTicket) -> ApprovalDecision:
        raise NotImplementedError
