"""E33-T07: the API the sequence editor uses: the /workflows and /workflow-runs aliases,
and what /workflow-schema adds for it (the dates a start counts from, each action's
message)."""

from __future__ import annotations

import pytest

from tutortrack.automations import services
from tutortrack.core.context import tenant_context
from tutortrack.core.testing import TenantIsolationTestMixin
from tutortrack.people.tests.factories import StudentFactory

from .test_automations import make

pytestmark = pytest.mark.django_db


def test_workflows_are_the_automations_under_their_product_name(org, api):
    automation = make(org)
    listed = api.get("/api/v1/workflows").json()
    assert [w["id"] for w in listed] == [str(automation.pk)]
    detail = api.get(f"/api/v1/workflows/{automation.pk}").json()
    assert detail == api.get(f"/api/v1/automations/{automation.pk}").json()
    paused = api.post(f"/api/v1/workflows/{automation.pk}/pause")
    assert paused.status_code == 200, paused.content
    assert paused.json()["paused"] is True
    assert api.get("/api/v1/workflow-runs").status_code == 200


def test_the_schema_gives_start_dates_and_each_actions_message(api):
    body = api.get("/api/v1/workflow-schema").json()
    kinds = {r["key"]: r for r in body["record_types"]}
    assert {"field": "start", "label": "Start", "type": "datetime"} in kinds["lesson"][
        "start_dates"
    ]
    assert {"field": "expiry_date", "label": "Expires", "type": "date"} in kinds[
        "compliance_record"
    ]["start_dates"]
    actions = {a["key"]: a for a in body["actions"]}
    assert actions["send_lesson_reminder"]["message"] == "lesson_reminder"
    assert actions["add_tag"]["message"] == ""


class TestWorkflowIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/workflows"

    def make_object(self, organisation):
        return make(organisation)


class TestWorkflowRunIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/workflow-runs"

    def make_object(self, organisation):
        automation = make(
            organisation, trigger_type="manual", trigger_config={"subject": "student"}
        )
        with tenant_context(organisation):
            student = StudentFactory(organisation=organisation)
            return services.prepare_run(automation, subject_id=str(student.pk),
                                        run_key="manual:x", manual=True)  # fmt: skip
