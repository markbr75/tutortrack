"""Tutor performance and offboarding (FR-18-9, gap batch G5a).

* **Probation reviews**: one scheduled review per tutor, due ``recruitment.probation_days``
  after the tutor is activated (or on a date staff choose). ``ProbationReviewWorkflow``
  reminds staff ``recruitment.probation_reminder_days`` before, tells them on the day and
  chases weekly until an outcome is recorded: passed, extended (a new review on a later
  date) or not passed.
* **Performance notes**: praise, concerns and plain notes from staff (staff only).
* **Offboarding**: a checklist (``catalogue.OFFBOARDING``). Starting it makes the tutor
  inactive (no new work). Jobs, future lessons, access and final pay tick themselves from
  the tutor's data; equipment and records are ticked by staff. Completing it archives the
  tutor; their records stay for the retention period (E29).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.time import now
from tutortrack.people.models import TutorProfile
from tutortrack.tenancy.settings_service import get_setting

from . import catalogue, compliance, events
from .models import OffboardingChecklist, PerformanceNote, ProbationReview

# --- probation reviews -----------------------------------------------------------------------


def open_review(tutor: TutorProfile) -> ProbationReview | None:
    return ProbationReview.objects.filter(
        tutor=tutor, status=ProbationReview.Status.SCHEDULED
    ).first()


@transaction.atomic
def schedule_probation(
    tutor: TutorProfile, *, due_on: date, user: Any = None, previous: ProbationReview | None = None
) -> ProbationReview:
    if open_review(tutor) is not None:
        raise BusinessRuleViolation(
            _("This tutor already has a probation review scheduled."),
            extra={"code": "probation_scheduled"},
        )
    if due_on < compliance.today():
        raise BusinessRuleViolation(
            _("Choose a date from today."), extra={"errors": {"due_on": [_("In the past.")]}}
        )
    review = ProbationReview.objects.create(
        tutor=tutor, due_on=due_on, created_by=user, previous=previous
    )
    audit.record(review, "create", {"due_on": [None, due_on.isoformat()]})
    publish(
        events.ProbationScheduled(
            subject_id=review.pk, tutor_id=str(tutor.pk), due_on=due_on.isoformat()
        )
    )
    return review


def schedule_after_activation(tutor_id: Any) -> ProbationReview | None:
    """Handler for ``onboarding.completed``: the first review ``probation_days`` after the
    tutor starts. Idempotent: nothing happens if the tutor has ever had a review."""
    days = int(get_setting("recruitment.probation_days") or 0)
    tutor = TutorProfile.objects.filter(pk=tutor_id).first()
    if not days or tutor is None or ProbationReview.objects.filter(tutor=tutor).exists():
        return None
    return schedule_probation(tutor, due_on=compliance.today() + timedelta(days=days))


@transaction.atomic
def complete_probation(
    review: ProbationReview,
    *,
    outcome: str,
    notes: str = "",
    user: Any = None,
    extend_to: date | None = None,
) -> ProbationReview:
    review = ProbationReview.objects.select_for_update().select_related("tutor").get(pk=review.pk)
    if review.status != ProbationReview.Status.SCHEDULED:
        raise BusinessRuleViolation(_("This review has already been recorded."))
    allowed = (
        ProbationReview.Status.PASSED,
        ProbationReview.Status.EXTENDED,
        ProbationReview.Status.FAILED,
        ProbationReview.Status.CANCELLED,
    )
    if outcome not in allowed:
        raise BusinessRuleViolation(_("Choose an outcome."))
    if outcome == ProbationReview.Status.EXTENDED and (
        extend_to is None or extend_to <= review.due_on
    ):
        raise BusinessRuleViolation(
            _("Choose a later date for the next review."),
            extra={"errors": {"extend_to": [_("Later than the current review.")]}},
        )
    with audit.track(review, action="complete"):
        review.status = outcome
        review.outcome_notes = notes[:5000]
        review.reviewer = user
        review.reviewed_at = now()
        review.save()
    publish(
        events.ProbationCompleted(
            subject_id=review.pk, tutor_id=str(review.tutor_id), outcome=outcome
        )
    )
    if outcome == ProbationReview.Status.EXTENDED and extend_to is not None:
        schedule_probation(review.tutor, due_on=extend_to, user=user, previous=review)
    return review


def probation_snapshot(review_id: Any) -> dict[str, Any]:
    """What ``ProbationReviewWorkflow`` needs (read once at the start)."""
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    review = ProbationReview.objects.filter(pk=review_id).first()
    org = Organisation.objects.get(pk=require_organisation_id())
    return {
        "due_on": review.due_on.isoformat() if review else "",
        "open": bool(review and review.status == ProbationReview.Status.SCHEDULED),
        "timezone": org.timezone,
        "reminder_days": int(get_setting("recruitment.probation_reminder_days")),
    }


def probation_alert(review_id: Any, stage: str) -> bool:
    """Tell staff a review is coming up (``upcoming``), due today (``due``) or overdue."""
    from tutortrack.comms import services as comms

    review = ProbationReview.objects.select_related("tutor").filter(pk=review_id).first()
    if review is None or review.status != ProbationReview.Status.SCHEDULED:
        return False
    name = review.tutor.full_name
    titles = {
        "upcoming": _("Probation review coming up: %(name)s"),
        "due": _("Probation review due today: %(name)s"),
        "overdue": _("Probation review overdue: %(name)s"),
    }
    body = _("Due on %(date)s. Record the outcome on the tutor's record.") % {
        "date": review.due_on.isoformat()
    }
    comms.notify(
        "staff_probation_review",
        (titles.get(stage, titles["due"]) % {"name": name}, body, f"/tutors/{review.tutor_id}"),
        key=f"probation:{review.pk}:{stage}:{now():%Y%m%d}",
    )
    return True


def probation_open(review_id: Any) -> bool:
    return ProbationReview.objects.filter(
        pk=review_id, status=ProbationReview.Status.SCHEDULED
    ).exists()


# --- performance notes ----------------------------------------------------------------------


@transaction.atomic
def add_note(tutor: TutorProfile, *, kind: str, body: str, user: Any) -> PerformanceNote:
    if kind not in PerformanceNote.Kind.values:
        raise BusinessRuleViolation(_("Choose a kind of note."))
    if not body.strip():
        raise BusinessRuleViolation(
            _("Write the note."), extra={"errors": {"body": [_("Required.")]}}
        )
    note = PerformanceNote.objects.create(
        tutor=tutor, kind=kind, body=body.strip()[:5000], author=user
    )
    audit.record(note, "create", {"kind": [None, kind]})
    publish(events.PerformanceNoteAdded(subject_id=tutor.pk, note_id=str(note.pk), kind=kind))
    return note


@transaction.atomic
def delete_note(note: PerformanceNote) -> None:
    audit.record(note, "delete", {"kind": [note.kind, None]})
    note.delete()


# --- offboarding ----------------------------------------------------------------------------


def open_offboarding(tutor: TutorProfile) -> OffboardingChecklist | None:
    return OffboardingChecklist.objects.filter(tutor=tutor, completed_at__isnull=True).first()


@transaction.atomic
def start_offboarding(
    tutor: TutorProfile, *, reason: str = "", leaving_on: date | None = None, user: Any = None
) -> OffboardingChecklist:
    from tutortrack.people.services import change_tutor_status

    tutor = TutorProfile.objects.select_for_update().get(pk=tutor.pk)
    if open_offboarding(tutor) is not None:
        raise BusinessRuleViolation(_("This tutor is already being offboarded."))
    if tutor.status == TutorProfile.Status.ARCHIVED:
        raise BusinessRuleViolation(_("This tutor has already left."))
    checklist = OffboardingChecklist.objects.create(
        tutor=tutor,
        reason=reason[:500],
        leaving_on=leaving_on,
        items=catalogue.OFFBOARDING,
        started_by=user,
    )
    audit.record(checklist, "create", {"reason": [None, reason[:500]]})
    if tutor.status in (TutorProfile.Status.ACTIVE, TutorProfile.Status.RESTRICTED):
        change_tutor_status(tutor, TutorProfile.Status.INACTIVE)
    review = open_review(tutor)
    if review is not None:
        complete_probation(review, outcome=ProbationReview.Status.CANCELLED, user=user)
    publish(
        events.OffboardingStarted(
            subject_id=tutor.pk, leaving_on=leaving_on.isoformat() if leaving_on else None
        )
    )
    return checklist


def _auto_done(tutor: TutorProfile, key: str) -> bool:
    from tutortrack.jobs.models import JobTutor
    from tutortrack.payroll.models import PayItem
    from tutortrack.scheduling.models import Lesson

    if key == "jobs":
        return not JobTutor.objects.filter(
            tutor=tutor, status__in=[JobTutor.Status.ACTIVE, JobTutor.Status.OFFERED]
        ).exists()
    if key == "lessons":
        return not Lesson.objects.filter(
            tutors__tutor=tutor, start__gte=now(), status=Lesson.Status.PLANNED
        ).exists()
    if key == "access":
        membership = tutor.membership
        return membership is None or membership.status != "active"
    if key == "final_pay":
        return not PayItem.objects.filter(
            tutor=tutor,
            status__in=[
                PayItem.Status.READY,
                PayItem.Status.HELD,
                PayItem.Status.IN_PAY_RUN,
                PayItem.Status.APPROVED,
            ],
        ).exists()
    return False


def offboarding_state(checklist: OffboardingChecklist) -> list[dict[str, Any]]:
    out = []
    for item in checklist.items:
        done = checklist.done.get(item["key"])
        complete = bool(done) or (
            bool(item.get("auto")) and _auto_done(checklist.tutor, item["key"])
        )
        out.append(
            {
                "key": item["key"],
                "label": item["label"],
                "auto": bool(item.get("auto")),
                "done": complete,
                "done_at": (done or {}).get("at"),
            }
        )
    return out


@transaction.atomic
def tick_offboarding(
    checklist: OffboardingChecklist, key: str, *, user: Any
) -> OffboardingChecklist:
    checklist = OffboardingChecklist.objects.select_for_update().get(pk=checklist.pk)
    if checklist.completed_at is not None:
        raise BusinessRuleViolation(_("Offboarding is finished."))
    item = next((i for i in checklist.items if i["key"] == key), None)
    if item is None:
        raise NotFound()
    if item.get("auto"):
        raise BusinessRuleViolation(
            _("This step completes itself when it is done."), extra={"code": "auto_item"}
        )
    if key not in checklist.done:
        checklist.done = {
            **checklist.done,
            key: {"at": now().isoformat(), "by": str(getattr(user, "pk", ""))},
        }
        checklist.save(update_fields=["done", "updated_at"])
        audit.record(checklist, "item_done", {"item": [None, key]})
    return checklist


@transaction.atomic
def revoke_access(checklist: OffboardingChecklist, *, user: Any) -> OffboardingChecklist:
    """End the tutor's login to this organisation (E03 ``remove_member``)."""
    from tutortrack.identity import services as identity

    membership = checklist.tutor.membership
    if membership is not None and membership.status == "active":
        identity.remove_member(membership)
    audit.record(checklist, "revoke_access", {})
    return checklist


@transaction.atomic
def complete_offboarding(checklist: OffboardingChecklist, *, user: Any) -> OffboardingChecklist:
    from tutortrack.people.services import change_tutor_status

    checklist = (
        OffboardingChecklist.objects.select_for_update()
        .select_related("tutor")
        .get(pk=checklist.pk)
    )
    if checklist.completed_at is not None:
        raise BusinessRuleViolation(_("Offboarding is finished."))
    waiting = [i["label"] for i in offboarding_state(checklist) if not i["done"]]
    if waiting:
        raise BusinessRuleViolation(
            _("Finish every step first."),
            extra={"code": "offboarding_incomplete", "waiting": waiting},
        )
    with audit.track(checklist, action="complete"):
        checklist.completed_at = now()
        checklist.save()
    change_tutor_status(checklist.tutor, TutorProfile.Status.ARCHIVED)
    publish(events.OffboardingCompleted(subject_id=checklist.tutor_id))
    return checklist
