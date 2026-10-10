"""E22-TW1: CalendarConnectionWorkflow and OnlineMeetingProvisioningWorkflow."""

from __future__ import annotations

import json
import os
import time as clock
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.calendar_sync.models import (
    CalendarSyncSettings,
    ExternalBusyBlock,
    OnlineMeeting,
    SyncState,
)
from tutortrack.calendar_sync.processes import (
    CalendarConnectionWorkflow,
    CalendarInput,
    OnlineMeetingProvisioningWorkflow,
    calendar_workflow_id,
    meeting_workflow_id,
)
from tutortrack.comms.models import InAppNotification
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent, WorkflowLink
from tutortrack.core.testing import client_for
from tutortrack.core.workflows import start_now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations import services as integrations
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import fake
from tutortrack.integrations.providers.fake import FakeCalendar
from tutortrack.scheduling import services as scheduling
from tutortrack.scheduling.models import Lesson

from .conftest import connect, make_lesson, settle, slot

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def wait_for(org, check: Callable[[], bool], seconds: float = 20) -> None:
    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        with tenant_context(org):
            if check():
                return
        clock.sleep(0.1)
    raise AssertionError("timed out waiting for the workflow")


def record(temporal_env, workflow_id: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(workflow_id))


def blocks() -> int:
    return ExternalBusyBlock.objects.count()


def synced(conn) -> Callable[[], bool]:
    return lambda: IntegrationConnection.objects.get(pk=conn.pk).last_sync_at is not None


def disconnect(org, conn) -> None:
    with tenant_context(org), transaction.atomic():
        integrations.disconnect(IntegrationConnection.objects.get(pk=conn.pk))
    dispatch_batch()  # integration.disconnected → signal "disconnect"


# --- CalendarConnectionWorkflow ------------------------------------------------------------------


def test_connection_syncs_on_push_and_on_the_polling_timer(org, people, temporal_env):
    """AC: a personal event appears as a busy block after a push notification, and the
    polling fallback catches changes without one; disconnecting ends the workflow."""
    lesson = make_lesson(org, people, start=slot(days=2))
    conn = connect(org, people["user"])
    dispatch_batch()  # integration.connected → CalendarConnectionWorkflow
    wait_for(org, synced(conn))
    store = FakeCalendar(conn.external_account_id)
    assert store.find_lesson(str(lesson.pk)) is not None  # backfilled on the first run
    start = slot(days=4, hour=18)
    store.add_event(start, start + timedelta(hours=1))
    with tenant_context(org):
        state = SyncState.objects.get(connection=conn, calendar_id="primary")
    token = store.channels()[state.channel_id]["token"]
    response = client_for(org).post(
        "/webhooks/google-calendar",
        HTTP_X_GOOG_CHANNEL_ID=state.channel_id,
        HTTP_X_GOOG_CHANNEL_TOKEN=token,
        HTTP_X_GOOG_RESOURCE_STATE="exists",
    )
    assert response.status_code == 200
    wait_for(org, lambda: blocks() == 1)  # push: signal "changed"
    later = slot(days=5, hour=18)
    store.add_event(later, later + timedelta(hours=1))
    temporal_env.skip(timedelta(minutes=6))  # no push: the 5-minute poll picks it up
    wait_for(org, lambda: blocks() == 2)
    disconnect(org, conn)
    wid = calendar_workflow_id(org.pk, conn.pk)
    assert temporal_env.result(wid) == "disconnected"
    with tenant_context(org):
        assert blocks() == 0
        assert not SyncState.objects.filter(connection=conn).exists()
    record(temporal_env, wid, "CalendarConnectionWorkflow-disconnected")


def test_sync_errors_back_off_and_recover(org, people, temporal_env):
    conn = connect(org, people["user"])
    dispatch_batch()
    wait_for(org, synced(conn))
    fake.fail("google", times=3)  # one sync's three attempts fail
    with tenant_context(org):
        state = SyncState.objects.get(connection=conn, calendar_id="primary")
    store = FakeCalendar(conn.external_account_id)
    client_for(org).post(
        "/webhooks/google-calendar",
        HTTP_X_GOOG_CHANNEL_ID=state.channel_id,
        HTTP_X_GOOG_CHANNEL_TOKEN=store.channels()[state.channel_id]["token"],
        HTTP_X_GOOG_RESOURCE_STATE="exists",
    )
    wait_for(org, lambda: IntegrationConnection.objects.get(pk=conn.pk).status == "error", 40)
    temporal_env.skip(timedelta(minutes=3))  # the backoff timer
    wait_for(org, lambda: IntegrationConnection.objects.get(pk=conn.pk).status == "active", 40)
    disconnect(org, conn)
    wid = calendar_workflow_id(org.pk, conn.pk)
    assert temporal_env.result(wid) == "disconnected"
    record(temporal_env, wid, "CalendarConnectionWorkflow-recovered")


