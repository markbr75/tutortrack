"""E34-T02: ready-made pathways, the new step types, and where pathways start by themselves."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command

from tutortrack.core.context import tenant_context
from tutortrack.core.events.base import EventEnvelope
from tutortrack.core.events.registry import subscribers_for
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.jobs import services as jobs
from tutortrack.jobs.models import JobTutor
from tutortrack.matching import services as matching
from tutortrack.matching import sharing
from tutortrack.matching.models import JobPosting, JobPostingApplication
from tutortrack.pathways import builtin_pathways, services
from tutortrack.pathways.models import PathwayRun, PathwayStep, PathwayTemplate
from tutortrack.recruitment import compliance
from tutortrack.recruitment.models import ComplianceRecord
from tutortrack.scheduling import services as scheduling
from tutortrack.tenancy.settings_service import get_setting, update_settings

from .factories import acknowledge, make_job, make_template, make_tutor, review, sign

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_temporal(monkeypatch):
    monkeypatch.setattr(services, "start", lambda *a, **k: None)
    monkeypatch.setattr(services, "signal", lambda *a, **k: None)


def deliver(org, *types):
    """Hand the pathway handlers the waiting events of ``types`` (other apps' handlers
    don't run), then mark the events dispatched."""
    with tenant_context(org):
        rows = list(
            OutboxEvent.objects.filter(event_type__in=types, dispatched_at__isnull=True).order_by(
                "occurred_at"
            )
        )
    for row in rows:
        envelope = EventEnvelope.from_payload(row.payload)
        for sub in subscribers_for(row.event_type):
            if sub.name.startswith("tutortrack.pathways.handlers"):
                with tenant_context(org):
                    sub.handler(envelope)
        with tenant_context(org):
            OutboxEvent.objects.filter(pk=row.pk).update(dispatched_at=now())


def _step(run, key):
    return PathwayStep.objects.get(run=run, key=key)


def _staff(org, role="coordinator"):
    with tenant_context(org):
        return MembershipFactory(organisation=org, role=role).user


def _use(org, template):
    with tenant_context(org):
        services.set_used_by_default(template, True)


def _complete(org, run, key, user, **payload):
    with tenant_context(org):
        return services.complete_step(_step(run, key), user=user, payload=payload)


# --- ready-made pathways ------------------------------------------------------------------------


def test_ready_made_pathways_are_installed_once_and_never_start_on_their_own(org):
    with tenant_context(org):
        assert services.install_builtins() == {"installed": 3, "upgraded": 0}
        assert services.install_builtins() == {"installed": 0, "upgraded": 0}
        found = {t.builtin_key: t for t in PathwayTemplate.objects.all()}
        assert set(found) == {"apply_for_job", "join_job", "finish_job"}
        assert {t.kind for t in found.values()} == {"apply", "join", "finish"}
        assert not any(t.edited for t in found.values())
        assert found["join_job"].name == "Join a job"
        assert found["join_job"].stages[0]["gate"] == "ready"
        assert get_setting("pathways.default_templates") == {}
        assert services.template_for("join") is None


def test_editing_marks_a_ready_made_pathway_edited_and_newer_defaults_reach_unedited_ones(org):
    with tenant_context(org):
        services.install_builtins()
        join = PathwayTemplate.objects.get(builtin_key="join_job")
        finish = PathwayTemplate.objects.get(builtin_key="finish_job")
        services.save_template(
            join, name=join.name, subject_type="job", kind="join",
            stages=[{**join.stages[0], "steps": join.stages[0]["steps"][:1]}],
        )  # fmt: skip
        join.refresh_from_db()
        assert join.edited
        assert join.current_version.version == 2
    original = builtin_pathways.builtin("finish_job")
    newer = builtin_pathways.BuiltinPathway(
        "finish_job", "finish", original.name, original.description, 2,
        lambda: {"record_type": "job", "stages": [
            {"key": "wrap_up", "name": "Wrapping up", "steps": [acknowledge()]}
        ]},
    )  # fmt: skip
    join_default = builtin_pathways.builtin("join_job")
    builtin_pathways.register(newer)
    builtin_pathways.register(
        builtin_pathways.BuiltinPathway(
            "join_job",
            "join",
            join_default.name,
            join_default.description,
            2,
            join_default.default,
        )
    )
    try:
        with tenant_context(org):
            assert services.install_builtins() == {"installed": 0, "upgraded": 1}
            finish.refresh_from_db()
            assert [s["key"] for s in finish.stages[0]["steps"]] == ["safeguarding"]
            assert finish.builtin_version == 2
            assert not finish.edited
            join.refresh_from_db()
            assert services.update_available(join)
            services.reset_to_default(join)
            join.refresh_from_db()
            assert not join.edited
            assert not services.update_available(join)
            assert len(join.stages[0]["steps"]) == 3
            assert join.current_version.version == 3
    finally:
        builtin_pathways.register(original)
        builtin_pathways.register(join_default)


def test_the_sync_command_installs_them_for_every_organisation(org, other_org):
    call_command("sync_builtin_pathways")
    for organisation in (org, other_org):
        with tenant_context(organisation):
            assert PathwayTemplate.objects.exclude(builtin_key="").count() == 3


def test_custom_pathways_have_no_default_to_reset_and_dont_start_on_their_own(org):
    template = make_template(org, kind="custom")
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation, match="Only ready-made"):
            services.reset_to_default(template)
        with pytest.raises(BusinessRuleViolation, match="start on their own"):
            services.set_used_by_default(template, True)


