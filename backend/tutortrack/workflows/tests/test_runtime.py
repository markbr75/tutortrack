"""E32 plumbing: ids, timers/business calendar, codec, processes API, schedules, bridge."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from rest_framework.test import APIClient

from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, ScheduleLink, WorkflowLink
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.workflows import ids, runtime, signal_now, start_now, workflow_id
from tutortrack.core.workflows.codec import EncryptionCodec, encrypted
from tutortrack.core.workflows.timers import BusinessCalendar, delay_until_local, to_utc
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.workflows.demo import DemoReminderInput, DemoReminderWorkflow

# --- ids and timers (pure) ------------------------------------------------------------------------


def test_workflow_ids_are_tenant_prefixed():
    wid = workflow_id("invoice-dunning", "org-1", "inv-9")
    assert wid == "invoice-dunning:org-1:inv-9"
    assert ids.parse(wid) == ("invoice-dunning", "org-1", ["inv-9"])
    with pytest.raises(ValueError, match="must not contain"):
        workflow_id("bad:process", "org")


def test_local_deadlines_follow_dst():
    # 09:00 London is 08:00 UTC in summer and 09:00 UTC in winter.
    assert to_utc(datetime(2026, 7, 1, 9), "Europe/London") == datetime(2026, 7, 1, 8, tzinfo=UTC)
    assert to_utc(datetime(2026, 12, 1, 9), "Europe/London") == datetime(2026, 12, 1, 9, tzinfo=UTC)


def test_quiet_hours_closed_days_and_holidays_push_reminders_forward():
    calendar = BusinessCalendar(
        timezone="Europe/London",
        quiet_start="21:00",
        quiet_end="08:00",
        closed_weekdays=(6,),  # Sunday
        holidays=("2026-12-25",),
    )
    # 22:30 on a Monday -> 08:00 Tuesday.
    assert calendar.next_allowed(datetime(2026, 10, 5, 22, 30)) == datetime(2026, 10, 6, 8)
    # 06:00 -> 08:00 the same day.
    assert calendar.next_allowed(datetime(2026, 10, 6, 6)) == datetime(2026, 10, 6, 8)
    # Sunday -> Monday 08:00; Christmas Day (a Friday) -> Saturday 08:00.
    assert calendar.next_allowed(datetime(2026, 10, 11, 12)) == datetime(2026, 10, 12, 8)
    assert calendar.next_allowed(datetime(2026, 12, 25, 10)) == datetime(2026, 12, 26, 8)
    # Allowed times are unchanged.
    assert calendar.next_allowed(datetime(2026, 10, 6, 14)) == datetime(2026, 10, 6, 14)


def test_delay_is_never_negative():
    calendar = BusinessCalendar(timezone="UTC")
    now = datetime(2026, 10, 6, 12, tzinfo=UTC)
    assert delay_until_local(now, datetime(2026, 10, 6, 11), calendar) == timedelta(0)
    assert delay_until_local(now, datetime(2026, 10, 7, 12), calendar) == timedelta(days=1)


# --- codec ----------------------------------------------------------------------------------------


def test_codec_round_trip_and_key_rotation(settings):
    from temporalio.api.common.v1 import Payload

    original = [Payload(metadata={"encoding": b"json/plain"}, data=b'{"name":"Sam"}')]
    codec = EncryptionCodec()
    sealed = runtime.run(codec.encode(original))
    assert encrypted(sealed)
    assert b"Sam" not in sealed[0].data
    settings.TEMPORAL_PAYLOAD_KEYS = [
        "dev2:" + base64.b64encode(b"k" * 32).decode(),
        *settings.TEMPORAL_PAYLOAD_KEYS,
    ]
    assert runtime.run(codec.decode(sealed)) == original  # old key still decrypts
    assert runtime.run(codec.encode(original))[0].metadata["encryption-key-id"] == b"dev2"


@pytest.mark.django_db
def test_codec_endpoint_is_platform_staff_only(settings):
    from temporalio.api.common.v1 import Payload

    sealed = runtime.run(EncryptionCodec().encode([Payload(data=b"secret")]))
    body = json.dumps(
        {
            "payloads": [
                {
                    "metadata": {k: base64.b64encode(v).decode() for k, v in p.metadata.items()},
                    "data": base64.b64encode(p.data).decode(),
                }
                for p in sealed
            ]
        }
    )
    staff = APIClient(HTTP_ORIGIN="http://localhost:8233")
    staff.force_login(UserFactory(is_platform_staff=True))
    response = staff.post("/temporal-codec/decode", body, content_type="application/json")
    assert response.status_code == 200
    assert base64.b64decode(response.json()["payloads"][0]["data"]) == b"secret"
    assert response["Access-Control-Allow-Origin"] == "http://localhost:8233"

    outsider = APIClient()
    outsider.force_login(UserFactory())
    assert (
        outsider.post("/temporal-codec/decode", body, content_type="application/json").status_code
        == 403
    )
    assert (
        APIClient()
        .post("/temporal-codec/decode", body, content_type="application/json")
        .status_code
        == 403
    )


# --- processes API --------------------------------------------------------------------------------


def make_link(org, **fields):
    with tenant_context(org):
        return WorkflowLink.objects.create(
            workflow_id=fields.pop("workflow_id", workflow_id("demo-reminder", org.pk, "x")),
            workflow_type="DemoReminderWorkflow",
            process="demo-reminder",
            subject_type="demo",
            subject_id=fields.pop("subject_id", "x"),
            started_at=datetime.now(UTC),
            input={"organisation_id": str(org.pk), "subject_id": "x", "days": 1},
            **fields,
        )


@pytest.mark.django_db
def test_processes_list_filters_by_subject(org):
    make_link(org)
    make_link(org, workflow_id="demo-reminder:other", subject_id="y")
    api = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    rows = api.get("/api/v1/processes", {"subject_type": "demo", "subject_id": "x"}).json()
    assert [r["subject_id"] for r in rows["results"]] == ["x"]
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    assert tutor.get("/api/v1/processes").status_code == 403


@pytest.mark.django_db
def test_processes_without_a_cancel_permission_cannot_be_cancelled(org):
    link = make_link(org)
    api = client_for(org, MembershipFactory(organisation=org, role="owner").user)
    response = api.post(f"/api/v1/processes/{link.workflow_id}/cancel")
    assert response.status_code == 422


@pytest.mark.django_db
def test_terminate_and_restart_are_platform_only(org):
    link = make_link(org, status="failed")
    owner = client_for(org, MembershipFactory(organisation=org, role="owner").user)
    body = {"reason": "stuck"}
    assert (
        owner.post(
            f"/api/v1/processes/{link.workflow_id}/terminate", body, format="json"
        ).status_code
        == 403
    )
    assert (
        owner.post(f"/api/v1/processes/{link.workflow_id}/restart", body, format="json").status_code
        == 403
    )


class TestProcessIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/processes"

    def make_object(self, organisation):
        return make_link(organisation)

    def detail_url(self, obj):
        return f"{self.list_url}/{obj.workflow_id}"


# --- with Temporal -------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_detail_shows_live_state_and_restart_after_termination(org, superuser, temporal_env):
    wid = workflow_id("demo-reminder", org.pk, "live")
    start_now(
        DemoReminderWorkflow,
        DemoReminderInput(organisation_id=str(org.pk), subject_id="live", days=5),
        id=wid,
        subject=("demo", "live"),
    )
    api = client_for(org, superuser)
    import time

    for _ in range(50):  # wait for the workflow to reach its timer
        detail = api.get(f"/api/v1/processes/{wid}").json()
        if detail["live"].get("step") == "waiting":
            break
        time.sleep(0.1)
    assert detail["status"] == "running"
    assert detail["live"] == {"step": "waiting"}

    terminated = api.post(f"/api/v1/processes/{wid}/terminate", {"reason": "test"}, format="json")
    assert terminated.json()["status"] == "terminated"
    with tenant_context(org):
        assert AuditEntry.objects.filter(
            action="terminate", object_id=str(terminated.json()["id"])
        ).exists()
    restarted = api.post(f"/api/v1/processes/{wid}/restart", {"reason": "retry"}, format="json")
    assert restarted.status_code == 200, restarted.json()
    assert restarted.json()["status"] == "running"
    temporal_env.result(wid)


@pytest.mark.django_db(transaction=True)
def test_signals_to_finished_or_unknown_workflows_are_ignored(org, temporal_env):
    assert signal_now("demo-reminder:nope:nope", "cancel") is False
    wid = workflow_id("demo-reminder", org.pk, "done")
    start_now(
        DemoReminderWorkflow,
        DemoReminderInput(organisation_id=str(org.pk), subject_id="d", days=1),
        id=wid,
    )
    temporal_env.result(wid)
    assert signal_now(wid, "cancel") is False


@pytest.mark.django_db(transaction=True)
def test_schedules_pause_with_the_organisation(org, temporal_local_env):
    from tutortrack.core.events.dispatcher import dispatch_batch
    from tutortrack.core.workflows import schedules
    from tutortrack.tenancy import lifecycle

    sid = schedules.ensure_schedule(
        process="demo-reminder",
        workflow=DemoReminderWorkflow,
        input=DemoReminderInput(organisation_id=str(org.pk), subject_id="monthly", days=0),
        cron=["0 9 1 * *"],
        timezone="Europe/London",
    )
    client = temporal_local_env.client

    def paused() -> bool:
        return temporal_local_env.run(
            client.get_schedule_handle(sid).describe()
        ).schedule.state.paused

    assert paused() is False
    # Updating is idempotent.
    schedules.ensure_schedule(
        process="demo-reminder",
        workflow=DemoReminderWorkflow,
        input=DemoReminderInput(organisation_id=str(org.pk), subject_id="monthly", days=1),
        cron=["0 9 2 * *"],
        timezone="Europe/London",
    )
    with tenant_context(org):
        assert ScheduleLink.objects.count() == 1

    lifecycle.suspend_organisation(org, reason="Unpaid")
    dispatch_batch()
    assert paused() is True
    lifecycle.reactivate_organisation(org)
    dispatch_batch()
    assert paused() is False

    assert schedules.delete_organisation_schedules(org.pk) == [sid]
    with tenant_context(org):
        assert not ScheduleLink.objects.exists()