def test_long_running_connection_continues_as_new(org, people, temporal_local_env):
    """On a real dev server: the time-skipping test server leaks its time lock across
    continue-as-new, which would stall timers in later tests."""
    temporal_env = temporal_local_env
    conn = connect(org, people["user"])
    settle(org)  # started by hand below, with a short loop budget
    wid = calendar_workflow_id(org.pk, f"{conn.pk}-can")
    start_now(
        CalendarConnectionWorkflow,
        CalendarInput(organisation_id=str(org.pk), connection_id=str(conn.pk), max_loops=1),
        id=wid,
    )
    wait_for(org, synced(conn))
    with tenant_context(org):
        first = IntegrationConnection.objects.get(pk=conn.pk).last_sync_at
    # A change ends the only loop of this run → continue_as_new → the new run syncs again
    temporal_env.run(temporal_env.handle(wid).signal("changed"))
    wait_for(org, lambda: IntegrationConnection.objects.get(pk=conn.pk).last_sync_at != first)
    temporal_env.run(temporal_env.handle(wid).signal("disconnect"))
    # Not ``result()``: following a continued run there unbalances the test server's
    # time-skipping lock for later tests. The process timeline shows the end instead.
    wait_for(org, lambda: WorkflowLink.objects.get(workflow_id=wid).status == "completed")
    record(temporal_env, wid, "CalendarConnectionWorkflow-continued")


def test_settings_changes_signal_a_sync(org, people, temporal_env):
    conn = connect(org, people["user"])
    dispatch_batch()
    wait_for(org, synced(conn))
    with tenant_context(org):
        sync_settings = CalendarSyncSettings.objects.get(connection=conn)
    store = FakeCalendar(conn.external_account_id)
    work = store.add_event(slot(days=3), slot(days=3) + timedelta(hours=1), calendar_id="work")
    from tutortrack.calendar_sync import services

    with tenant_context(org), transaction.atomic():
        services.update_sync_settings(sync_settings, read_calendar_ids=["primary", "work"])
    dispatch_batch()  # calendar.settings_changed → signal "changed"
    wait_for(org, lambda: ExternalBusyBlock.objects.filter(external_id=work).exists())
    disconnect(org, conn)
    assert temporal_env.result(calendar_workflow_id(org.pk, conn.pk)) == "disconnected"


# --- OnlineMeetingProvisioningWorkflow ----------------------------------------------------------


def _scheduled_id(org, lesson) -> str:
    with tenant_context(org):
        event = OutboxEvent.objects.get(
            event_type="lesson.scheduled", payload__subject__id=str(lesson.pk)
        )
    return meeting_workflow_id(org.pk, lesson.pk, event.pk)


def test_online_lessons_get_a_meeting_and_cancellation_removes_it(org, people, temporal_env):
    lesson = make_lesson(org, people, online=True)
    dispatch_batch()  # lesson.scheduled → OnlineMeetingProvisioningWorkflow
    wid = _scheduled_id(org, lesson)
    assert temporal_env.result(wid) == {str(lesson.pk): "created"}
    record(temporal_env, wid, "OnlineMeetingProvisioningWorkflow-created")
    dispatch_batch()  # our own lesson.updated(meeting_url) starts nothing
    with tenant_context(org):
        lesson.refresh_from_db()
        assert lesson.meeting_url
        assert lesson.meeting_provider == "builtin"
        assert WorkflowLink.objects.filter(process="online-meeting").count() == 1
        with transaction.atomic():
            scheduling.cancel_lesson(Lesson.objects.get(pk=lesson.pk))
        event = OutboxEvent.objects.get(event_type="lesson.cancelled")
    dispatch_batch()
    wid = meeting_workflow_id(org.pk, lesson.pk, event.pk)
    assert temporal_env.result(wid) == {str(lesson.pk): "deleted"}
    with tenant_context(org):
        assert OnlineMeeting.objects.get(lesson=lesson).status == "deleted"


def test_provisioning_retries_transient_failures(org, people, temporal_env):
    fake.fail("builtin", times=2)
    lesson = make_lesson(org, people, online=True)
    dispatch_batch()
    wid = _scheduled_id(org, lesson)
    assert temporal_env.result(wid) == {str(lesson.pk): "created"}
    record(temporal_env, wid, "OnlineMeetingProvisioningWorkflow-retried")


def test_provisioning_that_keeps_failing_tells_staff(org, people, temporal_env):
    with tenant_context(org):
        coordinator = MembershipFactory(organisation=org, role="coordinator").user
    fake.fail("builtin", times=50)
    lesson = make_lesson(org, people, online=True)
    dispatch_batch()
    wid = _scheduled_id(org, lesson)
    assert temporal_env.result(wid) == {str(lesson.pk): "failed"}
    with tenant_context(org):
        found = OnlineMeeting.objects.get(lesson=lesson)
        assert found.status == "failed"
        assert "unavailable" in found.last_error
        assert InAppNotification.objects.filter(user=coordinator).exists()
    record(temporal_env, wid, "OnlineMeetingProvisioningWorkflow-failed")


@pytest.mark.django_db(transaction=False)
@pytest.mark.parametrize(
    "prefix", ["CalendarConnectionWorkflow", "OnlineMeetingProvisioningWorkflow"]
)
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[CalendarConnectionWorkflow, OnlineMeetingProvisioningWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
