"""E33-T08: Preview for a record (real dates, the path each split takes, what each step would
send), Coming up (a scheduled or date start's next dates and counts), the records a preview
can use, where each run is, and cancelling a run."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tutortrack.automations import selectors, services
from tutortrack.automations.models import AutomationRun
from tutortrack.core.context import tenant_context
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.delivery.tests.test_delivery import lesson_at, people  # noqa: F401  (fixture)
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import StudentFactory

from .test_automations import make

pytestmark = pytest.mark.django_db

TAG = {"type": "action", "action": "add_tag", "config": {"tag": "Chased"}}
TASK = {"type": "action", "action": "create_task", "config": {"title": "Call the family"}}
ACTIVE = {"predicate": "student.active"}
# A Tuesday morning in London.
NOW = datetime(2026, 11, 3, 10, 30, tzinfo=ZoneInfo("Europe/London"))


def student_in(org, **fields):
    with tenant_context(org):
        return StudentFactory(organisation=org, **{"status": "active", **fields})


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(selectors, "now", lambda: NOW)
    return NOW


def local(value: str, org) -> datetime:
    return datetime.fromisoformat(value).astimezone(ZoneInfo(org.timezone))


def test_a_preview_gives_real_dates_the_path_each_split_takes_and_what_it_sends(org, api, frozen):
    student = student_in(org, first_name="Amara", status="paused")
    rule = make(org, [
        {"type": "wait", "days": 2, "at": "09:00"},
        {"type": "branch", "if": ACTIVE, "then": [TAG], "else": [
            {"type": "wait", "days": 1}, TASK,
        ]},
        {**TAG, "only_if": ACTIVE},
    ], trigger_type="manual", trigger_config={"subject": "student"},
       stop_when=["student.status_changed"])  # fmt: skip
    body = api.post(f"/api/v1/workflows/{rule.pk}/preview", {"subject_id": str(student.pk)})
    assert body.status_code == 200, body.content
    body = body.json()
    assert body["record"]["label"].startswith("Amara")
    assert body["matched"] is True
    assert local(body["start"], org) == NOW
    assert body["stop_when"] == ["Student status changed"]
    steps = {s["key"]: s for s in body["steps"]}
    # Two days on, at 09:00 local time.
    assert local(steps["0"]["at"], org) == datetime(2026, 11, 5, 9, 0, tzinfo=NOW.tzinfo)
    # The student is paused, so the split takes the No path, which waits a day more.
    assert steps["1"]["answer"] == "no"
    assert steps["1"]["questions"] == ["The student is active"]
    assert "1.then.0" not in steps
    assert steps["1.else.0"]["path"] == "no"
    assert local(steps["1.else.1"]["at"], org) == datetime(2026, 11, 6, 9, 0, tzinfo=NOW.tzinfo)
    assert steps["1.else.1"]["description"].startswith("Create task “Call the family”")
    # After the split, the step's "only if" isn't met.
    assert steps["2"]["skipped"] is True
    assert steps["2"]["questions"] == ["The student is active"]
    assert steps["2"]["message"] is None
    # A step that sends one of TutorTrack's notifications names it.
    assert selectors._message("send_invoice_reminder")["type"] == "invoice_reminder"


def test_a_preview_can_use_the_editors_unsaved_steps_which_are_checked(org, api, frozen):
    student = student_in(org)
    rule = make(org, [TAG], trigger_type="manual", trigger_config={"subject": "student"})
    url = f"/api/v1/workflows/{rule.pk}/preview"
    draft = {"trigger_type": "manual", "trigger_config": {"subject": "student"},
             "steps": [{"type": "wait", "hours": 3}, TASK]}  # fmt: skip
    body = api.post(url, {"subject_id": str(student.pk), "draft": draft}).json()
    assert [s["type"] for s in body["steps"]] == ["wait", "action"]
    assert local(body["steps"][1]["at"], org) == NOW + timedelta(hours=3)
    bad = {**draft, "steps": [{"type": "wait", "days": 1, "at": "9am"}]}
    assert api.post(url, {"subject_id": str(student.pk), "draft": bad}).status_code == 422
    assert api.post(url, {"subject_id": "nope"}).status_code == 422


def test_a_preview_for_a_record_that_wouldnt_start_says_which_check_fails(org, api, frozen):
    student = student_in(org, status="paused")
    rule = make(org, [TAG], trigger_type="manual", trigger_config={"subject": "student"},
                conditions_=ACTIVE)  # fmt: skip
    body = api.post(f"/api/v1/workflows/{rule.pk}/preview", {"subject_id": str(student.pk)})
    assert body.json()["matched"] is False
    assert body.json()["failed_checks"] == ["The student is active"]
    assert body.json()["steps"] == []


def test_a_date_start_previews_from_the_records_own_date(org, api, frozen):
    student = student_in(org, date_of_birth=date(2015, 11, 20))
    rule = make(org, [TAG], trigger_type="date", trigger_config={
        "subject": "student", "field": "date_of_birth", "offset_days": [-7, -1],
        "anniversary": True, "time": "08:00",
    })  # fmt: skip
    body = api.post(f"/api/v1/workflows/{rule.pk}/preview", {"subject_id": str(student.pk)})
    body = body.json()
    # This year's birthday, 7 and 1 days before, at 08:00; the first is the one coming up.
    assert [local(s, org).date() for s in body["starts"]] == [date(2026, 11, 13),
                                                              date(2026, 11, 19)]  # fmt: skip
    assert local(body["start"], org) == datetime(2026, 11, 13, 8, 0, tzinfo=NOW.tzinfo)
    assert body["start_passed"] is False


def test_coming_up_lists_a_schedules_next_five_dates_with_how_many_it_would_pick(org, api, frozen):
    with tenant_context(org):
        StudentFactory.create_batch(3, organisation=org)
    rule = make(org, [TAG], trigger_type="schedule", trigger_config={
        "subject": "student", "frequency": "monthly", "day": 1, "time": "06:00",
    })  # fmt: skip
    body = api.get(f"/api/v1/workflows/{rule.pk}/upcoming").json()
    assert body["kind"] == "schedule"
    assert [(local(d["at"], org).date(), d["count"]) for d in body["dates"]] == [
        (date(2026, 12, 1), 3), (date(2027, 1, 1), 3), (date(2027, 2, 1), 3),
        (date(2027, 3, 1), 3), (date(2027, 4, 1), 3),
    ]  # fmt: skip
    assert local(body["dates"][0]["at"], org).hour == 6
    assert body["before_checks"] is False


def test_coming_up_for_a_date_start_lists_the_days_with_records(org, api, frozen):
    student_in(org, date_of_birth=date(2016, 11, 10))
    student_in(org, date_of_birth=date(2014, 11, 10))
    student_in(org, date_of_birth=date(2015, 12, 25))
    rule = make(org, [TAG], trigger_type="date", trigger_config={
        "subject": "student", "field": "date_of_birth", "offset_days": 0, "anniversary": True,
        "time": "08:00",
    }, conditions_=ACTIVE)  # fmt: skip
    body = api.get(f"/api/v1/workflows/{rule.pk}/upcoming").json()
    assert [(local(d["at"], org).date(), d["count"]) for d in body["dates"]] == [
        (date(2026, 11, 10), 2),
        (date(2026, 12, 25), 1),
    ]
    assert body["before_checks"] is True
    assert body["looked_ahead_days"] == selectors.SCAN_DAYS


def test_coming_up_for_a_near_start_groups_records_by_the_sweep_that_picks_them(
    org,
    people,  # noqa: F811
):
    first = lesson_at(org, people, now() + timedelta(hours=30))
    lesson_at(org, people, first.start)
    lesson_at(org, people, now() + timedelta(hours=50))
    with tenant_context(org):
        rule = services.create_automation(
            name="Reminders", trigger_type="date", steps=[TAG],
            trigger_config={"subject": "lesson", "field": "start", "minutes": [-1440]},
        )  # fmt: skip
        dates = selectors.upcoming(rule)["dates"]
    assert [d["count"] for d in dates] == [2, 1]
    # The sweep on the quarter hour after the lesson's moment, 24 hours before it.
    moment = first.start - timedelta(hours=24)
    assert moment <= dates[0]["at"] < moment + timedelta(minutes=15)
    assert dates[0]["at"].minute % 15 == 0


def test_event_starts_have_nothing_coming_up(org, api):
    rule = make(org)
    assert api.get(f"/api/v1/workflows/{rule.pk}/upcoming").json()["dates"] == []


def test_the_record_picker_searches_records_of_the_workflows_kind(org, api):
    amara = student_in(org, first_name="Amara", last_name="Okafor")
    student_in(org, first_name="Ben", last_name="Hart")
    rule = make(org, [TAG], trigger_type="manual", trigger_config={"subject": "student"})
    url = f"/api/v1/workflows/{rule.pk}/records"
    assert len(api.get(url).json()) == 2
    assert api.get(url, {"q": "okaf"}).json() == [{"id": str(amara.pk), "label": "Amara Okafor"}]


# --- runs ---------------------------------------------------------------------------------------


def run_for(org, rule, student) -> AutomationRun:
    with tenant_context(org):
        return services.prepare_run(rule, subject_id=str(student.pk), run_key="manual:1",
                                    manual=True)  # fmt: skip


def test_the_runs_list_says_where_each_run_is_and_whose_record(org, api):
    student = student_in(org, first_name="Amara", last_name="Okafor")
    rule = make(org, [TAG, {"type": "wait", "days": 3}, TASK], trigger_type="manual",
                trigger_config={"subject": "student"})  # fmt: skip
    run = run_for(org, rule, student)
    with tenant_context(org):
        services.execute_step(str(run.pk), "0", TAG)
        until = services.start_wait(str(run.pk), "1", {"type": "wait", "days": 3},
                                    now().isoformat())  # fmt: skip
    [row] = api.get("/api/v1/workflow-runs", {"automation": str(rule.pk)}).json()["results"]
    assert row["status"] == "waiting"
    assert row["record_label"] == "Amara Okafor"
    assert datetime.fromisoformat(row["waiting_until"]) == datetime.fromisoformat(until)
    assert (row["waiting_step"], row["steps_done"]) == ("1", 1)
    under_way = api.get("/api/v1/workflow-runs", {"status": "under_way"}).json()["results"]
    assert [r["id"] for r in under_way] == [str(run.pk)]
    detail = api.get(f"/api/v1/workflow-runs/{run.pk}").json()
    assert [s["step_key"] for s in detail["steps"]] == ["0", "1"]
    on_page = api.get(f"/api/v1/workflows/{rule.pk}/runs").json()
    assert on_page[0]["waiting_until"] == row["waiting_until"]


def test_cancelling_a_run_whose_workflow_is_gone_closes_it(
    org, api, monkeypatch, django_capture_on_commit_callbacks
):
    monkeypatch.setattr("tutortrack.core.workflows.signal_now", lambda *a, **k: False)
    student = student_in(org)
    rule = make(org, [{"type": "wait", "days": 3}, TASK], trigger_type="manual",
                trigger_config={"subject": "student"})  # fmt: skip
    run = run_for(org, rule, student)
    with django_capture_on_commit_callbacks(execute=True):
        response = api.post(f"/api/v1/workflow-runs/{run.pk}/cancel")
    assert response.status_code == 200, response.content
    with tenant_context(org):
        run.refresh_from_db()
    assert (run.status, run.stop_reason) == ("stopped", services.CANCELLED)
    assert api.post(f"/api/v1/workflow-runs/{run.pk}/cancel").status_code == 422


def test_cancelling_needs_the_permission_that_changes_the_workflow(org):
    student = student_in(org)
    rule = make(org, [TASK], trigger_type="manual", trigger_config={"subject": "student"})
    run = run_for(org, rule, student)
    viewer = client_for(org, MembershipFactory(organisation=org, role="finance").user)
    assert viewer.get("/api/v1/workflow-runs").status_code == 200
    assert viewer.post(f"/api/v1/workflow-runs/{run.pk}/cancel").status_code == 403


@pytest.mark.django_db(transaction=True)
def test_a_cancelled_run_ends_before_its_next_step(org, temporal_env):
    from .test_sequences import wait_for

    student = student_in(org)
    rule = make(org, [{"type": "wait", "days": 3}, TASK], trigger_type="manual",
                trigger_config={"subject": "student"})  # fmt: skip
    with tenant_context(org):
        [run] = services.run_manually(rule, [str(student.pk)])
    wait_for(org, run, "waiting")
    with tenant_context(org):
        services.cancel(run)
    assert temporal_env.result(run.workflow_id) == "stopped"
    with tenant_context(org):
        run.refresh_from_db()
        assert (run.status, run.stop_reason) == ("stopped", services.CANCELLED)
        assert run.steps.get(step_key="0").status == "skipped"
        assert not run.steps.filter(step_key="1").exists()
