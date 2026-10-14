"""Lone working (E29-T09, FR-29-6): tutors tap "arrived" and "left" for in-person lessons;
if they haven't checked out ``safeguarding.lone_working_grace_minutes`` after the lesson
ends, monitors (``safeguarding.lone_working.monitor``) and the tutor are alerted, then the
safeguarding leads after ``safeguarding.lone_working_escalate_minutes``. The timers are
``LoneWorkingWorkflow`` (started by ``lone_working.checked_in``)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import notifications
from .events import LoneWorkingCheckedIn, LoneWorkingCheckedOut, LoneWorkingOverdue
from .models import LoneWorkingVisit

Visit = LoneWorkingVisit
PROCESS = "lone-working"


def workflow_id_for(visit: Visit) -> str:
    from tutortrack.core.workflows import workflow_id

    return workflow_id(PROCESS, visit.organisation_id, visit.pk)


def applies_to(lesson: Any) -> bool:
    mode = get_setting("safeguarding.lone_working")
    if mode == "off" or lesson.online:
        return False
    if mode == "in_person":
        return True
    location = lesson.location
    return location is None or location.type == "client_home"


def _tutor_for(user: Any) -> Any:
    from tutortrack.people.models import TutorProfile

    tutor = TutorProfile.objects.filter(membership__user=user).first()
    if tutor is None:
        raise BusinessRuleViolation(_("Only tutors check in to lessons."))
    return tutor


def _lesson_for(tutor: Any, lesson_id: Any) -> Any:
    from tutortrack.scheduling.models import Lesson

    lesson = (
        Lesson.objects.select_related("location").filter(pk=lesson_id, tutors__tutor=tutor).first()
    )
    if lesson is None:
        raise NotFound(_("Lesson not found."))
    return lesson


@transaction.atomic
def check_in(*, user: Any, lesson_id: Any) -> Visit:
    tutor = _tutor_for(user)
    lesson = _lesson_for(tutor, lesson_id)
    if not applies_to(lesson):
        raise BusinessRuleViolation(_("Check-in isn't needed for this lesson."))
    if lesson.status == "cancelled":
        raise BusinessRuleViolation(_("This lesson was cancelled."))
    existing = Visit.objects.filter(lesson=lesson, tutor=tutor).first()
    if existing is not None:
        return existing
    visit = Visit.objects.create(
        lesson=lesson, tutor=tutor, checked_in_at=now(), expected_end=lesson.end
    )
    visit.workflow_id = workflow_id_for(visit)
    visit.save(update_fields=["workflow_id", "updated_at"])
    audit.record_create(visit)
    publish(
        LoneWorkingCheckedIn(
            subject_id=visit.pk,
            lesson_id=str(lesson.pk),
            tutor_id=str(tutor.pk),
            expected_end=lesson.end.isoformat(),
        )
    )
    return visit


@transaction.atomic
def check_out(*, user: Any, lesson_id: Any) -> Visit:
    tutor = _tutor_for(user)
    visit = Visit.objects.select_for_update().filter(lesson_id=lesson_id, tutor=tutor).first()
    if visit is None:
        raise BusinessRuleViolation(_("You haven't checked in to this lesson."))
    if visit.checked_out_at is not None:
        return visit
    with audit.track(visit, action="check_out"):
        visit.checked_out_at = now()
        visit.status = Visit.Status.CHECKED_OUT
        visit.save()
    publish(
        LoneWorkingCheckedOut(subject_id=visit.pk, lesson_id=str(lesson_id), tutor_id=str(tutor.pk))
    )
    return visit


@transaction.atomic
def resolve(visit: Visit, *, user: Any, note: str) -> Visit:
    """A monitor confirmed the tutor is safe."""
    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    if visit.status in {Visit.Status.CHECKED_OUT, Visit.Status.RESOLVED}:
        return visit
    if not note.strip():
        message = _("Say how you confirmed the tutor is safe.")
        raise BusinessRuleViolation(message, extra={"errors": {"note": [message]}})
    with audit.track(visit, action="resolve"):
        visit.status = Visit.Status.RESOLVED
        visit.resolved_at = now()
        visit.resolved_by = user
        visit.note = note[:500]
        visit.save()
    from tutortrack.core.models import WorkflowLink
    from tutortrack.core.workflows import signal

    if WorkflowLink.objects.filter(workflow_id=visit.workflow_id, status="running").exists():
        signal(visit.workflow_id, "resolved")
    return visit


# --- workflow steps -----------------------------------------------------------------------------


def state(visit_id: str) -> dict[str, Any]:
    visit = Visit.objects.get(pk=visit_id)
    grace = int(get_setting("safeguarding.lone_working_grace_minutes") or 30)
    escalate = int(get_setting("safeguarding.lone_working_escalate_minutes") or 30)
    alert_at = visit.expected_end + timedelta(minutes=grace)
    return {
        "status": visit.status,
        "done": visit.status in {Visit.Status.CHECKED_OUT, Visit.Status.RESOLVED},
        "alert_at": alert_at.isoformat(),
        "escalate_at": (alert_at + timedelta(minutes=escalate)).isoformat(),
    }


@transaction.atomic
def alert(visit_id: str, *, escalate: bool) -> str:
    visit = Visit.objects.select_for_update().select_related("tutor").get(pk=visit_id)
    if visit.status in {Visit.Status.CHECKED_OUT, Visit.Status.RESOLVED}:
        return visit.status
    stamp = "escalated_at" if escalate else "alerted_at"
    if getattr(visit, stamp) is not None:
        return visit.status
    setattr(visit, stamp, now())
    visit.status = Visit.Status.OVERDUE
    visit.save(update_fields=[stamp, "status", "updated_at"])
    audit.record(visit, "escalate" if escalate else "overdue")
    publish(
        LoneWorkingOverdue(
            subject_id=visit.pk,
            lesson_id=str(visit.lesson_id),
            tutor_id=str(visit.tutor_id),
            escalated=escalate,
        )
    )
    title = (
        _("ESCALATED: %(tutor)s still hasn't checked out of a lesson")
        if escalate
        else _("%(tutor)s hasn't checked out of a lesson")
    ) % {"tutor": visit.tutor.full_name}
    notifications.send(
        "lone_working_overdue",
        (
            title,
            _("Expected to finish at %(time)s. Contact them and mark the visit resolved.")
            % {"time": notifications.local_time(visit.expected_end)},
            notifications.admin_link("/safeguarding?tab=lone-working"),
            visit.tutor,
            escalate,
        ),
        key=f"{'escalated' if escalate else 'overdue'}:{visit.pk}",
        immediate=True,
    )
    return visit.status
