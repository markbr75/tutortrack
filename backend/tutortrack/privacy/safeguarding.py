"""Safeguarding concerns and the DSL case record (E29-T08, FR-29-6).

Any member with ``safeguarding.raise`` (staff and tutors) can raise a concern about a
student, from the student or lesson page. It goes only to Designated Safeguarding Leads
(``safeguarding.dsl``): urgent notifications carry the reference and category, never
names or the description. The description, outcome and action notes are encrypted; every
DSL read is audited (``audit.record_read``) and the case's audit entries are hidden from
the general audit search for anyone else.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from tutortrack.core.models import StoredFile
from tutortrack.core.permissions import has_perm, permission_scope
from tutortrack.core.sequences import next_number
from tutortrack.core.time import now

from . import notifications
from .events import SafeguardingConcernClosed, SafeguardingConcernRaised
from .models import SafeguardingAction, SafeguardingConcern, SafeguardingFlag

Concern = SafeguardingConcern

audit.restrict_object_types("privacy.safeguarding", "safeguarding.dsl")


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def _visible_student(user: Any, student_id: Any) -> Any:
    from tutortrack.people.models import Student

    qs = Student.objects.filter(pk=student_id)
    if permission_scope(user, "people.student.view") == "own":
        qs = qs.filter(Student.own_scope_q(user))
    student = qs.first()
    if student is None:
        raise NotFound(_("Student not found."))
    return student


def _link(concern: Concern) -> str:
    return notifications.admin_link(f"/safeguarding/{concern.pk}")


def alert_dsls(concern: Concern, *, title: str, key: str) -> None:
    notifications.send(
        "safeguarding_alert",
        (title, str(concern.get_category_display()), _link(concern)),
        key=key,
        immediate=concern.immediate_risk,
    )


@transaction.atomic
def raise_concern(
    *,
    user: Any,
    category: str,
    description: str,
    immediate_risk: bool = False,
    student_id: Any = None,
    lesson_id: Any = None,
    tutor_id: Any = None,
    attachment_ids: list[Any] | None = None,
) -> Concern:
    if category not in Concern.Category.values:
        raise _invalid("category", _("Choose a category."))
    if not description.strip():
        raise _invalid("description", _("Describe what you saw or were told."))
    student = _visible_student(user, student_id) if student_id else None
    lesson = None
    if lesson_id:
        from tutortrack.scheduling.models import Lesson

        lesson = Lesson.objects.filter(pk=lesson_id).first()
        if lesson is None:
            raise NotFound(_("Lesson not found."))
    tutor = None
    if tutor_id:
        from tutortrack.people.models import TutorProfile

        tutor = TutorProfile.objects.filter(pk=tutor_id).first()
    concern = Concern.objects.create(
        reference=next_number("privacy.safeguarding", prefix="SG-", padding=5),
        student=student,
        lesson=lesson,
        tutor=tutor,
        category=category,
        description=description.strip(),
        immediate_risk=immediate_risk,
        raised_by=user,
        raised_at=now(),
    )
    if attachment_ids:
        files = list(StoredFile.objects.filter(pk__in=attachment_ids, uploaded_by=user))
        concern.attachments.set(files)
    audit.record_create(concern)
    publish(
        SafeguardingConcernRaised(
            subject_id=concern.pk, category=category, immediate_risk=immediate_risk
        )
    )
    title = (
        _("URGENT: safeguarding concern %(ref)s (immediate risk)") % {"ref": concern.reference}
        if immediate_risk
        else _("New safeguarding concern %(ref)s") % {"ref": concern.reference}
    )
    alert_dsls(concern, title=title, key=f"raised:{concern.pk}")
    return concern


def read_case(concern: Concern, user: Any) -> Concern:
    """A DSL opened the case: log the sensitive read."""
    if not has_perm(user, "safeguarding.dsl"):
        raise PermissionDenied()
    with transaction.atomic():
        audit.record_read(concern, "safeguarding_case")
    return concern


@transaction.atomic
def add_action(
    concern: Concern, *, kind: str, note: str = "", user: Any = None
) -> SafeguardingAction:
    if kind not in SafeguardingAction.Kind.values or kind in {
        SafeguardingAction.Kind.STATUS_CHANGED,
        SafeguardingAction.Kind.ASSIGNED,
    }:
        raise _invalid("kind", _("Choose an action."))
    if kind == SafeguardingAction.Kind.NOTE and not note.strip():
        raise _invalid("note", _("Write the note."))
    action = SafeguardingAction.objects.create(
        concern=concern, kind=kind, note=note.strip(), actor=user, occurred_at=now()
    )
    audit.record_create(action)
    if kind.startswith("referred_") and concern.status in {
        Concern.Status.OPEN,
        Concern.Status.IN_REVIEW,
    }:
        update_case(concern, status=Concern.Status.REFERRED, user=user)
    return action


@transaction.atomic
def update_case(
    concern: Concern,
    *,
    status: str | None = None,
    assigned_to: Any = None,
    outcome: str | None = None,
    user: Any = None,
) -> Concern:
    concern = Concern.objects.select_for_update().get(pk=concern.pk)
    if status is not None and status not in Concern.Status.values:
        raise _invalid("status", _("Unknown status."))
    if status == Concern.Status.CLOSED and not (outcome or concern.outcome).strip():
        raise _invalid("outcome", _("Record the outcome before closing the case."))
    if assigned_to is not None and not has_perm(assigned_to, "safeguarding.dsl"):
        raise _invalid("assigned_to", _("Cases can only be assigned to safeguarding leads."))
    with audit.track(concern):
        if outcome is not None:
            concern.outcome = outcome.strip()
        if assigned_to is not None and assigned_to.pk != concern.assigned_to_id:
            concern.assigned_to = assigned_to
            SafeguardingAction.objects.create(
                concern=concern,
                kind=SafeguardingAction.Kind.ASSIGNED,
                actor=user,
                occurred_at=now(),
                note=assigned_to.get_full_name() or assigned_to.email,
            )
        if status is not None and status != concern.status:
            SafeguardingAction.objects.create(
                concern=concern,
                kind=SafeguardingAction.Kind.STATUS_CHANGED,
                actor=user,
                occurred_at=now(),
                note=f"{concern.status} → {status}",
            )
            concern.status = status
            concern.closed_at = now() if status == Concern.Status.CLOSED else None
        concern.save()
    if status == Concern.Status.CLOSED:
        publish(SafeguardingConcernClosed(subject_id=concern.pk))
    return concern


# --- flagged messages ---------------------------------------------------------------------------


@transaction.atomic
def review_flag(
    flag: SafeguardingFlag, *, decision: str, user: Any = None, note: str = ""
) -> SafeguardingFlag:
    """``dismiss`` the flag, or ``escalate`` it into a new concern."""
    flag = SafeguardingFlag.objects.select_for_update().get(pk=flag.pk)
    if flag.status != SafeguardingFlag.Status.OPEN:
        raise BusinessRuleViolation(_("This flag has already been reviewed."))
    if decision not in {"dismiss", "escalate"}:
        raise _invalid("decision", _("Dismiss or escalate."))
    with audit.track(flag, action=decision):
        flag.reviewed_by = user
        flag.reviewed_at = now()
        if decision == "dismiss":
            flag.status = SafeguardingFlag.Status.DISMISSED
        else:
            flag.status = SafeguardingFlag.Status.ESCALATED
            flag.concern = raise_concern(
                user=user,
                category=Concern.Category.CONDUCT,
                description=note.strip()
                or _("Escalated from a flagged message: %(excerpt)s") % {"excerpt": flag.excerpt},
            )
        flag.save()
    return flag
