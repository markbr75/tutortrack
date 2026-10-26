"""E33-T06: the review request built-in workflow: its first version, what starts it, its
actions, and the replaced setting."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tutortrack.automations import services as automations
from tutortrack.automations.models import Automation, AutomationRun
from tutortrack.automations.tests.test_catalogue import act
from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.growth import services
from tutortrack.growth.models import ReviewRequest
from tutortrack.tenancy import settings_service

from .test_growth import ask, world  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


def install(org, **settings) -> Automation:
    with tenant_context(org):
        if settings:
            settings_service.update_settings("growth", settings, allow_replaced=True)
        automations.install_builtins()
        return Automation.objects.get(builtin_key="review_request")


def short(steps) -> list[str]:
    def one(s):
        if s["type"] == "action":
            return s["action"]
        return f"until {s['until']}" if s.get("until") else f"wait {s['days']}d"

    return [one(s) for s in steps]


def test_the_first_version_takes_the_reminder_days(org):
    default = install(org)
    assert not default.edited
    assert default.enabled
    assert short(default.steps) == [
        "send_review_link", "wait 4d", "remind_review", "until review_request.expires_at",
        "close_review_request",
    ]  # fmt: skip
    with tenant_context(org):
        default.delete()
    changed = install(org, **{"growth.review_reminder_days": 7})
    assert changed.edited
    assert short(changed.steps)[1] == "wait 7d"


def test_it_cant_be_switched_off_but_can_be_paused(org):
    review = install(org)
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation):
            automations.set_enabled(review, False)
        assert automations.pause(review).paused


def test_each_request_starts_it(org, world, monkeypatch):  # noqa: F811
    install(org)
    started: list[AutomationRun] = []
    monkeypatch.setattr(automations, "launch", lambda run, **kw: started.append(run))
    request = ask(org, world)
    dispatch_batch()
    assert [r.subject_id for r in started] == [str(request.pk)]
    assert request.workflow_id == ""  # no ReviewRequestWorkflow any more


def test_send_remind_and_close(org, world):  # noqa: F811
    request = ask(org, world)
    assert act(org, "send_review_link", "review_request", request) == {"sent": str(request.pk)}
    assert act(org, "remind_review", "review_request", request) == {"reminded": str(request.pk)}
    assert act(org, "remind_review", "review_request", request, step="b") == {
        "skipped": "the family has reviewed, or was already reminded"
    }
    assert act(org, "close_review_request", "review_request", request) == {"status": "expired"}
    with tenant_context(org):
        assert Message.objects.filter(type_key="review_request").count() == 2
    assert act(org, "send_review_link", "review_request", request, step="c") == {
        "skipped": "the family has reviewed or the request was closed"
    }


def test_a_reviewed_or_closed_link_isnt_chased(org, world):  # noqa: F811
    request = ask(org, world)
    with tenant_context(org):
        services.submit_review(request, rating=5, text="Great")
    assert act(org, "remind_review", "review_request", request) == {
        "skipped": "the family has reviewed, or was already reminded"
    }
    assert act(org, "close_review_request", "review_request", request) == {
        "skipped": "the family has reviewed or the request was closed"
    }
    with tenant_context(org):  # another request whose link has run out
        other = services.request_review(client=world["client"])
        ReviewRequest.objects.filter(pk=other.pk).update(expires_at=now() - timedelta(hours=1))
    assert act(org, "remind_review", "review_request", other) == {"skipped": "the link has closed"}


def test_the_reminder_setting_is_read_only_and_the_others_still_save(org, world):  # noqa: F811
    api = world["api"]
    described = {d["key"]: d for d in api.get("/api/v1/settings/growth").json()["schema"]}
    assert described["growth.review_reminder_days"]["replaced_by"] == "review_request"
    assert "replaced_by" not in described["growth.review_after_lessons"]
    refused = api.patch("/api/v1/settings/growth",
                        {"values": {"growth.review_reminder_days": 2}}, format="json")  # fmt: skip
    assert refused.status_code == 400
    saved = api.patch("/api/v1/settings/growth",
                      {"values": {"growth.review_after_lessons": 3}}, format="json")  # fmt: skip
    assert saved.status_code == 200, saved.content
