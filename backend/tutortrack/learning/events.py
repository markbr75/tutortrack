"""Domain events published by learning (E21 §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from tutortrack.core.events import DomainEvent

# --- resources ----------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ResourceShared(DomainEvent):
    """A resource was shared with a student, job, lesson or class (``target``). Online
    lesson integrations (E22) can pick up ``lesson`` shares."""

    event_type: ClassVar[str] = "resource.shared"
    subject_type: ClassVar[str] = "resource"
    share_id: str
    target: str  # student | job | lesson | group_class
    target_id: str
    student_ids: list[str] = field(default_factory=list)


# --- homework -----------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class _AssignmentEvent(DomainEvent):
    subject_type: ClassVar[str] = "homework_assignment"
    homework_id: str
    student_id: str
    round: int


@dataclass(frozen=True, kw_only=True)
class HomeworkAssigned(_AssignmentEvent):
    """Starts ``HomeworkReminderWorkflow`` (reminder before due, overdue at due)."""

    event_type: ClassVar[str] = "homework.assigned"
    title: str
    due_at: str


@dataclass(frozen=True, kw_only=True)
class HomeworkSubmitted(_AssignmentEvent):
    event_type: ClassVar[str] = "homework.submitted"
    is_late: bool


@dataclass(frozen=True, kw_only=True)
class HomeworkReturned(_AssignmentEvent):
    """Returned for resubmission: a new reminder round starts with the new due date."""

    event_type: ClassVar[str] = "homework.returned"
    due_at: str


@dataclass(frozen=True, kw_only=True)
class HomeworkGraded(_AssignmentEvent):
    event_type: ClassVar[str] = "homework.graded"
    grade: str
    score_percent: str | None = None


@dataclass(frozen=True, kw_only=True)
class HomeworkOverdue(_AssignmentEvent):
    event_type: ClassVar[str] = "homework.overdue"
    due_at: str


@dataclass(frozen=True, kw_only=True)
class HomeworkCancelled(DomainEvent):
    event_type: ClassVar[str] = "homework.cancelled"
    subject_type: ClassVar[str] = "homework"
    assignments: int


# --- curriculum ---------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class TopicMasteryChanged(DomainEvent):
    event_type: ClassVar[str] = "topic_mastery.changed"
    subject_type: ClassVar[str] = "topic_mastery"
    student_id: str
    node_id: str
    level: str
    previous: str


# --- goals --------------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class _GoalEvent(DomainEvent):
    subject_type: ClassVar[str] = "goal"
    student_id: str
    title: str


@dataclass(frozen=True, kw_only=True)
class GoalCreated(_GoalEvent):
    event_type: ClassVar[str] = "goal.created"
    kind: str


@dataclass(frozen=True, kw_only=True)
class GoalAchieved(_GoalEvent):
    event_type: ClassVar[str] = "goal.achieved"


# --- assessments --------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class AssessmentRecorded(DomainEvent):
    event_type: ClassVar[str] = "assessment.recorded"
    subject_type: ClassVar[str] = "assessment_result"
    assessment_id: str
    student_id: str
    kind: str
    percent: str | None = None
    grade: str = ""


# --- progress reports ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class _ProgressEvent(DomainEvent):
    subject_type: ClassVar[str] = "progress_report"
    student_id: str
    period_start: str
    period_end: str


@dataclass(frozen=True, kw_only=True)
class ProgressReportSubmitted(_ProgressEvent):
    event_type: ClassVar[str] = "progress_report.submitted"


@dataclass(frozen=True, kw_only=True)
class ProgressReportApproved(_ProgressEvent):
    event_type: ClassVar[str] = "progress_report.approved"


@dataclass(frozen=True, kw_only=True)
class ProgressReportShared(_ProgressEvent):
    event_type: ClassVar[str] = "progress_report.shared"
    client_id: str


# --- lending library ----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class _LoanEvent(DomainEvent):
    subject_type: ClassVar[str] = "loan"
    item_id: str
    student_id: str


@dataclass(frozen=True, kw_only=True)
class LoanCreated(_LoanEvent):
    """Starts ``LoanReminderWorkflow`` (due reminder, overdue notices)."""

    event_type: ClassVar[str] = "loan.created"
    due_date: str


@dataclass(frozen=True, kw_only=True)
class LoanReturned(_LoanEvent):
    event_type: ClassVar[str] = "loan.returned"


@dataclass(frozen=True, kw_only=True)
class LoanOverdue(_LoanEvent):
    event_type: ClassVar[str] = "loan.overdue"
    due_date: str


@dataclass(frozen=True, kw_only=True)
class LoanLost(_LoanEvent):
    event_type: ClassVar[str] = "loan.lost"
    charged: dict[str, str] | None = None


# --- quizzes ------------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class QuizSubmitted(DomainEvent):
    event_type: ClassVar[str] = "quiz.submitted"
    subject_type: ClassVar[str] = "quiz_attempt"
    quiz_id: str
    student_id: str | None
    percent: str
    passed: bool
