"""Outbox subscribers (E22): push lesson changes to connected calendars, provision online
meetings, and drive ``CalendarConnectionWorkflow``. Idempotent: pushes compare a content
hash, meetings reconcile to the lesson's current state, workflow starts are keyed by id."""

from __future__ import annotations

from typing import Any

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge
from tutortrack.scheduling.models import Lesson

from .processes import (
    MEETING_PROCESS,
    CalendarConnectionWorkflow,
    CalendarInput,
    MeetingInput,
    OnlineMeetingProvisioningWorkflow,
    calendar_workflow_id,
    meeting_workflow_id,
)

# lesson.updated fields that matter to the meeting (notes, colour... don't).
MEETING_FIELDS = {
    "online",
    "tutors",
    "attendees",
    "title",
    "service",
    "meeting_provider",
    "meeting_url",
}


# --- connection workflow -------------------------------------------------------------------------


def _calendar(e: EventEnvelope) -> bool:
    return e.data.get("level") == "user" and "calendar" in (e.data.get("capabilities") or [])


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


bridge.on(
    "integration.connected",
    start=CalendarConnectionWorkflow,
    id=lambda e: calendar_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: CalendarInput(
        organisation_id=str(e.organisation_id), connection_id=e.subject["id"]
    ),
    when=_calendar,
)
bridge.on(
    "integration.connected",
    signal="reconnected",
    id=lambda e: calendar_workflow_id(e.organisation_id, e.subject["id"]),
    when=lambda e: _calendar(e) and bool(e.data.get("reconnected")),
)
bridge.on(
    "integration.disconnected",
    signal="disconnect",
    id=lambda e: calendar_workflow_id(e.organisation_id, e.subject["id"]),
    when=lambda e: (
        _calendar(e) and _running(calendar_workflow_id(e.organisation_id, e.subject["id"]))
    ),
)
bridge.on(
    "calendar.settings_changed",
    signal="changed",
    id=lambda e: calendar_workflow_id(e.organisation_id, e.subject["id"]),
    when=lambda e: _running(calendar_workflow_id(e.organisation_id, e.subject["id"])),
)


# --- calendar push -------------------------------------------------------------------------------


def _has_calendars(lesson_ids: list[Any]) -> bool:
    from tutortrack.integrations.models import IntegrationConnection

    from .models import ExternalEventLink

    if ExternalEventLink.objects.filter(lesson_id__in=lesson_ids).exists():
        return True
    users = Lesson.objects.filter(pk__in=lesson_ids).values_list(
        "tutors__tutor__membership__user_id", flat=True
    )
    return IntegrationConnection.objects.filter(
        user_id__in=[u for u in users if u],
        status__in=["active", "error"],
        provider__in=["google", "microsoft", "caldav"],
    ).exists()


def _enqueue(organisation_id: Any, lesson_ids: list[str]) -> None:
    from . import tasks

    if not lesson_ids or not _has_calendars(lesson_ids):
        return
    for lesson_id in lesson_ids:
        tasks.sync_lesson.delay(organisation_id=str(organisation_id), lesson_id=lesson_id)


@subscribe("lesson.scheduled", "lesson.rescheduled", "lesson.updated", "lesson.cancelled")
def push_lesson(event: EventEnvelope) -> None:
    _enqueue(event.organisation_id, [event.subject["id"]])


def _series_lessons(series_id: str, *, online_only: bool = False) -> list[str]:
    from tutortrack.core.time import now

    qs = Lesson.objects.filter(series_id=series_id, start__gte=now(), status=Lesson.Status.PLANNED)
    if online_only:
        qs = qs.filter(online=True)
    return [str(pk) for pk in qs.order_by("start").values_list("pk", flat=True)]


@subscribe("lesson_series.created", "lesson_series.updated")
def push_series(event: EventEnvelope) -> None:
    _enqueue(event.organisation_id, _series_lessons(event.subject["id"]))


@receiver(pre_delete, sender=Lesson, dispatch_uid="calendar_sync.lesson_deleted")
def _lesson_deleted(sender: Any, instance: Lesson, **kwargs: Any) -> None:
    """Planned lessons can be deleted outright (no event): remove their external events
    and meeting rooms after the deletion commits."""
    from django.db import transaction

    from . import tasks
    from .models import ExternalEventLink, OnlineMeeting

    org = str(instance.organisation_id)
    items = [
        {"connection_id": str(c), "calendar_id": cal, "external_id": ext}
        for c, cal, ext in ExternalEventLink.objects.filter(lesson=instance).values_list(
            "connection_id", "calendar_id", "external_id"
        )
    ]
    if items:
        transaction.on_commit(lambda: tasks.delete_events.delay(organisation_id=org, items=items))
    meeting = OnlineMeeting.objects.filter(lesson=instance, status="active").first()
    if meeting is not None and meeting.external_id:
        args = {
            "organisation_id": org,
            "provider": meeting.provider,
            "connection_id": str(meeting.connection_id) if meeting.connection_id else None,
            "external_id": meeting.external_id,
        }
        transaction.on_commit(lambda: tasks.delete_meeting.delay(**args))


# --- online meetings -----------------------------------------------------------------------------


def _ours(e: EventEnvelope) -> bool:
    actor = e.actor or {}
    return actor.get("type") == "workflow" and str(actor.get("id", "")).startswith(
        f"{MEETING_PROCESS}:"
    )


def _needs_meeting_work(e: EventEnvelope) -> bool:
    from .models import OnlineMeeting

    if _ours(e):
        return False
    if e.type == "lesson.updated" and not set(e.data.get("fields") or []) & MEETING_FIELDS:
        return False
    lesson = Lesson.objects.filter(pk=e.subject["id"]).only("online", "status").first()
    if lesson is None:
        return False
    has_meeting = (
        OnlineMeeting.objects.filter(lesson_id=lesson.pk).exclude(status="deleted").exists()
    )
    return lesson.online or has_meeting


def _meeting_input(e: EventEnvelope) -> MeetingInput:
    return MeetingInput(organisation_id=str(e.organisation_id), lesson_ids=[e.subject["id"]])


for _type in ("lesson.scheduled", "lesson.rescheduled", "lesson.updated", "lesson.cancelled"):
    bridge.on(
        _type,
        start=OnlineMeetingProvisioningWorkflow,
        id=lambda e: meeting_workflow_id(e.organisation_id, e.subject["id"], e.id),
        input=_meeting_input,
        subject=lambda e: ("lesson", e.subject["id"]),
        when=_needs_meeting_work,
    )


def _series_meetings(e: EventEnvelope) -> MeetingInput:
    return MeetingInput(
        organisation_id=str(e.organisation_id),
        lesson_ids=_series_lessons(e.subject["id"], online_only=True),
    )


for _type in ("lesson_series.created", "lesson_series.updated"):
    bridge.on(
        _type,
        start=OnlineMeetingProvisioningWorkflow,
        id=lambda e: meeting_workflow_id(e.organisation_id, e.subject["id"], e.id),
        input=_series_meetings,
        subject=lambda e: ("lesson_series", e.subject["id"]),
        when=lambda e: bool(_series_lessons(e.subject["id"], online_only=True)),
    )
