"""E34-T01: pathway templates and runs (services), and who may do each step."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.models import OutboxEvent, StoredFile
from tutortrack.core.time import now
from tutortrack.crm.models import Signature
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.jobs.models import Job
from tutortrack.pathways import services
from tutortrack.pathways.models import PathwayRun, PathwayStep, PathwayTemplateVersion

from .factories import (
    TWO_STAGES,
    acknowledge,
    make_job,
    make_template,
    make_tutor,
    questions,
    review,
    sign,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_temporal(monkeypatch):
    """These tests don't run Temporal: starting and signalling the clock is a no-op."""
    monkeypatch.setattr(services, "start", lambda *a, **k: None)
    monkeypatch.setattr(services, "signal", lambda *a, **k: None)


def _events(org, event_type):
    with tenant_context(org):
        return list(OutboxEvent.objects.filter(event_type=event_type).order_by("occurred_at"))


def _start(org, template, tutor=None, job=None):
    job = job or make_job(org)
    tutor = tutor or make_tutor(org)
    with tenant_context(org):
        return services.start_run(template, record_id=job.pk, tutor=tutor)


def _step(run, key):
    return PathwayStep.objects.get(run=run, key=key)


# --- templates ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stages", "message"),
    [
        ([], "at least one stage"),
        ([{"key": "a", "name": "A", "steps": [{"key": "x", "type": "teleport"}]}], "Unknown kind"),
        ([{"key": "a", "name": "A", "steps": [sign("x"), acknowledge("x")]}], "Step keys"),
        ([{"key": "a", "name": "A", "steps": [sign(assignee="staff")]}], "can't be done by"),
        ([{"key": "a", "name": "A", "steps": [sign(role="coordinator")]}], "Only staff steps"),
        ([{"key": "a", "name": "A", "steps": [review(role="tutor")]}], "Only staff steps"),
        ([{"key": "a", "name": "A", "steps": [sign(due_days=0)]}], "Due dates"),
        (
            [{"key": "a", "name": "A", "steps": [
                {"key": "c", "type": "system_check", "config": {"question": "tutor.active"}}]}],
            "different kind of record",
        ),
        (
            [{"key": "a", "name": "A", "steps": [
                {"key": "q", "type": "questions", "config": {"fields": [
                    {"key": "pick", "label": "Pick", "type": "select"}]}}]}],
            "options",
        ),
        ([{"key": "a", "name": "A", "steps": [
            {"key": "r", "type": "acknowledge", "config": {"title": "Read"}}]}], "text to read"),
    ],
)  # fmt: skip
def test_templates_are_checked_when_saved(org, stages, message):
    with pytest.raises(BusinessRuleViolation, match=message):
        make_template(org, stages)


def test_changing_the_stages_adds_a_version_and_runs_keep_theirs(org):
    template = make_template(org)
    run = _start(org, template)
    with tenant_context(org):
        same = services.save_template(
            template, name="Renamed", subject_type="job", stages=TWO_STAGES, kind="join"
        )
        assert same.current_version.version == 1
        changed = services.save_template(
            template, name="Renamed", subject_type="job", kind="join",
            stages=[{"key": "only", "name": "Only", "steps": [sign()]}],
        )  # fmt: skip
        assert changed.current_version.version == 2
        assert PathwayTemplateVersion.objects.filter(template=template).count() == 2
        run.refresh_from_db()
        assert run.version.version == 1
        assert run.steps.count() == 3


def test_switched_off_templates_dont_start(org):
    template = make_template(org, active=False)
    with pytest.raises(BusinessRuleViolation, match="switched off"):
        _start(org, template)


# --- runs ---------------------------------------------------------------------------------------


def test_starting_opens_the_first_stage_and_tells_the_tutor(
    org, django_capture_on_commit_callbacks
):
    template = make_template(org, [
        {"key": "paperwork", "name": "Paperwork", "steps": [sign(due_days=3), acknowledge()]},
        {"key": "ready", "name": "Ready", "steps": [review()]},
    ])  # fmt: skip
    tutor = make_tutor(org)
    with django_capture_on_commit_callbacks(execute=True):
        run = _start(org, template, tutor=tutor)
    with tenant_context(org):
        statuses = dict(run.steps.values_list("key", "status"))
        assert statuses == {"agreement": "open", "safeguarding": "open", "check": "waiting"}
        agreement = _step(run, "agreement")
        assert agreement.due_at - agreement.opened_at == timedelta(days=3)
        assert run.stage == "paperwork"
        message = Message.objects.get(type_key="pathway_tasks_opened", channel="email")
        assert "Sign the job agreement, Read the safeguarding policy" in message.body
    [started] = _events(org, "pathway.started")
    assert started.payload["data"]["kind"] == "join"


