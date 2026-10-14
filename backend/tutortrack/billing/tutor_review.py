"""Tutor pre-review of draft invoices (FR-10-3 review window, TutorBird parity, gap G3).

With ``billing.tutor_review`` on, an invoice run that drafts invoices asks every tutor whose
lessons are on them to check those lessons (dates, students, lessons: never amounts, FR-07-1)
before the drafts are issued. Each tutor confirms or reports a problem:

* the run's review window lasts at least ``billing.tutor_review_days``; it ends early once
  every tutor has answered (``InvoiceRunWorkflow`` gets the ``tutors_done`` signal) or when
  staff approve the run;
* drafts with a reported problem are **held**: the run leaves them as drafts for staff to
  correct and issue, and staff get an alert. Unanswered reviews don't hold anything.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import events
from .models import Charge, Invoice, InvoiceRun, TutorInvoiceReview

LESSON_KINDS = ("lesson", "advance", "late_cancellation", "reconciliation")


def enabled(run: InvoiceRun) -> bool:
    return bool(get_setting("billing.tutor_review", branch=run.branch))


def review_days(run: InvoiceRun) -> int:
    return int(get_setting("billing.tutor_review_days", branch=run.branch))


def _run_charges(run: InvoiceRun) -> Any:
    return Charge.objects.filter(
        invoice__invoice_run=run,
        invoice__status=Invoice.Status.DRAFT,
        kind__in=LESSON_KINDS,
        tutor__isnull=False,
    )


def open_reviews(run: InvoiceRun) -> list[TutorInvoiceReview]:
    """One review per tutor with lessons on the run's drafts (idempotent)."""
    tutor_ids = sorted({str(t) for t in _run_charges(run).values_list("tutor_id", flat=True)})
    out = []
    for tutor_id in tutor_ids:
        review, _created = TutorInvoiceReview.objects.get_or_create(
            invoice_run=run, tutor_id=tutor_id
        )
        out.append(review)
    if tutor_ids:
        publish(
            events.TutorReviewRequested(
                subject_id=run.pk,
                tutor_ids=tutor_ids,
                review_until=run.review_until.isoformat() if run.review_until else None,
            ),
            branch_id=run.branch_id,
            dedupe_key=f"tutor-review:{run.pk}",
        )
    return out


def lessons_for(review: TutorInvoiceReview) -> list[dict[str, Any]]:
    """The tutor's lessons on the run's drafts, without any amounts."""
    rows = (
        _run_charges(review.invoice_run)
        .filter(tutor_id=review.tutor_id)
        .select_related("lesson", "student", "invoice")
        .order_by("date", "created_at")
    )
    return [
        {
            "invoice_id": str(c.invoice_id),
            "date": c.date,
            "lesson_id": str(c.lesson_id) if c.lesson_id else None,
            "description": c.description,
            "student": c.student.full_name if c.student else "",
            "duration_minutes": (
                int((c.lesson.end - c.lesson.start).total_seconds() // 60) if c.lesson else None
            ),
        }
        for c in rows
    ]


def _answerable(review: TutorInvoiceReview) -> TutorInvoiceReview:
    review = (
        TutorInvoiceReview.objects.select_for_update()
        .select_related("invoice_run")
        .get(pk=review.pk)
    )
    if review.invoice_run.status != InvoiceRun.Status.REVIEW:
        raise BusinessRuleViolation(_("These invoices are no longer waiting for review."))
    if review.status != TutorInvoiceReview.Status.PENDING:
        raise BusinessRuleViolation(_("You've already answered."))
    return review


def _answered(review: TutorInvoiceReview, held: list[str]) -> None:
    run = review.invoice_run
    publish(
        events.TutorReviewAnswered(
            subject_id=run.pk,
            review_id=str(review.pk),
            tutor_id=str(review.tutor_id),
            status=review.status,
            held_invoice_ids=held,
        ),
        branch_id=run.branch_id,
    )
    pending = TutorInvoiceReview.objects.filter(
        invoice_run=run, status=TutorInvoiceReview.Status.PENDING
    ).exists()
    if not pending and run.workflow_id:
        workflow_id = run.workflow_id

        def signal_done() -> None:
            from tutortrack.core.workflows import signal

            signal(workflow_id, "tutors_done")

        transaction.on_commit(signal_done)


@transaction.atomic
def confirm(review: TutorInvoiceReview, *, user: Any = None) -> TutorInvoiceReview:
    review = _answerable(review)
    with audit.track(review, action="confirm"):
        review.status = TutorInvoiceReview.Status.CONFIRMED
        review.decided_at = now()
        review.decided_by = user
        review.save()
    _answered(review, [])
    return review


@transaction.atomic
def flag(
    review: TutorInvoiceReview,
    *,
    comment: str,
    invoice_ids: list[str] | None = None,
    user: Any = None,
) -> TutorInvoiceReview:
    """Report a problem: the drafts with the tutor's lessons (or the ones named) are held."""
    review = _answerable(review)
    if not comment.strip():
        message = _("Say what's wrong.")
        raise BusinessRuleViolation(message, extra={"errors": {"comment": [message]}})
    mine = {row["invoice_id"] for row in lessons_for(review)}
    held = sorted(mine & {str(i) for i in invoice_ids}) if invoice_ids else sorted(mine)
    if not held:
        message = _("Choose an invoice with your lessons on it.")
        raise BusinessRuleViolation(message, extra={"errors": {"invoice_ids": [message]}})
    with audit.track(review, action="flag"):
        review.status = TutorInvoiceReview.Status.FLAGGED
        review.comment = comment[:2000]
        review.flagged_invoices = held
        review.decided_at = now()
        review.decided_by = user
        review.save()
    _answered(review, held)
    return review


def held_invoice_ids(run_id: Any) -> set[str]:
    """Drafts a tutor has reported a problem with (left as drafts by ``issue_run``)."""
    out: set[str] = set()
    for ids in TutorInvoiceReview.objects.filter(
        invoice_run_id=run_id, status=TutorInvoiceReview.Status.FLAGGED
    ).values_list("flagged_invoices", flat=True):
        out.update(str(i) for i in ids or [])
    return out


def summary(run: InvoiceRun) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for status in TutorInvoiceReview.objects.filter(invoice_run=run).values_list(
        "status", flat=True
    ):
        counts[status] += 1
    return dict(counts)
