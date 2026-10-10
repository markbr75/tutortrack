"""Payroll reactions to domain events (idempotent) and the Temporal bridge (E12-TW1)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import ExpenseApprovalWorkflow, ExpenseInput, expense_workflow_id


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


@subscribe(
    "lesson.completed",
    "lesson.cancelled",
    "attendance.recorded",
    "lesson.updated",
    "lesson.locked_edited",
)
def sync_pay(event: EventEnvelope) -> None:
    """Pay items follow what happened to the lesson (FR-12-1)."""
    from . import services

    services.sync_lesson_pay(event.subject["id"])


@subscribe("charge.created", "charge.voided")
def sync_charge_share(event: EventEnvelope) -> None:
    from . import services

    services.sync_charge_share(event.subject["id"])


@subscribe(
    "lesson_report.submitted", "lesson_report.approved", "lesson_report.overdue",
    "lesson_report.returned",
)  # fmt: skip
def report_holds(event: EventEnvelope) -> None:
    """Hold or release lesson pay as the report becomes overdue or is written (FR-12-1)."""
    from tutortrack.delivery.models import LessonReport

    from . import services

    report = LessonReport.objects.filter(pk=event.subject["id"]).first()
    if report is not None:
        services.reevaluate_lessons([report.lesson_id])


@subscribe("invoice.paid", "invoice.partially_paid", "invoice.voided")
def client_paid_holds(event: EventEnvelope) -> None:
    from tutortrack.billing.selectors import lessons_on_invoice

    from . import services

    services.reevaluate_lessons(lessons_on_invoice(event.subject["id"]))


@subscribe("organisation.settings_updated")
def follow_pay_schedule(event: EventEnvelope) -> None:
    keys = set(event.data.get("keys") or [])
    if event.data.get("area") == "payroll" and keys & {"payroll.pay_period", "payroll.cut_off_day"}:
        from .schedules import sync_pay_schedules

        sync_pay_schedules()


bridge.on(
    "expense.submitted",
    start=ExpenseApprovalWorkflow,
    id=lambda e: expense_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: ExpenseInput(
        organisation_id=str(e.organisation_id), expense_id=e.subject["id"]
    ),
)
for _decided in ("expense.approved", "expense.rejected"):
    bridge.on(
        _decided,
        signal="decided",
        id=lambda e: expense_workflow_id(e.organisation_id, e.subject["id"]),
        when=lambda e: _running(expense_workflow_id(e.organisation_id, e.subject["id"])),
    )
