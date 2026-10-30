"""E34-T01: the pathways API, tenant isolation, privacy, webhooks and the workflow catalogue."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.pathways import services
from tutortrack.pathways.models import PathwayRun, PathwayStep

from .factories import TWO_STAGES, make_job, make_template, make_tutor

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_temporal(monkeypatch):
    monkeypatch.setattr(services, "start", lambda *a, **k: None)
    monkeypatch.setattr(services, "signal", lambda *a, **k: None)


def _client(org, role):
    return client_for(org, MembershipFactory(organisation=org, role=role).user)


def test_templates_are_created_and_versioned_through_the_api(org, api):
    created = api.post(
        "/api/v1/pathway-templates",
        {"name": "Join a job", "kind": "join", "record_type": "job", "stages": TWO_STAGES},
        format="json",
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert (body["version"], body["record_type"], body["key"]) == (1, "job", "join-a-job")
    assert [s["key"] for s in body["stages"]] == ["paperwork", "ready"]
    changed = api.patch(
        f"/api/v1/pathway-templates/{body['id']}",
        {"stages": [{"key": "only", "name": "Only", "steps": TWO_STAGES[0]["steps"]}]},
        format="json",
    )
    assert changed.status_code == 200, changed.content
    assert changed.json()["version"] == 2
    bad = api.post(
        "/api/v1/pathway-templates",
        {"name": "Bad", "record_type": "spaceship", "stages": TWO_STAGES},
        format="json",
    )
    assert bad.status_code == 422


def test_tutors_cant_see_or_change_templates(org):
    tutor = make_tutor(org)
    client = client_for(org, tutor.membership.user)
    assert client.get("/api/v1/pathway-templates").status_code == 403
    assert client.get("/api/v1/pathway-runs").status_code == 403
    assert client.get("/api/v1/pathway-schema").status_code == 403


def test_coordinators_start_follow_and_cancel_runs(org):
    template = make_template(org)
    tutor = make_tutor(org)
    job = make_job(org)
    coordinator = _client(org, "coordinator")
    started = coordinator.post(
        "/api/v1/pathway-runs",
        {"template": str(template.pk), "record_id": str(job.pk), "tutor": str(tutor.pk)},
        format="json",
    )
    assert started.status_code == 201, started.content
    run = started.json()
    assert run["status"] == "running"
    assert run["stage"] == "paperwork"
    assert run["progress"] == {"finished": 0, "total": 3}
    assert [s["step_type"] for s in run["steps"]] == ["sign", "acknowledge", "staff_review"]
    listed = coordinator.get(f"/api/v1/pathway-runs?record_type=job&record_id={job.pk}").json()
    assert [r["id"] for r in listed["results"]] == [run["id"]]
    skipped = coordinator.post(
        f"/api/v1/pathway-runs/{run['id']}/steps/agreement/skip",
        {"reason": "Signed on paper"},
        format="json",
    )
    assert skipped.status_code == 200, skipped.content
    assert skipped.json()["status"] == "skipped"
    cancelled = coordinator.post(f"/api/v1/pathway-runs/{run['id']}/cancel", {}, format="json")
    assert cancelled.json()["status"] == "cancelled"


def test_tutors_see_and_do_their_own_tasks(org):
    template = make_template(org)
    tutor = make_tutor(org)
    with tenant_context(org):
        run = services.start_run(template, record_id=make_job(org).pk, tutor=tutor)
    client = client_for(org, tutor.membership.user)
    tasks = client.get("/api/v1/me/tasks").json()
    assert [t["name"] for t in tasks] == ["Sign the job agreement", "Read the safeguarding policy"]
    assert tasks[1]["view"]["title"] == "Safeguarding"
    step = tasks[1]["id"]
    done = client.post(f"/api/v1/me/tasks/{step}/complete", {}, format="json")
    assert done.status_code == 200, done.content
    assert done.json()["status"] == "done"
    other = client_for(org, make_tutor(org).membership.user)
    assert other.get("/api/v1/me/tasks").json() == []
    assert other.post(f"/api/v1/me/tasks/{tasks[0]['id']}/complete", {}).status_code == 404
    with tenant_context(org):
        assert PathwayStep.objects.get(run=run, key="safeguarding").completed_by_id == (
            tutor.membership.user_id
        )


def test_staff_steps_through_the_api_follow_their_role(org):
    template = make_template(org, [{"key": "a", "name": "A", "steps": [
        {"key": "check", "type": "staff_review", "assignee": "staff", "role": "finance",
         "config": {"question": "Rates agreed?"}},
    ]}])  # fmt: skip
    with tenant_context(org):
        run = services.start_run(template, record_id=make_job(org).pk, tutor=make_tutor(org))
    url = f"/api/v1/pathway-runs/{run.pk}/steps/check/complete"
    assert _client(org, "coordinator").post(url, {}, format="json").status_code == 403
    done = _client(org, "admin").post(url, {"note": "Yes"}, format="json")
    assert done.status_code == 200, done.content
    assert done.json()["result"] == {"decision": "approved", "note": "Yes"}


def test_the_schema_lists_step_types_record_types_and_questions(org, api):
    body = api.get("/api/v1/pathway-schema").json()
    types = {t["key"]: t["assignees"] for t in body["step_types"]}
    assert types["sign"] == ["participant"]
    assert types["staff_review"] == ["staff"]
    assert {"job", "tutor", "pathway_run"} <= {r["key"] for r in body["record_types"]}
    assert {"key": "job.active", "label": "The job is active", "record_type": "job"} in body[
        "questions"
    ]


def test_finished_pathways_are_a_webhook_event_and_the_rest_stay_internal():
    from tutortrack.developer.catalogue import event_types

    keys = {t.key for t in event_types()}
    assert "pathway.completed" in keys
    assert not keys & {"pathway.started", "pathway.step_completed", "pathway.cancelled"}


def test_pathways_are_a_record_type_for_workflows():
    from tutortrack.automations import registry

    assert registry.subject("pathway_run") is not None
    assert registry.trigger("pathway.completed").subject == "pathway_run"


def test_a_tutors_answers_are_exported_and_erased(org, s3):
    from tutortrack.privacy.registry import ErasureContext, Person, providers

    template = make_template(org, [{"key": "a", "name": "A", "steps": [
        {"key": "about", "type": "questions",
         "config": {"fields": [{"key": "why", "label": "Why", "type": "text"}]}},
    ]}])  # fmt: skip
    tutor = make_tutor(org)
    with tenant_context(org):
        run = services.start_run(template, record_id=make_job(org).pk, tutor=tutor)
        services.complete_step(
            PathwayStep.objects.get(run=run, key="about"),
            user=tutor.membership.user,
            payload={"answers": {"why": "I love algebra"}},
        )
        provider = next(p for p in providers() if p.key == "pathways")
        person = Person(subject_type="people.tutor", subject_id=str(tutor.pk))
        person.add("people.tutor", tutor.pk)
        [section] = provider.export(person)
        assert "I love algebra" in str(section.records)
        provider.erase(person, ErasureContext(labels={}, financial_cutoff=now()))
        assert PathwayStep.objects.get(run=run, key="about").result == {"erased": True}


class TestPathwayTemplateIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/pathway-templates"

    def make_object(self, organisation):
        return make_template(organisation)


class TestPathwayRunIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/pathway-runs"

    def make_object(self, organisation):
        template = make_template(organisation)
        with tenant_context(organisation):
            return services.start_run(
                template, record_id=make_job(organisation).pk, tutor=make_tutor(organisation)
            )


def test_runs_are_not_shared_between_organisations(org, other_org):
    run = TestPathwayRunIsolation().make_object(other_org)
    client = _client(org, "admin")
    assert client.get(f"/api/v1/pathway-runs/{run.pk}").status_code == 404
    assert (
        client.post(f"/api/v1/pathway-runs/{run.pk}/steps/check/skip", {"reason": "x"}).status_code
        == 404
    )
    with tenant_context(org):
        assert not PathwayRun.objects.filter(pk=run.pk).exists()
