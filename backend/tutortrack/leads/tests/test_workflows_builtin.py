"""E33-T06: the sales and onboarding built-in workflows: first versions from the settings,
what starts them, the enquiry and trial actions, and the replaced settings."""

from __future__ import annotations

from datetime import timedelta

import pytest
from rest_framework.exceptions import ValidationError

from tutortrack.automations import services as automations
from tutortrack.automations.models import Automation, AutomationRun
from tutortrack.automations.tests.test_catalogue import act
from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.comms.models import Message
from tutortrack.core import workflows
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery
from tutortrack.leads import services
from tutortrack.leads.models import Enquiry
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db

KEYS = {"enquiry_follow_up", "enquiry_stage_limits", "trial_follow_up", "welcome_family"}


def install(org, **settings) -> dict[str, Automation]:
    with tenant_context(org):
        if settings:
            settings_service.update_settings("leads", settings, allow_replaced=True)
        automations.install_builtins()
        return {a.builtin_key: a for a in Automation.objects.filter(builtin_key__in=KEYS)}


def short(steps) -> list[str]:
    def one(s):
        if s["type"] == "action":
            return s["action"]
        return (
            f"until {s['until']}"
            if s.get("until")
            else f"wait {s.get('days', 0)}d{s.get('hours', 0)}h"
        )

    return [one(s) for s in steps]


def launched(monkeypatch) -> list[AutomationRun]:
    started: list[AutomationRun] = []
    monkeypatch.setattr(automations, "launch", lambda run, **kw: started.append(run))
    return started


def new_enquiry(org, **kwargs) -> Enquiry:
    with tenant_context(org):
        return services.create_enquiry(
            contact={"first_name": "Priya", "email": "priya@example.com"},
            students=[{"first_name": "Arjun"}],
            **kwargs,
        )


def waited(org, enquiry: Enquiry, hours: int) -> Enquiry:
    """As if the enquiry had been in its stage for ``hours``."""
    with tenant_context(org):
        Enquiry.objects.filter(pk=enquiry.pk).update(
            stage_entered_at=now() - timedelta(hours=hours)
        )
        return Enquiry.objects.select_related("stage").get(pk=enquiry.pk)


# --- first versions ------------------------------------------------------------------------


def test_with_the_default_settings_each_starts_as_the_default(org):
    installed = install(org)
    assert set(installed) == KEYS
    assert not any(a.edited for a in installed.values())
    assert {k for k, a in installed.items() if a.enabled} == KEYS - {"welcome_family"}
    follow_up = installed["enquiry_follow_up"]
    assert short(follow_up.steps) == [
        "thank_for_enquiry", "tell_enquiry_owner", "until enquiry.stage_deadline",
        "flag_enquiry_waiting",
    ]  # fmt: skip
    assert follow_up.stop_when == ["enquiry.stage_changed", "enquiry.won", "enquiry.lost"]
    limits = installed["enquiry_stage_limits"]
    assert limits.trigger_key == "enquiry.stage_changed"
    assert limits.max_runs_per_record == 50
    assert short(installed["trial_follow_up"].steps) == ["wait 0d24h", "ask_trial_outcome"]
    assert short(installed["welcome_family"].steps) == [
        "send_message", "wait 14d0h", "create_task",
    ]  # fmt: skip


def test_each_takes_the_settings_it_replaces(org):
    installed = install(org, **{"leads.acknowledge": False, "leads.trial_follow_up_hours": 48})
    assert short(installed["enquiry_follow_up"].steps)[0] == "tell_enquiry_owner"
    assert short(installed["trial_follow_up"].steps) == ["wait 0d48h", "ask_trial_outcome"]
    assert installed["enquiry_follow_up"].edited
    assert installed["trial_follow_up"].edited