def test_tutor_steps_then_staff_review_complete_the_run_through_its_gate(org, s3):
    template = make_template(org)
    tutor = make_tutor(org)
    run = _start(org, template, tutor=tutor)
    staff = MembershipFactory(organisation=org, role="coordinator").user
    with tenant_context(org):
        user = tutor.membership.user
        signed = services.complete_step(
            _step(run, "agreement"), user=user, payload={"full_name": "Sam Tutor"}
        )
        assert signed.status == "done"
        assert Signature.objects.get(pk=signed.result["signature_id"]).agreement_key.startswith(
            "pathway:"
        )
        assert _step(run, "check").status == "waiting"  # the next stage waits for this one
        services.complete_step(_step(run, "safeguarding"), user=user)
        assert _step(run, "check").status == "open"
        services.complete_step(_step(run, "check"), user=staff, payload={"note": "All good"})
        run.refresh_from_db()
        assert run.status == "completed"
        assert run.gates == ["ready"]
    stages = _events(org, "pathway.stage_completed")
    assert [(e.payload["data"]["stage"], e.payload["data"]["gate"]) for e in stages] == [
        ("paperwork", ""),
        ("ready", "ready"),
    ]
    assert len(_events(org, "pathway.step_completed")) == 3
    [finished] = _events(org, "pathway.completed")
    assert finished.payload["data"]["outcome"] == "completed"


def test_only_the_person_a_step_names_can_finish_it(org):
    template = make_template(org)
    tutor = make_tutor(org)
    run = _start(org, template, tutor=tutor)
    other_tutor = make_tutor(org)
    admin = MembershipFactory(organisation=org, role="admin").user
    with tenant_context(org):
        for user in (other_tutor.membership.user, admin):
            with pytest.raises(PermissionDenied):
                services.complete_step(_step(run, "safeguarding"), user=user)
        services.skip_step(_step(run, "agreement"), user=admin, reason="Signed on paper")
        services.complete_step(_step(run, "safeguarding"), user=tutor.membership.user)
        with pytest.raises(PermissionDenied):  # a staff step is not the tutor's
            services.complete_step(_step(run, "check"), user=tutor.membership.user)


def test_a_staff_step_can_name_a_role(org):
    template = make_template(org, [{"key": "a", "name": "A", "steps": [review(role="finance")]}])
    run = _start(org, template)
    coordinator = MembershipFactory(organisation=org, role="coordinator").user
    owner = MembershipFactory(organisation=org, role="owner").user
    with tenant_context(org):
        with pytest.raises(PermissionDenied):
            services.complete_step(_step(run, "check"), user=coordinator)
        services.complete_step(_step(run, "check"), user=owner)
        run.refresh_from_db()
        assert run.status == "completed"


def test_a_staff_review_that_says_no_turns_the_run_down(org):
    run = _start(org, make_template(org, [{"key": "a", "name": "A", "steps": [review()]}]))
    staff = MembershipFactory(organisation=org, role="coordinator").user
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation, match="Say why"):
            services.reject_step(_step(run, "check"), user=staff, reason=" ")
        services.reject_step(_step(run, "check"), user=staff, reason="Not enough experience")
        run.refresh_from_db()
        assert (run.status, run.reason) == ("rejected", "Not enough experience")
        assert _step(run, "check").status == "rejected"
        with pytest.raises(BusinessRuleViolation, match="finished"):
            services.skip_step(_step(run, "check"), user=staff, reason="x")
    [finished] = _events(org, "pathway.completed")
    assert finished.payload["data"]["outcome"] == "rejected"


def test_answers_staff_check_go_to_review_and_can_be_sent_back(
    org, django_capture_on_commit_callbacks
):
    template = make_template(org, [
        {"key": "a", "name": "A", "steps": [questions(config={"review": True})]},
    ])  # fmt: skip
    tutor = make_tutor(org)
    run = _start(org, template, tutor=tutor)
    staff = MembershipFactory(organisation=org, role="coordinator").user
    user = tutor.membership.user
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation) as missing:
            services.complete_step(_step(run, "about"), user=user, payload={"answers": {}})
        assert "experience" in missing.value.extra["errors"]
        with pytest.raises(BusinessRuleViolation):
            services.complete_step(
                _step(run, "about"), user=user,
                payload={"answers": {"experience": 4, "boards": ["OCR"]}},
            )  # fmt: skip
        sent = services.complete_step(
            _step(run, "about"), user=user,
            payload={"answers": {"experience": 4, "boards": ["AQA"]}},
        )  # fmt: skip
        assert sent.status == "review"
        assert sent.result["answers"]["boards"] == ["AQA"]
        with django_capture_on_commit_callbacks(execute=True):
            back = services.reject_step(sent, user=staff, reason="Which boards exactly?")
        assert (back.status, back.reason, back.result) == ("open", "Which boards exactly?", {})
        assert Message.objects.filter(type_key="pathway_task_returned").exists()
        again = services.complete_step(
            back, user=user, payload={"answers": {"experience": 4, "boards": ["Edexcel"]}}
        )
        with pytest.raises(PermissionDenied):  # the tutor can't accept their own answers
            services.complete_step(again, user=user)
        services.complete_step(again, user=staff)
        run.refresh_from_db()
        assert run.status == "completed"


