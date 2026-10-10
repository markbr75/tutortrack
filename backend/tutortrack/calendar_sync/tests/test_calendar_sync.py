"""E22-T02..T05: lessons pushed to calendars, busy blocks in conflicts and availability,
two-way edits, Microsoft Graph, CalDAV polling, push webhooks."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from django.db import transaction

from tutortrack.calendar_sync import services
from tutortrack.calendar_sync.models import (
    CalendarSyncSettings,
    ExternalBusyBlock,
    ExternalEventLink,
    SyncState,
)
from tutortrack.comms.models import InAppNotification
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.crm.models import Task
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations.providers.fake import FakeCalendar
from tutortrack.jobs import services as jobs
from tutortrack.scheduling import availability, conflicts
from tutortrack.scheduling import services as scheduling
from tutortrack.scheduling.models import AvailabilityTemplate, AvailabilityWindow, Lesson
from tutortrack.scheduling.services import ConflictError

from .conftest import LONDON, connect, make_lesson, settle, slot

pytestmark = pytest.mark.django_db


@pytest.fixture
def google(org, people):
    conn = connect(org, people["user"])
    with tenant_context(org):
        services.prepare(conn.pk)  # creates the "TutorTrack" calendar, channels
        conn.refresh_from_db()
    settle(org)
    return conn


def fake_for(conn) -> FakeCalendar:
    return FakeCalendar(conn.external_account_id)


def write_calendar(org, conn) -> str:
    with tenant_context(org):
        return CalendarSyncSettings.objects.get(connection=conn).write_calendar_id


def sync(org, conn) -> dict:
    with tenant_context(org):
        return services.sync_connection(conn.pk)


# --- FR-22-1 push ------------------------------------------------------------------------------


def test_lessons_are_written_to_a_dedicated_calendar_with_the_lesson_id(org, people, google):
    lesson = make_lesson(org, people)
    dispatch_batch()  # lesson.scheduled → push
    store = fake_for(google)
    calendar_id = write_calendar(org, google)
    assert store.load()["calendars"][calendar_id]["name"] == "TutorTrack"
    found = store.find_lesson(str(lesson.pk))
    assert found is not None
    cal, _event_id, row = found
    assert cal == calendar_id
    assert row["title"] == "Maths 1:1 \N{EN DASH} Arjun Patel"  # default title format
    assert "notes" not in row["description"].lower()  # no sensitive data by default
    with tenant_context(org):
        assert ExternalEventLink.objects.get(lesson=lesson).pushed_start == lesson.start


def test_moves_cancellations_and_removed_tutors_follow_the_lesson(org, people, google):
    lesson = make_lesson(org, people)
    dispatch_batch()
    store = fake_for(google)
    later = lesson.start + timedelta(hours=2)
    with tenant_context(org), transaction.atomic():
        scheduling.update_lesson(lesson, start=later, end=later + timedelta(hours=1))
    dispatch_batch()  # lesson.rescheduled
    _cal, _eid, row = store.find_lesson(str(lesson.pk))
    assert datetime.fromisoformat(row["start"]) == later
    with tenant_context(org):
        other = MembershipFactory(organisation=org, role="tutor")
        from tutortrack.people.tests.factories import TutorProfileFactory

        cover = TutorProfileFactory(organisation=org, status="active", membership=other)
        with transaction.atomic():
            scheduling.update_lesson(lesson, tutors=[{"tutor": cover}])
    dispatch_batch()  # lesson.updated(tutors): Nia isn't teaching it any more
    assert store.find_lesson(str(lesson.pk)) is None
    second = make_lesson(org, people, start=slot(days=4))
    dispatch_batch()
    assert store.find_lesson(str(second.pk)) is not None
    with tenant_context(org), transaction.atomic():
        scheduling.cancel_lesson(Lesson.objects.get(pk=second.pk), reason="Ill")
    dispatch_batch()
    assert store.find_lesson(str(second.pk)) is None


def test_unchanged_lessons_are_not_pushed_again(org, people, google):
    lesson = make_lesson(org, people)
    dispatch_batch()
    etag = fake_for(google).find_lesson(str(lesson.pk))[2]["etag"]
    with tenant_context(org):
        assert services.sync_lesson(lesson.pk) == {"pushed": 0, "removed": 0, "failed": 0}
    assert fake_for(google).find_lesson(str(lesson.pk))[2]["etag"] == etag


def test_series_lessons_are_pushed(org, people, google):
    start = slot(days=2)
    with tenant_context(org), transaction.atomic():
        scheduling.create_series(
            service=people["service"],
            branch=people["student"].branch,
            rrule="FREQ=WEEKLY",
            count=3,
            start_date=start.date(),
            start_time=start.timetz().replace(tzinfo=None),
            timezone="Europe/London",
            duration_minutes=60,
            attendees=[{"student": people["student"]}],
            tutors=[{"tutor": people["tutor"]}],
        )
    dispatch_batch()  # lesson_series.created
    calendar_id = write_calendar(org, google)
    assert len(fake_for(google).events(calendar_id)) == 3


def test_deleting_a_lesson_removes_its_event(
    org, people, google, django_capture_on_commit_callbacks
):
    lesson = make_lesson(org, people)
    dispatch_batch()
    with (
        tenant_context(org),
        django_capture_on_commit_callbacks(execute=True),
        transaction.atomic(),
    ):
        scheduling.delete_lesson(Lesson.objects.get(pk=lesson.pk))
    assert fake_for(google).find_lesson(str(lesson.pk)) is None


def test_a_failed_push_marks_the_connection(org, people, google):
    from tutortrack.integrations.providers import fake

    lesson = make_lesson(org, people)
    fake.fail("google", times=1)
    with tenant_context(org):
        assert services.sync_lesson(lesson.pk)["failed"] == 1
        google.refresh_from_db()
        assert google.status == "error"
        assert services.sync_lesson(lesson.pk)["pushed"] == 1


# --- FR-22-1 busy blocks -------------------------------------------------------------------------


def test_personal_events_become_busy_blocks_that_block_booking(org, people, google):
    """AC: a personal event in a connected calendar is a busy block and blocks booking."""
    start = slot(days=5, hour=17)
    event_id = fake_for(google).add_event(start, start + timedelta(hours=1), title="Dentist")
    assert sync(org, google)["changed"] == 1
    with tenant_context(org):
        block = ExternalBusyBlock.objects.get(external_id=event_id)
        assert block.user == people["user"]
        assert block.start == start
        assert not hasattr(block, "title")  # times only
        found = conflicts.check(
            start=start + timedelta(minutes=30), end=start + timedelta(minutes=90),
            tz="Europe/London", tutors=[people["tutor"]],
        )  # fmt: skip
        assert [c.kind for c in conflicts.hard(found)] == ["tutor_external_busy"]
        with pytest.raises(ConflictError):
            make_lesson(org, people, start=start)
        busy = availability.busy_intervals(
            people["tutor"].pk, start - timedelta(hours=1), start + timedelta(hours=2)
        )
        assert (start, start + timedelta(hours=1)) in busy
    assert OutboxEvent.objects.filter(event_type="calendar.busy_updated").exists()


def test_busy_blocks_feed_free_slots_and_batched_fit(org, people, google):
    start = slot(days=6, hour=10)
    with tenant_context(org):
        template = AvailabilityTemplate.objects.create(
            tutor=people["tutor"], effective_from=start.date() - timedelta(days=7),
            timezone="Europe/London",
        )  # fmt: skip
        AvailabilityWindow.objects.create(
            template=template, weekday=start.weekday(), start_time=time(9), end_time=time(12)
        )
    fake_for(google).add_event(start, start + timedelta(hours=1))
    sync(org, google)
    with tenant_context(org):
        slots = availability.free_slots(
            people["tutor"].pk, start=start.date(), end=start.date(), duration_minutes=60,
            buffer_minutes=0, min_notice_hours=0,
        )  # fmt: skip
        starts = {s.start.astimezone(LONDON).time() for s in slots}
        assert time(9) in starts
        assert time(10) not in starts
        assert time(11) in starts
        fit = availability.interval_fit(
            [people["tutor"].pk], [[(start, start + timedelta(hours=1))]]
        )
        assert fit[str(people["tutor"].pk)] == [0.0]


def test_incremental_sync_handles_moves_deletes_and_free_events(org, people, google):
    store = fake_for(google)
    start = slot(days=5, hour=9)
    event_id = store.add_event(start, start + timedelta(hours=1))
    store.add_event(start, start + timedelta(hours=1), busy=False)  # "free": not busy
    sync(org, google)
    with tenant_context(org):
        assert ExternalBusyBlock.objects.count() == 1
    store.move_event(event_id, start + timedelta(hours=3), start + timedelta(hours=4))
    sync(org, google)
    with tenant_context(org):
        assert ExternalBusyBlock.objects.get().start == start + timedelta(hours=3)
    store.delete_event(event_id)
    sync(org, google)
    with tenant_context(org):
        assert not ExternalBusyBlock.objects.exists()


def test_expired_sync_token_falls_back_to_a_full_sync(org, people, google):
    start = slot(days=2)
    store = fake_for(google)
    store.add_event(start, start + timedelta(hours=1))
    sync(org, google)
    with tenant_context(org):
        ExternalBusyBlock.objects.create(
            user=people["user"], connection=google, source="google", calendar_id="primary",
            external_id="stale", start=start, end=start + timedelta(hours=1),
        )  # fmt: skip
        SyncState.objects.filter(connection=google).update(sync_token="expired")
    sync(org, google)
    with tenant_context(org):
        assert list(ExternalBusyBlock.objects.values_list("external_id", flat=True)) != ["stale"]
        assert not ExternalBusyBlock.objects.filter(external_id="stale").exists()


def test_our_own_lesson_events_are_never_busy(org, people, google):
    lesson = make_lesson(org, people)
    dispatch_batch()
    calendar_id = write_calendar(org, google)
    with tenant_context(org):
        CalendarSyncSettings.objects.filter(connection=google).update(
            read_calendar_ids=["primary", calendar_id]
        )
        services.prepare(google.pk)
    sync(org, google)
    with tenant_context(org):
        assert not ExternalBusyBlock.objects.exists()
        assert conflicts.hard(
            conflicts.check(start=lesson.start, end=lesson.end, tz="Europe/London",
                            tutors=[people["tutor"]], exclude_lesson_ids=[lesson.pk])
        ) == []  # fmt: skip


def test_disconnected_calendars_stop_blocking(org, people, google):
    from tutortrack.integrations import services as integrations

    start = slot(days=5)
    fake_for(google).add_event(start, start + timedelta(hours=1))
    sync(org, google)
    with tenant_context(org):
        integrations.disconnect(google)
        assert conflicts.hard(
            conflicts.check(start=start, end=start + timedelta(hours=1), tz="Europe/London",
                            tutors=[people["tutor"]])
        ) == []  # fmt: skip
        services.clear(google)
        assert not ExternalBusyBlock.objects.exists()


# --- channels and webhooks ------------------------------------------------------------------------


def test_push_channels_are_created_and_renewed_before_expiry(org, people, google):
    with tenant_context(org):
        state = SyncState.objects.get(connection=google, calendar_id="primary")
        assert state.channel_id
        assert state.channel_expiry > now() + timedelta(days=6)
        old = state.channel_id
        state.channel_expiry = now() + timedelta(hours=2)
        state.save()
        plan = services.prepare(google.pk)
        state.refresh_from_db()
        assert state.channel_id != old
        assert plan["poll_seconds"] == 300
    channels = fake_for(google).channels()
    assert old not in channels
    assert state.channel_id in channels


def test_google_webhook_validates_the_token_and_signals(org, people, google, monkeypatch):
    signals: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "tutortrack.core.workflows.ops.signal_now", lambda wid, name, arg=None: signals.append(
            (wid, name)) or True,
    )  # fmt: skip
    with tenant_context(org):
        state = SyncState.objects.get(connection=google, calendar_id="primary")
    channel = fake_for(google).channels()[state.channel_id]
    client = client_for(org)
    headers = {"HTTP_X_GOOG_CHANNEL_ID": state.channel_id,
               "HTTP_X_GOOG_RESOURCE_STATE": "exists"}  # fmt: skip
    bad = client.post("/webhooks/google-calendar", HTTP_X_GOOG_CHANNEL_TOKEN="x.y.z", **headers)
    assert bad.status_code == 403
    assert signals == []
    ok = client.post(
        "/webhooks/google-calendar", HTTP_X_GOOG_CHANNEL_TOKEN=channel["token"], **headers
    )
    assert ok.status_code == 200
    assert signals == [(f"calendar:{org.pk}:{google.pk}", "changed")]


def test_graph_subscription_handshake_and_notifications(org, people, monkeypatch):
    signals: list[str] = []
    monkeypatch.setattr(
        "tutortrack.core.workflows.ops.signal_now",
        lambda wid, name, arg=None: signals.append(wid) or True,
    )
    conn = connect(org, people["user"], provider="microsoft")
    with tenant_context(org):
        plan = services.prepare(conn.pk)
        state = SyncState.objects.get(connection=conn, calendar_id="primary")
    assert plan["status"] == "active"
    assert state.channel_expiry < now() + timedelta(days=3)
    client = client_for(org)
    handshake = client.post("/webhooks/microsoft-graph?validationToken=abc%20123")
    assert handshake.status_code == 200
    assert handshake.content == b"abc 123"
    token = FakeCalendar(conn.external_account_id).channels()[state.channel_id]["token"]
    body = {"value": [{"subscriptionId": state.channel_id, "clientState": token}]}
    response = client.post("/webhooks/microsoft-graph", body, format="json")
    assert response.status_code == 202
    assert signals == [f"calendar:{org.pk}:{conn.pk}"]
    forged = {"value": [{"subscriptionId": state.channel_id, "clientState": "a.b.c"}]}
    assert client.post("/webhooks/microsoft-graph", forged, format="json").status_code == 403


def test_microsoft_calendar_pushes_and_reads_busy(org, people):
    """FR-22-2: same capabilities via Graph (delta queries)."""
    conn = connect(org, people["user"], provider="microsoft")
    with tenant_context(org):
        services.prepare(conn.pk)
    settle(org)
    lesson = make_lesson(org, people)
    dispatch_batch()
    store = FakeCalendar(conn.external_account_id)
    assert store.find_lesson(str(lesson.pk)) is not None
    start = slot(days=8)
    store.add_event(start, start + timedelta(hours=1))
    assert sync(org, conn)["changed"] == 1


def test_caldav_polls_every_ten_minutes_without_channels(org, people):
    """FR-22-3: iCloud via CalDAV with an app-specific password, polled."""
    conn = connect(org, people["user"], provider="caldav")
    with tenant_context(org):
        plan = services.prepare(conn.pk)
        state = SyncState.objects.get(connection=conn)
    assert plan["poll_seconds"] == 600
    assert state.channel_id == ""
    store = FakeCalendar(conn.external_account_id)
    start = slot(days=2)
    event_id = store.add_event(start, start + timedelta(hours=1))
    assert sync(org, conn)["changed"] == 1
    store.delete_event(event_id)
    sync(org, conn)
    with tenant_context(org):
        assert not ExternalBusyBlock.objects.exists()


# --- T03 two-way edits ---------------------------------------------------------------------------


@pytest.fixture
def two_way(org, people, google):
    with tenant_context(org):
        sync_settings = CalendarSyncSettings.objects.get(connection=google)
        services.update_sync_settings(sync_settings, two_way=True)
        services.prepare(google.pk)
    settle(org)
    return google


def test_moving_a_lesson_in_google_proposes_a_reschedule(org, people, two_way):
    with tenant_context(org):
        manager = MembershipFactory(organisation=org, role="coordinator").user
        job = jobs.create_job(
            client=people["client"], service=people["service"],
            students=[{"student": people["student"]}], account_manager=manager,
        )  # fmt: skip
    lesson = make_lesson(org, people, job=job)
    dispatch_batch()
    store = fake_for(two_way)
    calendar_id, event_id, _row = store.find_lesson(str(lesson.pk))
    moved = lesson.start + timedelta(days=1)
    store.move_event(event_id, moved, moved + timedelta(hours=1), calendar_id=calendar_id)
    sync(org, two_way)
    with tenant_context(org):
        lesson.refresh_from_db()
        assert lesson.start != moved  # a tutor can't reschedule: proposed instead
        task = Task.objects.get(target_type="scheduling.lesson", target_id=str(lesson.pk))
        assert task.assignee == manager
        assert "Reschedule" in task.title
        assert ExternalEventLink.objects.get(lesson=lesson).proposed_start == moved
        assert ExternalEventLink.objects.filter(lesson=lesson).exists()
    assert datetime.fromisoformat(store.find_lesson(str(lesson.pk))[2]["start"]) == lesson.start
    assert OutboxEvent.objects.filter(event_type="calendar.reschedule_proposed").exists()
    sync(org, two_way)
    with tenant_context(org):
        assert Task.objects.filter(target_id=str(lesson.pk)).count() == 1  # not proposed twice


def test_moves_apply_directly_when_the_owner_may_edit_lessons(org, people):
    from tutortrack.people.tests.factories import TutorProfileFactory

    with tenant_context(org):
        admin = MembershipFactory(organisation=org, role="admin")
        tutor = TutorProfileFactory(organisation=org, status="active", membership=admin)
    conn = connect(org, admin.user, who="boss")
    with tenant_context(org):
        services.update_sync_settings(CalendarSyncSettings.objects.get_or_create(
            connection=conn, defaults={"user": admin.user})[0], two_way=True)  # fmt: skip
        services.prepare(conn.pk)
    settle(org)
    lesson = make_lesson(org, {**people, "tutor": tutor})
    dispatch_batch()
    store = FakeCalendar(conn.external_account_id)
    calendar_id, event_id, _row = store.find_lesson(str(lesson.pk))
    moved = lesson.start + timedelta(hours=3)
    store.move_event(event_id, moved, moved + timedelta(hours=1), calendar_id=calendar_id)
    sync(org, conn)
    with tenant_context(org):
        lesson.refresh_from_db()
        assert lesson.start == moved
        assert not Task.objects.filter(target_id=str(lesson.pk)).exists()


def test_deleting_a_lesson_in_google_recreates_it_with_a_warning(
    org, people, two_way, django_capture_on_commit_callbacks
):
    lesson = make_lesson(org, people)
    dispatch_batch()
    store = fake_for(two_way)
    calendar_id, event_id, _row = store.find_lesson(str(lesson.pk))
    store.delete_event(event_id, calendar_id=calendar_id)
    with tenant_context(org):
        with django_capture_on_commit_callbacks(execute=True):
            services.sync_connection(two_way.pk)
        lesson.refresh_from_db()
        assert lesson.status == "planned"  # never cancelled from outside
        assert InAppNotification.objects.filter(user=people["user"]).exists()
    again = store.find_lesson(str(lesson.pk))
    assert again is not None
    assert again[1] != event_id


def test_two_way_needs_the_org_setting(org, people, google):
    from tutortrack.core.exceptions import BusinessRuleViolation
    from tutortrack.tenancy.settings_service import update_settings

    with tenant_context(org):
        with transaction.atomic():
            update_settings("integrations", {"integrations.calendar_two_way": False})
        with pytest.raises(BusinessRuleViolation):
            services.update_sync_settings(
                CalendarSyncSettings.objects.get(connection=google), two_way=True
            )


# --- settings API --------------------------------------------------------------------------------


def test_sync_settings_api(org, people, google, monkeypatch):
    monkeypatch.setattr("tutortrack.core.workflows.ops.signal_now", lambda *a, **k: True)
    api = client_for(org, people["user"])
    url = f"/api/v1/calendar-sync/connections/{google.pk}/settings"
    page = api.get(url).json()
    assert page["settings"]["read_calendar_ids"] == ["primary"]
    assert {c["name"] for c in page["calendars"]} == {"Personal", "TutorTrack"}
    response = api.patch(url, {"two_way": True, "title_format": "{service}"}, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["settings"]["two_way"] is True
    stranger = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    assert stranger.get(url).status_code == 404
    assert api.post(f"/api/v1/calendar-sync/connections/{google.pk}/sync").status_code == 202


def test_title_format_placeholders(org, people, google):
    with tenant_context(org):
        sync_settings = CalendarSyncSettings.objects.get(connection=google)
        sync_settings.title_format = "{service} with {student_initials} {unknown}"
        lesson = make_lesson(org, people)
        assert services.event_title(lesson, sync_settings) == ("Maths 1:1 with Arjun P. {unknown}")


class TestBusyBlockIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/calendar-sync/busy-blocks"

    def make_object(self, organisation):
        from tutortrack.identity.tests.factories import UserFactory
        from tutortrack.integrations.models import IntegrationConnection

        with tenant_context(organisation):
            user = UserFactory()
            conn = IntegrationConnection.objects.create(provider="google", user=user)
            start = now() + timedelta(days=1)
            return ExternalBusyBlock.objects.create(
                user=user, connection=conn, source="google", calendar_id="primary",
                external_id="e1", start=start, end=start + timedelta(hours=1),
            )  # fmt: skip
