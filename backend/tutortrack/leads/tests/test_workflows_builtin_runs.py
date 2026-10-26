"""E33-T06: the enquiry follow-up built-in running on Temporal: thank the family, then flag
the enquiry when its stage's time limit is up, and stop when it moves on."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import transaction

from tutortrack.automations import services as automations
from tutortrack.automations.models import AutomationRun
from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.time import now
from tutortrack.leads import services
from tutortrack.leads.models import Enquiry

pytestmark = pytest.mark.django_db(transaction=True)


def run_for(org, key: str, subject_id) -> AutomationRun:
    with tenant_context(org):
        return AutomationRun.objects.get(automation__builtin_key=key, subject_id=str(subject_id))


def new_enquiry(org, waited_hours: int) -> Enquiry:
    with tenant_context(org), transaction.atomic():
        enquiry = services.create_enquiry(
            contact={"first_name": "Priya", "email": "priya@example.com"},
            students=[{"first_name": "Arjun"}],
        )
        Enquiry.objects.filter(pk=enquiry.pk).update(
            stage_entered_at=now() - timedelta(hours=waited_hours)
        )
    return enquiry


def test_the_follow_up_thanks_the_family_and_flags_a_late_enquiry(org, temporal_env):
    with tenant_context(org):
        automations.install_builtins()
    dispatch_batch()
    enquiry = new_enquiry(org, waited_hours=25)  # "New" allows 24 hours
    dispatch_batch()  # enquiry.received starts the run; the time limit has passed
    run = run_for(org, "enquiry_follow_up", enquiry.pk)
    assert temporal_env.result(run.workflow_id) == "completed"
    with tenant_context(org):
        enquiry.refresh_from_db()
        assert enquiry.sla_breached_at is not None
        assert Message.objects.filter(type_key="enquiry_acknowledgement").count() == 1
        run.refresh_from_db()
        outcomes = {s.step_key: s.status for s in run.steps.filter(step_type="action")}
    assert list(outcomes.values()) == ["completed", "skipped", "completed"]  # no owner to tell


def test_moving_the_enquiry_on_stops_the_follow_up(org, temporal_env):
    with tenant_context(org):
        automations.install_builtins()
    dispatch_batch()
    enquiry = new_enquiry(org, waited_hours=0)
    dispatch_batch()
    run = run_for(org, "enquiry_follow_up", enquiry.pk)
    with tenant_context(org):
        services.move(enquiry, enquiry.pipeline.stages.get(name="Contacted"))
    dispatch_batch()  # enquiry.stage_changed: stop this run, watch "Contacted"
    assert temporal_env.result(run.workflow_id) == "stopped"
    with tenant_context(org):
        enquiry.refresh_from_db()
        assert enquiry.sla_breached_at is None
        assert run_for(org, "enquiry_stage_limits", enquiry.pk).status in ("running", "waiting")
