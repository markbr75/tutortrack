"""E33-T06: the compliance expiry built-in workflow: its first version, the daily start on
several days before a date, the reminder action, and what it replaced."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import transaction
from rest_framework.exceptions import ValidationError

from tutortrack.automations import services as automations
from tutortrack.automations.models import Automation, AutomationRun
from tutortrack.automations.tests.test_catalogue import act
from tutortrack.comms.models import Message
from tutortrack.core import workflows
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.recruitment import compliance
from tutortrack.recruitment.models import ComplianceRecord, RequirementType
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db


def install(org, **settings) -> Automation:
    with tenant_context(org):
        if settings:
            settings_service.update_settings("compliance", settings, allow_replaced=True)
        automations.install_builtins()
        return Automation.objects.get(builtin_key="compliance_expiry")


def verified(org, days_left: int, *, verify: bool = True) -> ComplianceRecord:
    """A tutor's enhanced DBS expiring ``days_left`` days from today."""
    with tenant_context(org):
        tutor = TutorProfileFactory(
            organisation=org, status="active",
            membership=MembershipFactory(organisation=org, role="tutor"),
        )  # fmt: skip
        compliance.ensure_requirement_types()
        requirement = RequirementType.objects.get(key="dbs_enhanced")
        expiry = compliance.today() + timedelta(days=days_left)
        with transaction.atomic():
            record = compliance.submit(tutor, requirement, number="123", expiry_date=expiry)
            if verify:
                compliance.verify(record, user=MembershipFactory(organisation=org).user)
        return ComplianceRecord.objects.get(pk=record.pk)


def test_the_first_version_takes_the_reminder_days(org):
    default = install(org)
    assert not default.edited and default.enabled  # noqa: PT018
    assert default.trigger_config == {
        "subject": "compliance_record", "field": "expiry_date",
        "offset_days": [-60, -30, -7], "time": "09:00",
    }  # fmt: skip
    assert default.conditions == {"predicate": "compliance_record.verified"}
    with tenant_context(org):
        default.delete()
    changed = install(org, **{"compliance.reminder_days": [14, 90]})
    assert changed.edited
    assert changed.trigger_config["offset_days"] == [-90, -14]
    with tenant_context(org):
        changed.delete()
    assert not install(org, **{"compliance.reminder_days": []}).enabled


def test_each_reminder_day_picks_the_checks_expiring_then(org, monkeypatch):
    reminders = install(org)
    due = [verified(org, days) for days in (60, 30, 7)]
    verified(org, 20)  # not a reminder day
    verified(org, 30, verify=False)  # waiting for verification
    started: list[AutomationRun] = []
    monkeypatch.setattr(automations, "launch", lambda run, **kw: started.append(run))
    with tenant_context(org):
        assert automations.fan_out(str(reminders.pk), on=compliance.today()) == 3
        assert automations.fan_out(str(reminders.pk), on=compliance.today()) == 0  # once a day
    assert {r.subject_id for r in started} == {str(r.pk) for r in due}


def test_the_reminder_says_how_many_days_are_left_once(org):
    record = verified(org, 30)
    assert act(org, "remind_compliance_expiry", "compliance_record", record) == {
        "reminded": str(record.pk), "days": 30,
    }  # fmt: skip
    with tenant_context(org):
        sent = Message.objects.filter(type_key="compliance_reminder").count()
    assert sent
    act(org, "remind_compliance_expiry", "compliance_record", record, step="b")
    with tenant_context(org):
        [event] = OutboxEvent.objects.filter(event_type="compliance.expiring")
        assert event.payload["data"]["days"] == 30
        assert Message.objects.filter(type_key="compliance_reminder").count() == sent
    with tenant_context(org):
        compliance.reject(
            record, reason="Blurred scan", user=MembershipFactory(organisation=org).user
        )
    assert act(org, "remind_compliance_expiry", "compliance_record", record, step="c") == {
        "skipped": "the check isn't verified any more"
    }


def test_new_expiry_runs_leave_the_reminders_to_the_workflow(org, monkeypatch):
    started = []
    monkeypatch.setattr(workflows, "start_now", lambda wf, input, **kw: started.append(input))
    verified(org, 90)
    dispatch_batch()  # compliance.record_verified → ComplianceRecordWorkflow (expiry only)
    assert [i.reminder_days for i in started] == [[]]
    with tenant_context(org), pytest.raises(ValidationError):
        settings_service.update_settings("compliance", {"compliance.reminder_days": [10]})


def test_date_starts_check_their_days(org):
    def save(offset_days):
        with tenant_context(org):
            automations.create_automation(
                name="x", trigger_type="date",
                trigger_config={"subject": "compliance_record", "field": "expiry_date",
                                "offset_days": offset_days},
                steps=[{"type": "action", "action": "remind_compliance_expiry", "config": {}}],
            )  # fmt: skip

    for bad in ([], [1, 2, 3, 4, 5, 6, 7], [400], ["soon"]):
        with pytest.raises(BusinessRuleViolation):
            save(bad)
    save([-30, -7])
    save(-14)
