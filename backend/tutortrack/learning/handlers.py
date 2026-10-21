"""Learning reactions to domain events (idempotent) and the Temporal bridge (E21-TW1)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import (
    AssignmentInput,
    HomeworkReminderWorkflow,
    LoanInput,
    LoanReminderWorkflow,
    homework_workflow_id,
    loan_workflow_id,
)


@subscribe("lesson_report.submitted")
def report_topics_and_homework(event: EventEnvelope) -> None:
    """E09 → E21: a written report's topics tag the lesson (mastery moves on) and its
    homework field sets homework for the lesson's students (once per report)."""
    from . import services

    services.topics_from_report(event.subject["id"])
    services.homework_from_report(event.subject["id"])


@subscribe("organisation.settings_updated")
def follow_progress_schedule(event: EventEnvelope) -> None:
    """Gap G5c (FR-21-6): keep the progress-report Temporal Schedule in step with
    ``learning.progress_schedule`` (create, update or delete; idempotent)."""
    keys = set(event.data.get("keys") or [])
    if event.data.get("area") == "learning" and "learning.progress_schedule" in keys:
        from .progress_schedule import sync_schedule

        sync_schedule()


def _notify(type_key: str, loader: str, event: EventEnvelope, key: str) -> None:
    from tutortrack.comms import services as comms

    from . import notifications

    subject = getattr(notifications, loader)(event.subject["id"])
    if subject is not None:
        comms.notify(type_key, subject, key=key)


@subscribe("homework.assigned")
def tell_family_about_homework(event: EventEnvelope) -> None:
    if int(event.data.get("round", 1)) == 1:
        _notify("homework_assigned", "load_assignment", event, f"homework:{event.subject['id']}")


@subscribe("homework.submitted")
def tell_tutor_about_hand_in(event: EventEnvelope) -> None:
    _notify(
        "homework_submitted",
        "load_assignment",
        event,
        f"homework-submitted:{event.subject['id']}:{event.data.get('round')}",
    )


@subscribe("homework.graded")
def tell_family_about_marks(event: EventEnvelope) -> None:
    _notify("homework_graded", "load_assignment", event, f"homework-graded:{event.subject['id']}")


@subscribe("goal.achieved")
def tell_family_about_goal(event: EventEnvelope) -> None:
    _notify("goal_achieved", "load_goal", event, f"goal-achieved:{event.subject['id']}")


@subscribe("progress_report.shared")
def send_progress_report(event: EventEnvelope) -> None:
    _notify(
        "progress_report_shared", "load_report", event, f"progress-report:{event.subject['id']}"
    )


@subscribe("resource.shared")
def tell_family_about_resource(event: EventEnvelope) -> None:
    from tutortrack.comms import services as comms

    from .notifications import load_share

    share = load_share(event.data["share_id"])
    if share is not None:
        comms.notify(
            "resource_shared",
            (share, event.data.get("student_ids", [])),
            key=f"resource-shared:{share.pk}",
        )


# --- Temporal bridge (E21-TW1) ------------------------------------------------------------------


def _assignment_input(event: EventEnvelope) -> AssignmentInput:
    return AssignmentInput(
        organisation_id=str(event.organisation_id), assignment_id=event.subject["id"]
    )


def _homework_id(event: EventEnvelope) -> str:
    return homework_workflow_id(event.organisation_id, event.subject["id"], event.data["round"])


for _type in ("homework.assigned", "homework.returned"):
    bridge.on(
        _type,
        start=HomeworkReminderWorkflow,
        id=_homework_id,
        input=_assignment_input,
        subject=lambda e: ("homework_assignment", e.subject["id"]),
    )
bridge.on("homework.submitted", signal="changed", id=_homework_id)
bridge.on(
    "loan.created",
    start=LoanReminderWorkflow,
    id=lambda e: loan_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: LoanInput(organisation_id=str(e.organisation_id), loan_id=e.subject["id"]),
)
for _type in ("loan.returned", "loan.lost"):
    bridge.on(
        _type,
        signal="changed",
        id=lambda e: loan_workflow_id(e.organisation_id, e.subject["id"]),
    )