def test_a_job_or_posting_can_name_its_own_pathway_over_the_default(org):
    default = make_template(org, name="Default join")
    special = make_template(org, name="Special join")
    apply = make_template(org, name="Apply", kind="apply", stages=[
        {"key": "a", "name": "A", "steps": [review()]}
    ])  # fmt: skip
    job = make_job(org)
    with tenant_context(org):
        assert services.template_for("join", job=job) is None
        services.set_used_by_default(default, True)
        assert services.template_for("join", job=job) == default
        jobs.update_job(job, join_template=special)
        assert services.template_for("join", job=job) == special
        with pytest.raises(BusinessRuleViolation, match="Join pathway"):
            jobs.update_job(job, join_template=apply)
        posting = JobPosting.objects.create(job=job, title="Maths", eligible=[])
        assert services.template_for("apply", posting=posting) is None
        posting.apply_template = apply
        assert services.template_for("apply", posting=posting) == apply
        services.save_template(default, name=default.name, subject_type="job", kind="join",
                               stages=default.stages, active=False)  # fmt: skip
        job.join_template = None
        assert services.template_for("join", job=job) is None  # switched off


# --- Join: joining, ready, and holding back lessons ---------------------------------------------


def _join_template(org):
    template = make_template(
        org,
        stages=[
            {"key": "paperwork", "name": "Paperwork", "gate": "ready", "steps": [sign()]},
            {"key": "later", "name": "In the first weeks", "steps": [acknowledge()]},
        ],
    )
    _use(org, template)
    return template


