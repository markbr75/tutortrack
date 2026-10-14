"""Gap batch G4 for automations: feedback survey, mailing list, WhatsApp and saved-message
actions (FR-14-3), package triggers and the "package under 2 hours" recipe (FR-14-1/6)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from tutortrack.automations import conditions, recipes, registry, services
from tutortrack.billing.models import PackagePurchase
from tutortrack.comms import services as comms
from tutortrack.comms.models import Message
from tutortrack.comms.tests.factories import CannedReplyFactory, WhatsAppTemplateFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.events import EventEnvelope
from tutortrack.core.time import now
from tutortrack.crm.services import tags_for

from .test_automations import _execute, api_as, family, make  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db


def package(org, client, *, remaining="1.5", kind="hours"):
    with tenant_context(org):
        return PackagePurchase.objects.create(
            client=client,
            name="10 hours of Maths",
            quantity_type=kind,
            units_total=Decimal(10),
            units_used=Decimal(10) - Decimal(remaining),
            currency="GBP",
            price_amount=Decimal(300),
            status="active",
        )


def test_package_subject_and_triggers_are_registered():
    subject = registry.subject("package")
    assert subject is not None
    assert "client" in subject.recipients
    for event in ("package.low", "package.depleted", "package.expiring", "package.expired"):
        assert registry.trigger(event).subject == "package"
    assert {a.key for a in registry.actions()} >= {
        "send_feedback_survey",
        "add_to_mailing_list",
        "send_whatsapp",
        "send_saved_reply",
    }


def test_package_under_two_hours_recipe(org, family, monkeypatch):  # noqa: F811
    client, _student = family
    api, _user = api_as(org, "admin")
    found = recipes.recipe("package_low_hours")
    assert found is not None
    assert found.trigger_config == {"event": "package.low"}
    assert api.post("/api/v1/automation-recipes/package_low_hours/install").status_code == 201
    low = package(org, client, remaining="1.5")
    lessons = package(org, client, remaining="1", kind="lessons")
    plenty = package(org, client, remaining="3")
    with tenant_context(org):
        for purchase, expected in ((low, True), (lessons, False), (plenty, False)):
            ctx = {"package": registry.subject("package").context(purchase)}
            assert conditions.evaluate(found.conditions, ctx) is expected
        automation = services.create_automation(
            name="Live",
            trigger_type="event",
            trigger_config={"event": "package.low"},
            conditions_=found.conditions,
            steps=found.steps,
            enabled=True,
        )
        launched = []
        monkeypatch.setattr(services, "launch", lambda run, **kw: launched.append(run))
        event = EventEnvelope(
            id=uuid.uuid4(),
            type="package.low",
            version=1,
            occurred_at=now(),
            organisation_id=org.pk,
            branch_id=None,
            actor={"type": "system", "id": None},
            subject={"type": "package", "id": str(low.pk)},
            data={},
            changes={},
        )
        runs = services.on_event(event)
    assert [r.automation_id for r in runs] == [automation.pk]
    _run, result = _execute(org, automation, low, found.steps[0])
    assert result["status"] == "completed", result
    with tenant_context(org):
        message = Message.objects.get(type_key="automation_message")
        assert "1.5 hours left" in message.body


def test_feedback_survey_action(org, family, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(
        "tutortrack.delivery.feedback.send_for_lesson", lambda pk: calls.append(pk) or ["f1"]
    )
    from tutortrack.automations import g4

    ctx = type("Ctx", (), {"obj": type("Lesson", (), {"pk": "lesson-1"})()})()
    assert g4.feedback_survey(ctx, {}) == {"sent": 1, "note": ""}
    assert calls == ["lesson-1"]
    action = registry.action("send_feedback_survey")
    assert action.subjects == ("lesson",)


def test_mailing_list_action_tags_and_syncs(org, family, monkeypatch):  # noqa: F811
    client, student = family
    queued = []
    monkeypatch.setattr("tutortrack.comms.marketing.queue_contact_sync", queued.append)
    step = {
        "type": "action",
        "action": "add_to_mailing_list",
        "config": {"list": "Summer school", "sync": True},
    }
    automation = make(org, [step], trigger_config={"event": "student.status_changed"})
    _run, result = _execute(org, automation, student, step)
    assert result["status"] == "completed", result
    with tenant_context(org):
        tags = [t.name for t in tags_for("people.client", [str(client.pk)])[str(client.pk)]]
    assert "Summer school" in tags
    assert queued == [str(client.primary_contact_id)]


def test_whatsapp_action_needs_an_approved_utility_template_and_opt_in(org, family):  # noqa: F811
    client, student = family
    with tenant_context(org):
        contact = client.primary_contact
        contact.mobile = "07700 900123"
        contact.save()
        template = WhatsAppTemplateFactory(organisation=org)
        marketing = WhatsAppTemplateFactory(organisation=org, category="marketing")
    step = {
        "type": "action",
        "action": "send_whatsapp",
        "config": {"to": ["client"], "template": str(template.pk)},
    }
    automation = make(org, [step])
    _run, result = _execute(org, automation, student, step)
    assert result["status"] == "completed", result
    with tenant_context(org):
        assert not Message.objects.filter(channel="whatsapp").exists()  # no opt-in yet
        comms.set_preference("contact", str(contact.pk), "account", ["email", "whatsapp"])
    _run, result = _execute(org, automation, student, step, key="1")
    with tenant_context(org):
        sent = Message.objects.get(channel="whatsapp")
        assert sent.meta["content_sid"] == "HX-test-template"
        assert sent.body.startswith("Hi Priya")
    bad = {**step, "config": {"to": ["client"], "template": str(marketing.pk)}}
    _run, result = _execute(org, automation, student, bad, key="2")
    assert result["status"] == "failed"


def test_saved_reply_action(org, family):  # noqa: F811
    _client, student = family
    with tenant_context(org):
        reply = CannedReplyFactory(
            organisation=org,
            title="Welcome back",
            body="Hello {{ recipient.first_name }}, {{ student.first_name }} is booked in.",
        )
    step = {
        "type": "action",
        "action": "send_saved_reply",
        "config": {"to": ["client"], "channels": ["email"], "template": str(reply.pk)},
    }
    automation = make(org, [step])
    _run, result = _execute(org, automation, student, step)
    assert result["status"] == "completed", result
    with tenant_context(org):
        message = Message.objects.get(type_key="automation_message")
        assert message.subject == "Welcome back"
        assert "Hello Priya, Arjun is booked in." in message.body
        preview = services.dry_run(automation, str(student.pk))
    assert "Welcome back" in str(preview["steps"])


def test_new_actions_appear_in_the_builder_schema(org):
    api, _user = api_as(org, "admin")
    schema = api.get("/api/v1/automation-schema").json()
    by_key = {a["key"]: a for a in schema["actions"]}
    assert by_key["send_whatsapp"]["fields"][1]["type"] == "whatsapp_template"
    assert by_key["send_saved_reply"]["fields"][2]["type"] == "saved_reply"
    assert "package" in {s["key"] for s in schema["subjects"]}
