"""Domain events published by courses (E20 §5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class _EnrolmentEvent(DomainEvent):
    subject_type: ClassVar[str] = "enrolment"
    class_id: str
    student_id: str
    client_id: str


@dataclass(frozen=True, kw_only=True)
class EnrolmentCreated(_EnrolmentEvent):
    """A student was enrolled (or holds a place while paying: starts
    ``EnrolmentPaymentWorkflow``)."""

    event_type: ClassVar[str] = "enrolment.created"
    status: str
    source: str
    start_date: str


@dataclass(frozen=True, kw_only=True)
class EnrolmentConfirmed(_EnrolmentEvent):
    """A place held for payment (or a trial) became a full enrolment."""

    event_type: ClassVar[str] = "enrolment.confirmed"


@dataclass(frozen=True, kw_only=True)
class EnrolmentReleased(_EnrolmentEvent):
    """A place held for payment was released (not paid in time, or cancelled)."""

    event_type: ClassVar[str] = "enrolment.released"
    reason: str


@dataclass(frozen=True, kw_only=True)
class EnrolmentWithdrawn(_EnrolmentEvent):
    event_type: ClassVar[str] = "enrolment.withdrawn"
    effective_date: str
    reason: str
    credited: dict[str, str] | None = None


@dataclass(frozen=True, kw_only=True)
class EnrolmentTransferred(_EnrolmentEvent):
    event_type: ClassVar[str] = "enrolment.transferred"
    to_class_id: str
    to_enrolment_id: str
    effective_date: str


@dataclass(frozen=True, kw_only=True)
class EnrolmentCompleted(_EnrolmentEvent):
    event_type: ClassVar[str] = "enrolment.completed"


@dataclass(frozen=True, kw_only=True)
class _ClassEvent(DomainEvent):
    subject_type: ClassVar[str] = "group_class"
    course_id: str


@dataclass(frozen=True, kw_only=True)
class ClassFull(_ClassEvent):
    event_type: ClassVar[str] = "class.full"
    capacity: int


@dataclass(frozen=True, kw_only=True)
class ClassBelowMinimum(_ClassEvent):
    event_type: ClassVar[str] = "class.below_minimum"
    enrolled: int
    min_size: int


@dataclass(frozen=True, kw_only=True)
class ClassCancelled(_ClassEvent):
    event_type: ClassVar[str] = "class.cancelled"
    reason: str
    enrolments_withdrawn: int


@dataclass(frozen=True, kw_only=True)
class ClassPlacesFreed(_ClassEvent):
    """Places may be free (withdrawal, transfer, more capacity, an offer ran out): the
    class offers them to its waitlist."""

    event_type: ClassVar[str] = "class.places_freed"


@dataclass(frozen=True, kw_only=True)
class TermRolloverStarted(DomainEvent):
    """Starts ``TermRolloverWorkflow``."""

    event_type: ClassVar[str] = "term.rollover_started"
    subject_type: ClassVar[str] = "term_rollover"
    from_term_id: str
    to_term_id: str
    offers: int
    deadline: str


@dataclass(frozen=True, kw_only=True)
class RolloverResponded(DomainEvent):
    """A family confirmed or declined next term's place (signals the rollover)."""

    event_type: ClassVar[str] = "term.rollover_responded"
    subject_type: ClassVar[str] = "term_rollover"
    offer_id: str
    confirmed: bool


@dataclass(frozen=True, kw_only=True)
class TermRolloverFinalised(DomainEvent):
    event_type: ClassVar[str] = "term.rollover_finalised"
    subject_type: ClassVar[str] = "term_rollover"
    enrolled: int
    released: int