def test_uploads_must_be_the_tutors_own_files_and_are_attached_to_the_step(org):
    template = make_template(org, [{"key": "a", "name": "A", "steps": [
        {"key": "dbs", "type": "upload", "name": "Your DBS certificate",
         "config": {"instructions": "A photo of both sides", "max_files": 2}},
    ]}])  # fmt: skip
    tutor = make_tutor(org)
    run = _start(org, template, tutor=tutor)
    user = tutor.membership.user
    with tenant_context(org):

        def stored(owner):
            return StoredFile.objects.create(
                filename="dbs.jpg", content_type="image/jpeg", size_bytes=10,
                storage_key=f"k/{owner.pk}", status=StoredFile.Status.UPLOADED,
                uploaded_by=owner,
            )  # fmt: skip

        someone_elses = stored(MembershipFactory(organisation=org).user)
        with pytest.raises(BusinessRuleViolation, match="weren't found"):
            services.complete_step(
                _step(run, "dbs"), user=user, payload={"files": [str(someone_elses.pk)]}
            )
        mine = stored(user)
        sent = services.complete_step(
            _step(run, "dbs"), user=user, payload={"files": [str(mine.pk)]}
        )
        assert sent.status == "review"  # uploads are checked by staff by default
        assert sent.result["files"] == [{"id": str(mine.pk), "filename": "dbs.jpg"}]
        mine.refresh_from_db()
        assert mine.owner_object_id == str(sent.pk)


def test_system_steps_finish_when_their_question_holds(org):
    template = make_template(org, [
        {"key": "a", "name": "A", "steps": [
            {"key": "live", "type": "system_check", "name": "The job is live",
             "config": {"question": "job.active"}}]},
    ])  # fmt: skip
    job = make_job(org)
    run = _start(org, template, job=job)
    with tenant_context(org):
        state = services.tick(str(run.pk))
        assert state["finished"] is False
        assert state["wake_at"] is not None  # checked again tomorrow
        assert _step(run, "live").status == "open"
        Job.objects.filter(pk=job.pk).update(status="active")
        assert services.tick(str(run.pk))["status"] == "completed"
        assert _step(run, "live").status == "done"


def test_tick_reminds_before_the_due_date_then_says_overdue(
    org, django_capture_on_commit_callbacks
):
    template = make_template(org, [
        {"key": "a", "name": "A", "steps": [sign(due_days=3), review(due_days=5)]},
    ])  # fmt: skip
    run = _start(org, template)
    MembershipFactory(organisation=org, role="coordinator")  # gets the staff alerts
    with tenant_context(org):
        due = _step(run, "agreement").due_at
        state = services.tick(str(run.pk), at=now())
        assert state["wake_at"] == (due - timedelta(days=1)).isoformat()
        with django_capture_on_commit_callbacks(execute=True):
            services.tick(str(run.pk), at=due - timedelta(hours=2))
        assert _step(run, "agreement").reminded_at is not None
        keys = set(Message.objects.values_list("dedupe_key", flat=True))
        assert any(":due_soon:" in k for k in keys)
        with django_capture_on_commit_callbacks(execute=True):
            state = services.tick(str(run.pk), at=due + timedelta(minutes=1))
        assert _step(run, "agreement").overdue_at is not None
        types = set(Message.objects.values_list("type_key", flat=True))
        assert {"pathway_task_reminder", "staff_pathway_attention"} <= types
        # Next: the staff review's reminder (due in 5 days, reminded a day before).
        review_due = _step(run, "check").due_at
        assert state["wake_at"] == (review_due - timedelta(days=1)).isoformat()


def test_cancelling_stops_the_run(org):
    run = _start(org, make_template(org))
    admin = MembershipFactory(organisation=org, role="admin").user
    with tenant_context(org):
        services.cancel_run(run, user=admin, reason="The family stopped")
        run.refresh_from_db()
        assert run.status == "cancelled"
        assert services.tick(str(run.pk))["finished"] is True
        with pytest.raises(BusinessRuleViolation, match="finished"):
            services.complete_step(_step(run, "safeguarding"), user=run.tutor.membership.user)
    assert len(_events(org, "pathway.cancelled")) == 1


def test_runs_take_the_branch_of_their_record(org):
    job = make_job(org)
    run = _start(org, make_template(org), job=job)
    with tenant_context(org):
        assert PathwayRun.objects.get(pk=run.pk).branch_id == job.branch_id
