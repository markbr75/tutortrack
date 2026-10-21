"""Waitlist suggestions when tutor capacity appears (gap G5c, FR-17-6).

Domain events tell us a tutor may have room (``leads.handlers.suggest_on_capacity``):

* ``availability.updated``: the tutor's weekly availability, extra availability or time off
  changed. They have room when they still have a free hour in the next two weeks and
  aren't at their weekly hours limit.
* ``job.status_changed`` (to completed, cancelled or paused) and ``job.tutor_removed``:
  the job's tutors lost lessons.
* ``tutor.status_changed`` (to active) and ``tutor.unrestricted``: the tutor can take
  work again.

For each waiting student (not class waitlists, which E20 handles) whose subject the tutor
is approved for, the E19 matching engine checks the hard filters (approved subject and
level, branch, not excluded, travel, the student's gender preference when allowed) and
scores the tutor. A match becomes a ``WaitlistSuggestion`` and staff with
``leads.waitlist.manage`` are told once per tutor and event. Staff offer the place from
the suggestion (the E17 offer link) or dismiss it.

Idempotent: there is one suggestion per waiting entry and tutor. Replaying an event only
refreshes the score of open suggestions; dismissed or used ones are never raised again.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from tutortrack.core import audit
from tutortrack.core.events import EventEnvelope, publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.people.models import TutorProfile, TutorSubject

from . import events
from .models import WaitlistEntry, WaitlistSuggestion

R = WaitlistSuggestion.Reason
CAPACITY_EVENTS = (
    "availability.updated",
    "job.status_changed",
    "job.tutor_removed",
    "tutor.status_changed",
    "tutor.unrestricted",
)
ENDED = ("completed", "cancelled", "paused")
LOOKAHEAD_DAYS = 14
LESSON_MINUTES = 60


def reason_and_tutors(event: EventEnvelope) -> tuple[str, list[str]]:
    """Which tutors may now have room, and why. Empty when the event frees nothing."""
    data = event.data or {}
    subject_id = str(event.subject.get("id", ""))
    if event.type == "availability.updated":
        return R.AVAILABILITY, [subject_id]
    if event.type == "tutor.unrestricted":
        return R.TUTOR_AVAILABLE, [subject_id]
    if event.type == "tutor.status_changed":
        return (R.TUTOR_AVAILABLE, [subject_id]) if data.get("new_status") == "active" else ("", [])
    if event.type == "job.tutor_removed":
        return R.JOB_ENDED, [str(data.get("tutor_id", ""))]
    if event.type == "job.status_changed" and data.get("to_status") in ENDED:
        from tutortrack.jobs.models import JobTutor

        tutors = JobTutor.objects.filter(
            job_id=subject_id, status__in=[JobTutor.Status.ACTIVE, JobTutor.Status.ENDED]
        ).values_list("tutor_id", flat=True)
        return R.JOB_ENDED, sorted({str(t) for t in tutors})
    return "", []


def has_room(tutor: TutorProfile) -> bool:
    """Below the weekly hours limit and, with availability set, a free lesson-length slot
    in the next two weeks."""
    from tutortrack.recruitment.compliance import today
    from tutortrack.scheduling.availability import free_slots, has_template
    from tutortrack.scheduling.selectors import scheduled_minutes

    if tutor.max_weekly_hours:
        start = now()
        booked = scheduled_minutes([str(tutor.pk)], start, start + timedelta(weeks=4))
        per_week = booked.get(str(tutor.pk), 0) / 60 / 4
        if per_week + LESSON_MINUTES / 60 > tutor.max_weekly_hours:
            return False
    if not has_template(tutor.pk):
        return True  # no availability set: the hours limit is all we know
    first = today()
    return bool(
        free_slots(
            tutor.pk,
            start=first,
            end=first + timedelta(days=LOOKAHEAD_DAYS),
            duration_minutes=LESSON_MINUTES,
            step_minutes=LESSON_MINUTES,
        )
    )


def _approved_subjects(tutor: TutorProfile) -> set[str]:
    names: set[str] = set()
    for name, catalogue in TutorSubject.objects.filter(tutor=tutor, approved=True).values_list(
        "subject", "catalogue_subject__name"
    ):
        names |= {n.casefold() for n in (name, catalogue) if n}
    return names


def _entry_subject(entry: WaitlistEntry) -> tuple[Any, Any]:
    """The catalogue subject and level the student waits for (from the service, else by
    name)."""
    from tutortrack.catalogue.models import Level, Subject

    service = entry.service
    if service is not None and service.subject_id:
        return service.subject, service.level if service.level_id else None
    subject = Subject.objects.filter(name__iexact=entry.subject).first() if entry.subject else None
    level = (
        Level.objects.filter(subject=subject, name__iexact=entry.level).first()
        if subject is not None and entry.level
        else None
    )
    return subject, level


def score(entry: WaitlistEntry, tutor: TutorProfile) -> Any:
    """The tutor's match score for the waiting student, or ``None`` when a hard filter
    rules them out (E19 engine, limited to this tutor)."""
    from tutortrack.matching import engine

    subject, level = _entry_subject(entry)
    student = entry.student
    place = student.lesson_address
    criteria = engine.Criteria(
        subject_id=str(subject.pk) if subject is not None else None,
        subject_name=subject.name if subject is not None else entry.subject,
        level_id=str(level.pk) if level is not None else None,
        branch_id=str(entry.branch_id),
        start_date=now().date(),
        lat=place.lat if place is not None else None,
        lng=place.lng if place is not None else None,
        exclude={str(t) for t in student.excluded_tutors.values_list("pk", flat=True)},
        **engine.student_needs([student], subject),
    )
    matches = engine.search(criteria, only=[str(tutor.pk)], limit=1)
    return matches[0].score if matches else None


def suggest_for_tutor(tutor_id: Any, reason: str) -> list[WaitlistSuggestion]:
    """Suggest the tutor for each waiting student they fit; returns the new suggestions."""
    tutor = TutorProfile.objects.filter(
        pk=tutor_id, status=TutorProfile.Status.ACTIVE, archived_at__isnull=True
    ).first()
    if tutor is None or (reason != R.JOB_ENDED and not has_room(tutor)):
        return []
    subjects = _approved_subjects(tutor)
    if not subjects:
        return []
    entries = (
        WaitlistEntry.objects.filter(
            status=WaitlistEntry.Status.WAITING, group_class_id__isnull=True
        )
        .filter(Q(tutor__isnull=True) | Q(tutor=tutor))  # or waiting for this tutor
        .select_related("student__lesson_address", "service__subject", "service__level")
    )
    known = {
        s.entry_id: s for s in WaitlistSuggestion.objects.filter(tutor=tutor, entry__in=entries)
    }
    created: list[WaitlistSuggestion] = []
    for entry in entries:
        wanted = entry.service.subject.name if entry.service and entry.service.subject_id else ""
        wanted = wanted or entry.subject
        if wanted and wanted.casefold() not in subjects:
            continue
        existing = known.get(entry.pk)
        if existing is not None and existing.status != WaitlistSuggestion.Status.OPEN:
            continue
        value = score(entry, tutor)
        if value is None:
            continue
        if existing is not None:
            existing.score, existing.reason = value, reason
            existing.save(update_fields=["score", "reason", "updated_at"])
            continue
        suggestion = _create(entry, tutor, reason, value)
        if suggestion is not None:
            created.append(suggestion)
    return created


def _create(
    entry: WaitlistEntry, tutor: TutorProfile, reason: str, value: Any
) -> WaitlistSuggestion | None:
    try:
        with transaction.atomic():
            suggestion = WaitlistSuggestion.objects.create(
                entry=entry, tutor=tutor, reason=reason, score=value, branch_id=entry.branch_id
            )
            audit.record_create(suggestion)
            publish(
                events.WaitlistSuggestionCreated(
                    subject_id=suggestion.pk,
                    entry_id=str(entry.pk),
                    student_id=str(entry.student_id),
                    tutor_id=str(tutor.pk),
                    reason=reason,
                ),
                branch_id=entry.branch_id,
            )
    except IntegrityError:
        return None  # another worker raised it first
    return suggestion


def capacity_appeared(event: EventEnvelope) -> int:
    """React to a capacity event: suggest, and tell staff once per tutor and event."""
    from tutortrack.comms import services as comms

    reason, tutor_ids = reason_and_tutors(event)
    total = 0
    for tutor_id in tutor_ids:
        if not tutor_id:
            continue
        created = suggest_for_tutor(tutor_id, reason)
        if not created:
            continue
        total += len(created)
        name = created[0].tutor.full_name
        title = ngettext(
            "%(tutor)s has room for %(count)s waiting student",
            "%(tutor)s has room for %(count)s waiting students",
            len(created),
        ) % {"tutor": name, "count": len(created)}
        comms.notify(
            "staff_waitlist_suggestion",
            (title, str(WaitlistSuggestion.Reason(reason).label), "/leads/waitlist"),
            key=f"waitlist-suggestion:{tutor_id}:{event.id}",
        )
    return total


# --- staff decisions ----------------------------------------------------------------------------


def close_for_entry(entry: WaitlistEntry) -> int:
    """The student isn't waiting any more (offered a place, removed): close open
    suggestions."""
    return WaitlistSuggestion.objects.filter(
        entry=entry, status=WaitlistSuggestion.Status.OPEN
    ).update(status=WaitlistSuggestion.Status.CLOSED, decided_at=now(), updated_at=now())


def _open(suggestion: WaitlistSuggestion) -> WaitlistSuggestion:
    locked = WaitlistSuggestion.objects.select_for_update().get(pk=suggestion.pk)
    if locked.status != WaitlistSuggestion.Status.OPEN:
        raise BusinessRuleViolation(_("This suggestion has already been dealt with."))
    return locked


@transaction.atomic
def offer_from_suggestion(
    suggestion: WaitlistSuggestion, *, details: str = "", hours: int | None = None, user: Any
) -> WaitlistSuggestion:
    """Offer the waiting student a place with the suggested tutor (E17 offer link)."""
    from . import services

    suggestion = _open(suggestion)
    details = details.strip() or _("A place with %(tutor)s") % {"tutor": suggestion.tutor.full_name}
    services.offer_place(suggestion.entry, details=details, hours=hours)
    with audit.track(suggestion, action="offer"):
        suggestion.status = WaitlistSuggestion.Status.OFFERED
        suggestion.decided_by = user if getattr(user, "is_authenticated", False) else None
        suggestion.decided_at = now()
        suggestion.save()
    return suggestion


@transaction.atomic
def dismiss(suggestion: WaitlistSuggestion, *, user: Any) -> WaitlistSuggestion:
    suggestion = _open(suggestion)
    with audit.track(suggestion, action="dismiss"):
        suggestion.status = WaitlistSuggestion.Status.DISMISSED
        suggestion.decided_by = user if getattr(user, "is_authenticated", False) else None
        suggestion.decided_at = now()
        suggestion.save()
    return suggestion
