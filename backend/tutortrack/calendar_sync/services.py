"""Calendar sync writes (E22-T02..T05).

* **Push** (outbox-driven): ``sync_lesson`` reconciles a lesson's events in its tutors'
  connected calendars: create, update (only when the content changed), delete when the
  lesson is cancelled or a tutor leaves it. Events carry the lesson id in provider
  metadata.
* **Read busy**: ``sync_connection`` pulls incremental changes (sync tokens / delta links,
  or a full time-range listing for CalDAV) of the chosen calendars into
  ``ExternalBusyBlock`` rows: times only, never titles.
* **Two-way edits** (T03, opt-in): a TutorTrack event moved outside is applied when the
  calendar's owner may edit the lesson, otherwise it becomes a reschedule request (a CRM
  task for the job's account manager) and the event is put back. An event deleted outside
  never cancels the lesson: it is re-created and the tutor is warned.
* **Channels**: ``prepare`` creates the "TutorTrack" calendar and renews push channels
  (Google watch, Graph subscriptions) before they expire.

Long-running orchestration (polling, renewals, backoff) lives in
``CalendarConnectionWorkflow``; everything here is idempotent.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import structlog
from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.integrations import providers
from tutortrack.integrations import services as integrations
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import (
    AuthError,
    CalendarClient,
    Credentials,
    EventBody,
    ExternalEvent,
    NotFound,
    ProviderError,
    SyncTokenExpired,
)
from tutortrack.scheduling.models import Lesson

from . import events
from .models import CalendarSyncSettings, ExternalBusyBlock, ExternalEventLink, SyncState

logger = structlog.get_logger(__name__)
CALENDAR_NAME = "TutorTrack"
WINDOW_PAST = timedelta(days=1)
WINDOW_AHEAD = timedelta(days=120)
PUSH_AHEAD = timedelta(days=120)
RENEW_BEFORE = timedelta(hours=12)
CHANNEL_TTL = {"google": timedelta(days=7), "microsoft": timedelta(days=2, hours=12)}
LIVE = (IntegrationConnection.Status.ACTIVE, IntegrationConnection.Status.ERROR)


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def _setting(key: str) -> Any:
    from tutortrack.tenancy.settings_service import get_setting

    return get_setting(key)


def is_calendar(connection: IntegrationConnection) -> bool:
    return (
        connection.user_id is not None
        and "calendar" in providers.get_spec(connection.provider).capabilities
    )


# --- settings -----------------------------------------------------------------------------------


def settings_for(connection: IntegrationConnection) -> CalendarSyncSettings:
    found, _created = CalendarSyncSettings.objects.get_or_create(
        connection=connection, defaults={"user_id": connection.user_id}
    )
    return found


def initialise(connection: IntegrationConnection, creds: Credentials) -> CalendarSyncSettings:
    """First run: read the primary calendar as busy and write lessons into a dedicated
    "TutorTrack" calendar we create (users can change both)."""
    sync = settings_for(connection)
    client = providers.calendar_client(connection.provider)
    if not sync.read_calendar_ids and not connection.settings.get("calendar_initialised"):
        primary = next((c for c in client.list_calendars(creds) if c.primary), None)
        sync.read_calendar_ids = [primary.id] if primary else []
        sync.save(update_fields=["read_calendar_ids", "updated_at"])
    if sync.write_enabled and not sync.write_calendar_id:
        tz = connection.user.timezone if connection.user else "UTC"
        sync.write_calendar_id = client.create_calendar(creds, CALENDAR_NAME, tz)
        sync.save(update_fields=["write_calendar_id", "updated_at"])
    if not connection.settings.get("calendar_initialised"):
        integrations.update_settings(connection, calendar_initialised=True)
    return sync


@transaction.atomic
def update_sync_settings(sync: CalendarSyncSettings, **changes: Any) -> CalendarSyncSettings:
    if changes.get("two_way") and not _setting("integrations.calendar_two_way"):
        raise _invalid("two_way", _("Your organisation hasn't turned on two-way sync."))
    old_write = sync.write_calendar_id
    with audit.track(sync):
        for key, value in changes.items():
            setattr(sync, key, value)
        sync.save()
    if "write_calendar_id" in changes and changes["write_calendar_id"] != old_write:
        # Lessons move to the new calendar on the next push; the old events are removed.
        connection_id = sync.connection_id
        transaction.on_commit(lambda: _enqueue_backfill(connection_id))
    publish(events.CalendarSettingsChanged(subject_id=sync.connection_id))
    return sync


def _enqueue_backfill(connection_id: Any) -> None:
    from tutortrack.core.context import require_organisation_id

    from . import tasks

    tasks.backfill.delay(
        organisation_id=str(require_organisation_id()), connection_id=str(connection_id)
    )


# --- push: lessons -> calendars -------------------------------------------------------------------


def _tutor_users(lesson: Lesson) -> dict[str, Any]:
    """{user id: tutor} for the lesson's tutors who have an active membership."""
    out = {}
    for link in lesson.tutors.select_related("tutor__membership"):
        membership = link.tutor.membership
        if membership is not None and membership.status == "active":
            out[str(membership.user_id)] = link.tutor
    return out