def test_replaced_settings_are_read_only(org):
    with tenant_context(org), pytest.raises(ValidationError) as refused:
        settings_service.update_settings("leads", {"leads.trial_follow_up_hours": 12})
    assert "Workflows" in str(refused.value.detail["leads.trial_follow_up_hours"][0])
    with tenant_context(org):  # the stage time limits and other leads settings stay
        settings_service.update_settings("leads", {"leads.waitlist_offer_hours": 24})


# --- what starts them ----------------------------------------------------------------------


def test_new_enquiries_start_the_follow_up_but_imported_ones_dont(org, monkeypatch):
    install(org)
    started = launched(monkeypatch)
    typed = new_enquiry(org)
    new_enquiry(org, source=Enquiry.Source.IMPORT)
    dispatch_batch()
    assert [(r.automation.builtin_key, r.subject_id) for r in started] == [
        ("enquiry_follow_up", str(typed.pk))
    ]


def test_moving_stage_stops_the_last_watch_and_watches_the_new_stage(org, monkeypatch):
    install(org)
    started = launched(monkeypatch)
    signalled: list[tuple[str, str]] = []
    monkeypatch.setattr(workflows, "signal", lambda wid, name, *a: signalled.append((wid, name)))
    enquiry = new_enquiry(org)
    dispatch_batch()
    [follow_up] = started
    with tenant_context(org):
        services.move(enquiry, enquiry.pipeline.stages.get(name="Contacted"))
    dispatch_batch()
    assert (follow_up.workflow_id, "stop") in signalled
    assert [r.automation.builtin_key for r in started[1:]] == ["enquiry_stage_limits"]
    with tenant_context(org):  # a stage without a time limit isn't watched
        services.move(enquiry, enquiry.pipeline.stages.get(name="Trial booked"))
    dispatch_batch()
    assert len(started) == 2
    assert (started[1].workflow_id, "stop") in signalled


# --- actions -------------------------------------------------------------------------------


def test_thank_tell_and_flag_the_enquiry(org):
    enquiry = new_enquiry(org)
    assert act(org, "thank_for_enquiry", "enquiry", enquiry) == {"thanked": str(enquiry.pk)}
    assert act(org, "tell_enquiry_owner", "enquiry", enquiry) == {
        "skipped": "nobody is looking after the enquiry"
    }
    assert act(org, "flag_enquiry_waiting", "enquiry", enquiry) == {
        "skipped": "the enquiry moved on in time"
    }
    late = waited(org, enquiry, 25)  # "New" has a 24-hour time limit
    assert act(org, "flag_enquiry_waiting", "enquiry", late, step="b") == {
        "flagged": str(enquiry.pk)
    }
    assert act(org, "flag_enquiry_waiting", "enquiry", late, step="c") == {
        "skipped": "it was already flagged"
    }
    with tenant_context(org):
        late.refresh_from_db()
        assert late.sla_breached_at is not None
        assert Message.objects.filter(type_key="enquiry_acknowledgement").count() == 1
        services.move(late, late.pipeline.stages.get(name="Trial booked"))
    assert act(org, "flag_enquiry_waiting", "enquiry", late, step="d") == {
        "skipped": "the stage has no time limit"
    }


def test_ask_how_the_trial_went_until_the_outcome_is_recorded(org):
    enquiry = new_enquiry(org)
    with tenant_context(org):
        start = (now() - timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
        booked = services.book_trial(
            enquiry, start=start, end=start + timedelta(hours=1),
            service=ServiceFactory(organisation=org),
            tutor=TutorProfileFactory(organisation=org, status="active"),
            price=Money("0", "GBP"),
        )  # fmt: skip
        lesson = booked.trial_lesson
        delivery.complete_lesson(lesson)
    assert act(org, "ask_trial_outcome", "lesson", lesson) == {"asked": str(enquiry.pk)}
    with tenant_context(org):
        services.record_trial_outcome(booked, outcome="continuing")
    assert act(org, "ask_trial_outcome", "lesson", lesson, step="b") == {
        "skipped": "the outcome is recorded or the enquiry is closed"
    }
