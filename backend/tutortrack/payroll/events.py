"""Domain events published by payroll (E12 §5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class _PayItemEvent(DomainEvent):
    subject_type: ClassVar[str] = "pay_item"
    tutor_id: str
    kind: str
    amount: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class PayItemCreated(_PayItemEvent):
    event_type: ClassVar[str] = "pay_item.created"


@dataclass(frozen=True, kw_only=True)
class PayItemHeld(_PayItemEvent):
    event_type: ClassVar[str] = "pay_item.held"
    reasons: list[str]


@dataclass(frozen=True, kw_only=True)
class PayItemReleased(_PayItemEvent):
    event_type: ClassVar[str] = "pay_item.released"


@dataclass(frozen=True, kw_only=True)
class _ExpenseEvent(DomainEvent):
    subject_type: ClassVar[str] = "expense"
    tutor_id: str
    amount: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class ExpenseSubmitted(_ExpenseEvent):
    """Starts ``ExpenseApprovalWorkflow``."""

    event_type: ClassVar[str] = "expense.submitted"


@dataclass(frozen=True, kw_only=True)
class ExpenseApproved(_ExpenseEvent):
    event_type: ClassVar[str] = "expense.approved"


@dataclass(frozen=True, kw_only=True)
class ExpenseRejected(_ExpenseEvent):
    event_type: ClassVar[str] = "expense.rejected"
    comment: str = ""


@dataclass(frozen=True, kw_only=True)
class _PayRunEvent(DomainEvent):
    subject_type: ClassVar[str] = "pay_run"
    number: str


@dataclass(frozen=True, kw_only=True)
class PayRunCreated(_PayRunEvent):
    event_type: ClassVar[str] = "pay_run.created"


@dataclass(frozen=True, kw_only=True)
class PayRunApproved(_PayRunEvent):
    event_type: ClassVar[str] = "pay_run.approved"


@dataclass(frozen=True, kw_only=True)
class PayRunPaid(_PayRunEvent):
    event_type: ClassVar[str] = "pay_run.paid"


@dataclass(frozen=True, kw_only=True)
class PayRunPartiallyFailed(_PayRunEvent):
    event_type: ClassVar[str] = "pay_run.partially_failed"
    failed: int


@dataclass(frozen=True, kw_only=True)
class _PayoutEvent(DomainEvent):
    subject_type: ClassVar[str] = "payout"
    tutor_id: str
    pay_run_id: str
    amount: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class PayoutPaid(_PayoutEvent):
    event_type: ClassVar[str] = "payout.paid"


@dataclass(frozen=True, kw_only=True)
class PayoutFailed(_PayoutEvent):
    event_type: ClassVar[str] = "payout.failed"
    reason: str


@dataclass(frozen=True, kw_only=True)
class SelfBillingStatementIssued(DomainEvent):
    event_type: ClassVar[str] = "self_billing_statement.issued"
    subject_type: ClassVar[str] = "pay_statement"
    tutor_id: str
    number: str