def targets(lesson: Lesson) -> list[tuple[IntegrationConnection, CalendarSyncSettings]]:
    users = _tutor_users(lesson)
    if not users:
        return []
    found = []
    connections = IntegrationConnection.objects.filter(
        user_id__in=list(users), status__in=LIVE
    ).select_related("user")
    for connection in connections:
        if not is_calendar(connection):
            continue
        sync = settings_for(connection)
        if sync.write_enabled:
            found.append((connection, sync))
    return found


class _Format(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def event_title(lesson: Lesson, sync: CalendarSyncSettings) -> str:
    pattern = sync.title_format or str(_setting("integrations.calendar_title_format"))
    students = [a.student for a in lesson.attendees.select_related("student")]
    tutors = [t.tutor for t in lesson.tutors.select_related("tutor")]
    values = _Format(
        title=lesson.title,
        service=lesson.service.name,
        students=", ".join(s.full_name for s in students),
        student_initials=", ".join(f"{s.first_name} {s.last_name[:1]}.".strip() for s in students),
        tutors=", ".join(t.full_name for t in tutors),
    )
    try:
        title = pattern.format_map(values)
    except (ValueError, IndexError):
        title = lesson.title
    return title.strip()[:250] or lesson.title


def event_body(lesson: Lesson, sync: CalendarSyncSettings) -> EventBody:
    from tutortrack.scheduling.external import join_link

    link = join_link(lesson, "host") if lesson.online else None
    description = _("Managed by TutorTrack: change this lesson in TutorTrack.")
    if _setting("integrations.calendar_details") and lesson.notes_for_tutor:
        description = f"{lesson.notes_for_tutor}\n\n{description}"
    return EventBody(
        lesson_id=str(lesson.pk),
        title=event_title(lesson, sync),
        start=lesson.start,
        end=lesson.end,
        timezone=lesson.timezone,
        location=lesson.location.name if lesson.location_id and lesson.location else "",
        description=description,
        join_url=link.url if link else "",
    )


def _hash(body: EventBody, calendar_id: str) -> str:
    raw = json.dumps(
        [
            calendar_id,
            body.title,
            body.start.isoformat(),
            body.end.isoformat(),
            body.location,
            body.description,
            body.join_url,
        ],
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _write_calendar(
    connection: IntegrationConnection, sync: CalendarSyncSettings, creds: Credentials
) -> str:
    if not sync.write_calendar_id:
        sync = initialise(connection, creds)
    return sync.write_calendar_id


def push(
    connection: IntegrationConnection,
    sync: CalendarSyncSettings,
    lesson: Lesson,
    link: ExternalEventLink | None,
    *,
    force: bool = False,
) -> str:
    """Create or update the lesson's event in this connection's write calendar."""
    creds = integrations.credentials(connection)
    calendar_id = _write_calendar(connection, sync, creds)
    body = event_body(lesson, sync)
    digest = _hash(body, calendar_id)
    if link is not None and link.content_hash == digest and not force:
        return "unchanged"
    client = providers.calendar_client(connection.provider)
    external_id = ""
    if link is not None:
        if link.calendar_id == calendar_id:
            external_id = link.external_id
        else:
            _delete_quietly(client, creds, link.calendar_id, link.external_id)
    try:
        pushed = client.put_event(creds, calendar_id, body, external_id)
    except NotFound:
        pushed = client.put_event(creds, calendar_id, body, "")  # gone outside: re-create
    values = {
        "provider": connection.provider,
        "calendar_id": calendar_id,
        "external_id": pushed.external_id,
        "etag": pushed.etag,
        "content_hash": digest,
        "pushed_start": lesson.start,
        "pushed_end": lesson.end,
        "last_pushed_at": now(),
        "proposed_start": None,
    }
    ExternalEventLink.objects.update_or_create(
        lesson=lesson, connection=connection, defaults=values
    )
    return "created" if not external_id else "updated"


def _delete_quietly(client: CalendarClient, creds: Credentials, calendar_id: str, ext: str) -> None:
    with contextlib.suppress(NotFound):
        client.delete_event(creds, calendar_id, ext)


def unpush(link: ExternalEventLink) -> None:
    connection = link.connection
    if connection.status in LIVE:
        creds = integrations.credentials(connection)
        client = providers.calendar_client(connection.provider)
        _delete_quietly(client, creds, link.calendar_id, link.external_id)
    link.delete()


def sync_lesson(lesson_id: Any) -> dict[str, int]:
    """Reconcile one lesson's external events. Provider failures are recorded on the
    connection (error status, owner told) and counted; the caller retries later."""
    counts = {"pushed": 0, "removed": 0, "failed": 0}
    lesson = Lesson.objects.select_related("service", "location").filter(pk=lesson_id).first()
    links = {
        str(link.connection_id): link
        for link in ExternalEventLink.objects.filter(lesson_id=lesson_id).select_related(
            "connection"
        )
    }
    wanted = []
    current = lesson is not None and lesson.status != Lesson.Status.CANCELLED
    if current and lesson is not None and lesson.end >= now() - WINDOW_PAST:
        wanted = targets(lesson)
    wanted_ids = {str(c.pk) for c, _s in wanted}
    for connection_id, link in links.items():
        if connection_id in wanted_ids:
            continue
        try:
            unpush(link)
            counts["removed"] += 1
        except ProviderError as exc:
            counts["failed"] += 1
            integrations.record_failure(link.connection, exc)
    for connection, sync in wanted:
        try:
            outcome = push(connection, sync, lesson, links.get(str(connection.pk)))
        except ProviderError as exc:
            counts["failed"] += 1
            integrations.record_failure(connection, exc)
            continue
        if outcome != "unchanged":
            counts["pushed"] += 1
    return counts


def lessons_for_user(user_id: Any) -> Any:
    start = now() - WINDOW_PAST
    return (
        Lesson.objects.filter(
            tutors__tutor__membership__user_id=user_id,
            start__gte=start,
            start__lt=now() + PUSH_AHEAD,
        )
        .exclude(status=Lesson.Status.CANCELLED)
        .distinct()
    )


def backfill(connection: IntegrationConnection) -> int:
    """Push the user's upcoming lessons (first connection, write calendar changed, and once
    per workflow run to catch anything a failed push missed)."""
    pushed = 0
    for lesson_id in lessons_for_user(connection.user_id).values_list("pk", flat=True):
        pushed += sync_lesson(lesson_id)["pushed"]
    return pushed


# --- channels -------------------------------------------------------------------------------------


def channel_token(organisation_id: Any, state_id: Any) -> str:
    """Short (Graph allows 128 chars), verifiable without a database lookup."""
    org, state = uuid.UUID(str(organisation_id)).hex, uuid.UUID(str(state_id)).hex
    mac = hmac.new(settings.SECRET_KEY.encode(), f"channel:{org}:{state}".encode(), "sha256")
    return f"{org}.{state}.{mac.hexdigest()[:32]}"


def read_channel_token(token: str) -> tuple[str, str] | None:
    try:
        org, state, mac = token.split(".")
        expected = channel_token(org, state).split(".")[2]
    except ValueError:
        return None
    if not hmac.compare_digest(mac, expected):
        return None
    return str(uuid.UUID(org)), str(uuid.UUID(state))


def webhook_address(provider: str) -> str:
    base = settings.INTEGRATIONS["WEBHOOK_BASE_URL"].rstrip("/")
    path = "google-calendar" if provider == "google" else "microsoft-graph"
    return f"{base}/webhooks/{path}"


def watched_calendars(sync: CalendarSyncSettings) -> dict[str, bool]:
    """{calendar id: read as busy?}; the write calendar is watched for two-way edits."""
    out = dict.fromkeys(sync.read_calendar_ids, True)
    if sync.two_way and sync.write_enabled and sync.write_calendar_id:
        out.setdefault(sync.write_calendar_id, False)
    return out


def _renew(
    connection: IntegrationConnection, creds: Credentials, state: SyncState, client: CalendarClient
) -> None:
    ttl = CHANNEL_TTL.get(connection.provider, timedelta(days=7))
    if state.channel_id:
        with contextlib.suppress(ProviderError):
            client.stop(creds, state.channel_id, state.channel_resource_id)
    channel = client.watch(
        creds,
        state.calendar_id,
        address=webhook_address(connection.provider),
        channel_id=uuid.uuid4().hex,
        token=channel_token(state.organisation_id, state.pk),
        expires_at=now() + ttl,
    )
    state.channel_id = channel.id if channel else ""
    state.channel_resource_id = channel.resource_id if channel else ""
    state.channel_expiry = channel.expires_at if channel else None
    state.save(update_fields=["channel_id", "channel_resource_id", "channel_expiry", "updated_at"])


def prepare(connection_id: Any) -> dict[str, Any]:
    """Refresh the token, initialise calendars, renew channels expiring soon. Returns the
    workflow's plan: ``status`` and how long to wait (polling, next renewal)."""
    connection = IntegrationConnection.objects.select_related("user").get(pk=connection_id)
    spec = providers.get_spec(connection.provider)
    if connection.status == IntegrationConnection.Status.DISCONNECTED:
        return {"status": "disconnected"}
    if connection.status == IntegrationConnection.Status.NEEDS_RECONNECT:
        return {"status": "needs_reconnect"}
    poll = spec.poll_minutes * 60
    try:
        creds = integrations.credentials(connection)
        sync = initialise(connection, creds)
        client = providers.calendar_client(connection.provider)
        watched = watched_calendars(sync)
        renew_in = 24 * 3600
        for stale in SyncState.objects.filter(connection=connection).exclude(
            calendar_id__in=list(watched)
        ):
            if stale.channel_id:
                with contextlib.suppress(ProviderError):
                    client.stop(creds, stale.channel_id, stale.channel_resource_id)
            ExternalBusyBlock.objects.filter(
                connection=connection, calendar_id=stale.calendar_id
            ).delete()
            stale.delete()
        for calendar_id in watched:
            state, _created = SyncState.objects.get_or_create(
                connection=connection, calendar_id=calendar_id
            )
            if spec.key in CHANNEL_TTL and (
                state.channel_expiry is None or state.channel_expiry <= now() + RENEW_BEFORE
            ):
                _renew(connection, creds, state, client)
            if state.channel_expiry is not None:
                until = (state.channel_expiry - RENEW_BEFORE - now()).total_seconds()
                renew_in = min(renew_in, max(int(until), 60))
    except AuthError as exc:
        integrations.record_failure(connection, exc)
        return {"status": "needs_reconnect"}
    except ProviderError as exc:
        integrations.record_failure(connection, exc)
        raise
    return {"status": "active", "poll_seconds": poll, "renew_in_seconds": renew_in}


# --- read: calendars -> busy blocks ---------------------------------------------------------------


def sync_connection(connection_id: Any) -> dict[str, Any]:
    connection = IntegrationConnection.objects.select_related("user").get(pk=connection_id)
    if connection.status not in LIVE:
        return {"status": connection.status, "changed": 0}
    try:
        creds = integrations.credentials(connection)
        sync = settings_for(connection)
        changed = 0
        for calendar_id, read_busy in watched_calendars(sync).items():
            changed += _sync_calendar(connection, sync, creds, calendar_id, read_busy=read_busy)
    except AuthError as exc:
        integrations.record_failure(connection, exc)
        return {"status": "needs_reconnect", "changed": 0}
    except ProviderError as exc:
        integrations.record_failure(connection, exc)
        raise
    integrations.record_success(connection, synced=True)
    if changed:
        with transaction.atomic():
            publish(
                events.CalendarBusyUpdated(
                    subject_id=connection.pk, user_id=str(connection.user_id), changed=changed
                )
            )
    return {"status": "active", "changed": changed}


def _sync_calendar(
    connection: IntegrationConnection,
    sync: CalendarSyncSettings,
    creds: Credentials,
    calendar_id: str,
    *,
    read_busy: bool,
) -> int:
    client = providers.calendar_client(connection.provider)
    state, _created = SyncState.objects.get_or_create(
        connection=connection, calendar_id=calendar_id
    )
    window = {"window_start": now() - WINDOW_PAST, "window_end": now() + WINDOW_AHEAD}
    try:
        changes = client.changes(creds, calendar_id, state.sync_token, **window)
    except SyncTokenExpired:
        changes = client.changes(creds, calendar_id, "", **window)
    links = {
        link.external_id: link
        for link in ExternalEventLink.objects.filter(
            connection=connection, calendar_id=calendar_id
        ).select_related("lesson")
    }
    changed = 0
    seen: set[str] = set()
    with transaction.atomic():
        for event in changes.events:
            seen.add(event.id)
            link = links.get(event.id)
            if link is not None or event.lesson_id:
                if link is not None and sync.two_way and calendar_id == sync.write_calendar_id:
                    _external_change(connection, sync, link, event)
                continue  # our own lessons are never busy blocks
            if read_busy:
                changed += _apply_busy(connection, calendar_id, event)
        if changes.full:
            if read_busy:
                gone = ExternalBusyBlock.objects.filter(
                    connection=connection, calendar_id=calendar_id
                ).exclude(external_id__in=seen)
                changed += gone.delete()[0]
            if sync.two_way and calendar_id == sync.write_calendar_id:
                lo, hi = window["window_start"], window["window_end"]
                for external_id, link in links.items():
                    if external_id not in seen and lo <= link.lesson.start <= hi:
                        _external_change(
                            connection, sync, link, ExternalEvent(external_id, cancelled=True)
                        )
        state.sync_token = changes.next_token
        state.last_synced_at = now()
        if changes.full:
            state.last_full_sync_at = now()
        state.save(
            update_fields=["sync_token", "last_synced_at", "last_full_sync_at", "updated_at"]
        )
    return changed


def _apply_busy(connection: IntegrationConnection, calendar_id: str, event: ExternalEvent) -> int:
    existing = ExternalBusyBlock.objects.filter(
        connection=connection, calendar_id=calendar_id, external_id=event.id
    )
    if event.cancelled or not event.busy or event.start is None or event.end is None:
        return existing.delete()[0]
    ExternalBusyBlock.objects.update_or_create(
        connection=connection,
        calendar_id=calendar_id,
        external_id=event.id,
        defaults={
            "user_id": connection.user_id,
            "source": connection.provider,
            "start": event.start,
            "end": event.end,
            "all_day": event.all_day,
        },
    )
    return 1


def clear(connection: IntegrationConnection) -> None:
    """After disconnecting: stop channels (best effort) and forget synced state."""
    states = list(SyncState.objects.filter(connection=connection))
    ExternalBusyBlock.objects.filter(connection=connection).delete()
    ExternalEventLink.objects.filter(connection=connection).delete()
    for state in states:
        state.delete()


# --- two-way edits (T03) --------------------------------------------------------------------------


def _external_change(
    connection: IntegrationConnection,
    sync: CalendarSyncSettings,
    link: ExternalEventLink,
    event: ExternalEvent,
) -> None:
    lesson = link.lesson
    if lesson.status != Lesson.Status.PLANNED:
        return
    if event.cancelled:
        _restore(connection, sync, link, lesson)
        return
    if event.start is None or event.end is None:
        return
    if event.start == link.pushed_start and event.end == link.pushed_end:
        return  # an edit of something else (title, colour): ours wins on the next push
    if link.proposed_start == event.start:
        return  # already proposed
    _propose_move(connection, sync, link, lesson, event.start, event.end)


def _restore(
    connection: IntegrationConnection,
    sync: CalendarSyncSettings,
    link: ExternalEventLink,
    lesson: Lesson,
) -> None:
    from tutortrack.integrations.notifications import notify_calendar

    link.external_id = ""  # forces a new event
    push(connection, sync, lesson, link, force=True)
    audit.record(lesson, "calendar_restored", {"provider": connection.provider})
    notify_calendar(
        connection.user_id,
        _("Lesson put back in your calendar"),
        _(
            "%(lesson)s was deleted from your calendar, but it is still booked. To cancel it, "
            "cancel it in TutorTrack."
        )
        % {"lesson": lesson.title},
        key=f"restored:{lesson.pk}:{now().date()}",
    )


def _propose_move(
    connection: IntegrationConnection,
    sync: CalendarSyncSettings,
    link: ExternalEventLink,
    lesson: Lesson,
    start: datetime,
    end: datetime,
) -> None:
    """Apply the move if the calendar's owner may edit the lesson; otherwise create a
    reschedule request for the coordinator and put the event back."""
    from tutortrack.core.permissions import has_perm
    from tutortrack.integrations.notifications import notify_calendar
    from tutortrack.scheduling import services as scheduling

    user = connection.user
    provider = providers.get_spec(connection.provider).label
    if user is not None and has_perm(user, "scheduling.lesson.edit", lesson):
        try:
            with transaction.atomic():
                scheduling.update_lesson(
                    lesson, start=start, end=end, reason=_("Moved in %(p)s") % {"p": provider}
                )
            link.refresh_from_db()
            link.pushed_start, link.pushed_end = start, end
            link.save(update_fields=["pushed_start", "pushed_end", "updated_at"])
            return
        except BusinessRuleViolation as exc:
            logger.info("calendar_sync.move_rejected", lesson=str(lesson.pk), reason=str(exc))
    from tutortrack.crm import services as crm

    when = start.strftime("%Y-%m-%d %H:%M %Z")
    crm.create_task(
        title=_("Reschedule request: %(lesson)s") % {"lesson": lesson.title[:150]},
        description=_(
            "%(user)s moved this lesson to %(when)s in %(provider)s. Reschedule it in "
            "TutorTrack if that works for everyone."
        )
        % {"user": user.get_full_name() if user else "", "when": when, "provider": provider},
        target_type="scheduling.lesson",
        target_id=str(lesson.pk),
        assignee=lesson.job.account_manager if lesson.job_id and lesson.job else None,
        due_at=lesson.start,
    )
    link.proposed_start = start
    link.save(update_fields=["proposed_start", "updated_at"])
    push(connection, sync, lesson, link, force=True)  # the calendar shows the real time again
    link.refresh_from_db()
    link.proposed_start = start
    link.save(update_fields=["proposed_start", "updated_at"])
    publish(
        events.RescheduleProposed(
            subject_id=lesson.pk,
            user_id=str(connection.user_id),
            proposed_start=start.isoformat(),
            proposed_end=end.isoformat(),
            provider=connection.provider,
        )
    )
    notify_calendar(
        connection.user_id,
        _("Reschedule requested"),
        _(
            "You moved %(lesson)s in your calendar. We've asked the office to reschedule it; "
            "until then it stays at its original time."
        )
        % {"lesson": lesson.title},
        key=f"proposed:{lesson.pk}:{start.isoformat()}",
    )