def _past_lesson(org, job, tutor):
    start = (now() - timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
    with tenant_context(org):
        student = job.students.first().student
        return scheduling.create_lesson(
            job=job, start=start, end=start + timedelta(hours=1),
            attendees=[{"student": student}], tutors=[{"tutor": tutor}],
            timezone="Europe/London", override_conflicts=True,
        ).lesson  # fmt: skip


def test_assigning_a_tutor_starts_join_and_lessons_wait_until_they_are_ready(org, s3):
    _join_template(org)
    job, tutor = make_job(org), make_tutor(org)
    with tenant_context(org):
        link = jobs.add_tutor(job, tutor=tutor)
    deliver(org, "job.tutor_assigned")
    deliver(org, "job.tutor_assigned")  # handled twice: still one run
    with tenant_context(org):
        run = PathwayRun.objects.get(subject_id=str(job.pk), tutor=tutor)
        assert PathwayRun.objects.filter(tutor=tutor).count() == 1
        link.refresh_from_db()
        assert link.join_status == "joining"
    lesson = _past_lesson(org, job, tutor)
    with tenant_context(org), pytest.raises(BusinessRuleViolation, match="finished joining"):
        delivery.complete_lesson(lesson)
    _complete(org, run, "agreement", tutor.membership.user, full_name="Ada Tutor")
    with tenant_context(org):
        link.refresh_from_db()
        run.refresh_from_db()
        assert link.join_status == "ready"
        assert run.gates == ["ready"]
        assert run.status == "running"  # the later stage is still open
        delivery.complete_lesson(lesson)
        lesson.refresh_from_db()
        assert lesson.status == "completed"


def test_lessons_arent_held_back_when_the_setting_is_off_or_join_is_cancelled(org):
    _join_template(org)
    job, tutor = make_job(org), make_tutor(org)
    with tenant_context(org):
        jobs.add_tutor(job, tutor=tutor)
    deliver(org, "job.tutor_assigned")
    lesson = _past_lesson(org, job, tutor)
    with tenant_context(org):
        update_settings("pathways", {"pathways.block_lessons_until_joined": False})
        delivery.complete_lesson(lesson)  # not held back
        update_settings("pathways", {"pathways.block_lessons_until_joined": True})
        run = PathwayRun.objects.get(tutor=tutor)
        services.cancel_run(run, user=None, reason="Not needed")
        assert JobTutor.objects.get(job=job, tutor=tutor).join_status is None


def test_offers_start_join_when_accepted(org):
    _join_template(org)
    job, tutor = make_job(org), make_tutor(org)
    with tenant_context(org):
        link = jobs.add_tutor(job, tutor=tutor, offer=True)
    deliver(org, "job.tutor_assigned")
    with tenant_context(org):
        assert not PathwayRun.objects.filter(tutor=tutor).exists()
        jobs.respond_to_offer(link, accept=True)
    deliver(org, "job.tutor_accepted")
    with tenant_context(org):
        assert PathwayRun.objects.filter(tutor=tutor, template__kind="join").count() == 1


def test_leaving_cancels_join_and_starts_finish(org):
    _join_template(org)
    finish = make_template(org, name="Finish", kind="finish", stages=[
        {"key": "wrap", "name": "Wrap up", "steps": [acknowledge("resources")]}
    ])  # fmt: skip
    _use(org, finish)
    job, tutor = make_job(org), make_tutor(org)
    with tenant_context(org):
        link = jobs.add_tutor(job, tutor=tutor)
    deliver(org, "job.tutor_assigned")
    with tenant_context(org):
        jobs.remove_tutor(link)
    deliver(org, "job.tutor_removed")
    with tenant_context(org):
        runs = {r.template.kind: r for r in PathwayRun.objects.filter(tutor=tutor)}
        assert runs["join"].status == "cancelled"
        assert runs["join"].reason == "The tutor left the job"
        assert runs["finish"].status == "running"


# --- Apply: the job board -----------------------------------------------------------------------


def _apply_setup(org):
    template = make_template(org, name="Apply", kind="apply", stages=[
        {"key": "decision", "name": "Decision", "steps": [review("choose")]}
    ])  # fmt: skip
    _use(org, template)
    job = make_job(org)
    tutors = [make_tutor(org), make_tutor(org)]
    with tenant_context(org):
        posting = JobPosting.objects.create(
            job=job, title="Maths", eligible=[str(t.pk) for t in tutors], published_at=now()
        )
        for tutor in tutors:
            matching.apply_to_posting(posting, tutor)
    deliver(org, "job_posting.application_received")
    with tenant_context(org):
        runs = [PathwayRun.objects.get(tutor=t, template__kind="apply") for t in tutors]
    return job, posting, tutors, runs


def test_applying_on_the_job_board_starts_apply_and_choosing_assigns_the_tutor(org):
    job, posting, (chosen, _other), (run, other_run) = _apply_setup(org)
    staff = _staff(org)
    _complete(org, run, "choose", staff)
    deliver(org, "job_posting.filled")
    with tenant_context(org):
        assert JobPostingApplication.objects.get(posting=posting, tutor=chosen).status == "selected"
        assert JobTutor.objects.get(job=job, status="active").tutor == chosen
        other_run.refresh_from_db()
        assert other_run.status == "cancelled"
        assert other_run.reason == "Another tutor was chosen"


def test_turning_an_applicant_down_rejects_their_application(org):
    _job, posting, (tutor, _other), (run, _other_run) = _apply_setup(org)
    with tenant_context(org):
        services.reject_step(_step(run, "choose"), user=_staff(org), reason="Not this time")
        assert JobPostingApplication.objects.get(posting=posting, tutor=tutor).status == "rejected"


# --- new step types -----------------------------------------------------------------------------


def _single(org, step, job=None, tutor=None, owner=None):
    template = make_template(org, kind="custom", stages=[
        {"key": "one", "name": "One", "steps": [step]}
    ])  # fmt: skip
    job = job or make_job(org)
    tutor = tutor or make_tutor(org)
    with tenant_context(org):
        return services.start_run(template, record_id=job.pk, tutor=tutor, owner=owner)


def test_show_a_check_sends_an_e18_record_that_staff_verify(org):
    run = _single(org, {"key": "id", "type": "show_check", "config": {"requirement": "photo_id"}})
    staff = _staff(org, "admin")
    with tenant_context(org):
        step = _step(run, "id")
        assert step.status == "open"
        services.complete_step(step, user=run.tutor.membership.user, payload={})
        step.refresh_from_db()
        record = ComplianceRecord.objects.get(tutor=run.tutor, requirement__key="photo_id")
        assert (step.status, record.status) == ("review", "submitted")
        services.reject_step(step, user=staff, reason="Blurry")
        record.refresh_from_db()
        step.refresh_from_db()
        assert (step.status, record.status) == ("open", "rejected")
        services.complete_step(step, user=run.tutor.membership.user, payload={})
        services.complete_step(_step(run, "id"), user=staff)
        record.refresh_from_db()
        assert record.status == "verified"
        assert _step(run, "id").status == "done"


def test_a_check_verified_elsewhere_ticks_the_step(org):
    tutor = make_tutor(org)
    run = _single(
        org, {"key": "id", "type": "show_check", "config": {"requirement": "photo_id"}},
        tutor=tutor,
    )  # fmt: skip
    with tenant_context(org):
        requirement = next(r for r in compliance.ensure_requirement_types() if r.key == "photo_id")
        record = compliance.submit(tutor, requirement)
        compliance.verify(record, user=_staff(org, "admin"))
    deliver(org, "compliance.record_verified")
    with tenant_context(org):
        assert _step(run, "id").status == "done"
        assert PathwayRun.objects.get(pk=run.pk).status == "completed"


def test_all_checks_in_date_is_ticked_by_tutortrack(org, monkeypatch):
    run = _single(org, {"key": "checks", "type": "show_check", "config": {"requirement": ""}})
    with tenant_context(org):
        step = _step(run, "checks")
        assert step.status == "open"
        with pytest.raises(BusinessRuleViolation, match="Checks page"):
            services.complete_step(step, user=run.tutor.membership.user, payload={})
        monkeypatch.setattr(compliance, "problems", lambda tutor, on=None: [])
        assert services.recheck(PathwayRun.objects.filter(pk=run.pk)) == 1
        assert _step(run, "checks").status == "done"


def test_trial_lesson_is_ticked_when_a_lesson_with_the_tutor_is_completed(org):
    job, tutor = make_job(org), make_tutor(org)
    with tenant_context(org):
        jobs.add_tutor(job, tutor=tutor)
    run = _single(org, {"key": "trial", "type": "trial_lesson"}, job=job, tutor=tutor)
    lesson = _past_lesson(org, job, tutor)
    with tenant_context(org):
        assert _step(run, "trial").status == "open"
        delivery.complete_lesson(lesson)
    deliver(org, "lesson.completed")
    with tenant_context(org):
        assert _step(run, "trial").status == "done"


def test_the_family_choosing_the_tutor_ticks_the_step_and_another_tutor_turns_it_down(org):
    job, tutor, rival = make_job(org), make_tutor(org), make_tutor(org)
    run = _single(org, {"key": "family", "type": "family_chooses"}, job=job, tutor=tutor)
    other = _single(org, {"key": "family", "type": "family_chooses"}, job=job, tutor=rival)
    with tenant_context(org):
        matching.shortlist_add(job, tutor)
        matching.shortlist_add(job, rival)
        _share, token = sharing.share(job, tutors=[tutor, rival])
        sharing.choose(token, tutor_id=str(tutor.pk))
    deliver(org, "shortlist.tutor_chosen")
    with tenant_context(org):
        assert PathwayRun.objects.get(pk=run.pk).status == "completed"
        lost = PathwayRun.objects.get(pk=other.pk)
        assert lost.status == "rejected"
        assert _step(other, "family").status == "rejected"


def test_booking_a_call_takes_a_free_slot_and_makes_the_meeting(org, monkeypatch):
    from tutortrack.calendar_sync import meetings
    from tutortrack.recruitment import interviews

    slot = (now() + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    monkeypatch.setattr(interviews, "interviewer_slots", lambda host, **kw: [slot])
    made = []

    class Info:
        join_url, host_url, external_id = "https://meet.example/abc", "https://meet.example/h", "x"

    def fake_meeting(**kwargs):
        made.append(kwargs)
        return "builtin", Info()

    monkeypatch.setattr(meetings, "create_standalone_meeting", fake_meeting)
    owner = _staff(org)
    run = _single(
        org, {"key": "call", "type": "book_call", "config": {"title": "Intro", "minutes": 20}},
        owner=owner,
    )  # fmt: skip
    tutor_user = run.tutor.membership.user
    tasks = client_for(org, tutor_user).get("/api/v1/me/tasks").json()
    assert tasks[0]["view"]["slots"] == [slot.isoformat()]
    with tenant_context(org), pytest.raises(BusinessRuleViolation, match="isn't free"):
        services.complete_step(
            _step(run, "call"), user=tutor_user, payload={"start": slot + timedelta(hours=1)}
        )
    with tenant_context(org):
        step_id = _step(run, "call").pk
    response = client_for(org, tutor_user).post(
        f"/api/v1/me/tasks/{step_id}/complete",
        {"start": slot.isoformat()},
        format="json",
    )
    assert response.status_code == 200, response.content
    with tenant_context(org):
        assert services.provision_call(_step(run, "call").pk) == "created"
        assert services.provision_call(_step(run, "call").pk) == "kept"
        result = _step(run, "call").result
    assert made[0]["host_user_id"] == owner.pk
    assert made[0]["start"] == slot
    assert result["meeting_url"] == "https://meet.example/abc"
    tasks = client_for(org, tutor_user).get("/api/v1/me/tasks").json()
    assert [t["status"] for t in tasks] == ["done"]  # the booked call, still to come
    assert tasks[0]["result"]["meeting_url"] == "https://meet.example/abc"
    assert "host_url" not in tasks[0]["result"]


# --- API ----------------------------------------------------------------------------------------


def test_templates_can_be_used_by_default_and_reset_through_the_api(org, api):
    with tenant_context(org):
        services.install_builtins()
        join = PathwayTemplate.objects.get(builtin_key="join_job")
        stage = join.stages[0]
    response = api.patch(
        f"/api/v1/pathway-templates/{join.pk}", {"used_by_default": True}, format="json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["used_by_default"] is True
    with tenant_context(org):
        assert get_setting("pathways.default_templates") == {"join": join.key}
    edited = api.patch(
        f"/api/v1/pathway-templates/{join.pk}",
        {"stages": [{**stage, "steps": stage["steps"][:1]}]},
        format="json",
    ).json()
    assert edited["edited"] is True
    assert edited["update_available"] is False
    reset = api.post(f"/api/v1/pathway-templates/{join.pk}/reset-to-default")
    assert reset.status_code == 200
    assert reset.json()["edited"] is False
    off = api.patch(f"/api/v1/pathway-templates/{join.pk}", {"active": False}, format="json")
    assert off.json()["used_by_default"] is False  # switching it off stops it starting
    schema = api.get("/api/v1/pathway-schema").json()
    assert "photo_id" in {r["key"] for r in schema["requirements"]}
    assert {"show_check", "book_call", "trial_lesson", "family_chooses"} <= {
        t["key"] for t in schema["step_types"]
    }


def test_jobs_show_where_each_tutor_is_in_joining(org, api):
    _join_template(org)
    job, tutor = make_job(org), make_tutor(org)
    with tenant_context(org):
        jobs.add_tutor(job, tutor=tutor)
    deliver(org, "job.tutor_assigned")
    body = api.get(f"/api/v1/jobs/{job.pk}").json()
    assert body["tutors"][0]["join_status"] == "joining"
    assert body["join_template"] is None
