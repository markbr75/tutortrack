"""E13-T01..T08: notification settings, templates, the pipeline, email and SMS channels,
reminders, preferences and unsubscribe, delivery webhooks and in-app notifications."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.core import mail

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.comms import channels, handlers, services
from tutortrack.comms.models import InAppNotification, Message, SmsOptOut, Suppression
from tutortrack.comms.tasks import send_lesson_reminders
from tutortrack.core.context import tenant_context
from tutortrack.core.events import EventEnvelope
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)
from tutortrack.scheduling import services as scheduling
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fake_sms():
    channels.sms_provider.cache_clear()
    provider = channels.sms_provider()
    yield provider
    channels.sms_provider.cache_clear()
    channels.set_credit_meter(channels._Unlimited())


@pytest.fixture
def admin(org):
    membership = MembershipFactory(organisation=org, role="admin")
    return client_for(org, membership.user), membership.user


@pytest.fixture
def family(org):
    client = ClientFactory(organisation=org, display_name="The Patels")
    contact = ContactFactory(
        organisation=org, client=client, first_name="Priya", email="priya@example.com",
        mobile="07700 900123", is_primary=True,
    )  # fmt: skip
    student = StudentFactory(organisation=org, client=client, first_name="Arjun")
    tutor_member = MembershipFactory(organisation=org, role="tutor")
    tutor = TutorProfileFactory(
        organisation=org, status="active", first_name="Nia", email="nia@example.com",
        membership=tutor_member,
    )  # fmt: skip
    service = ServiceFactory(organisation=org, name="Maths 1:1")
    return {"client": client, "contact": contact, "student": student, "tutor": tutor,
            "tutor_user": tutor_member.user, "service": service}  # fmt: skip


def snap(moment):
    return moment.replace(second=0, microsecond=0, minute=moment.minute - moment.minute % 5)


def lesson_at(org, family, start):
    start = snap(start)
    with tenant_context(org):
        return scheduling.create_lesson(
            start=start, end=start + timedelta(hours=1), service=family["service"],
            attendees=[{"student": family["student"]}], tutors=[{"tutor": family["tutor"]}],
            timezone="Europe/London", override_conflicts=True,
        ).lesson  # fmt: skip


def quiet_window(*, now_is_quiet: bool) -> dict[str, str]:
    """Quiet hours that do (or don't) include the current London time."""
    from zoneinfo import ZoneInfo

    local = now().astimezone(ZoneInfo("Europe/London"))
    if now_is_quiet:
        start, end = local - timedelta(hours=1), local + timedelta(hours=2)
    else:
        start, end = local + timedelta(hours=2), local + timedelta(hours=3)
    return {
        "comms.quiet_hours_start": start.strftime("%H:%M"),
        "comms.quiet_hours_end": end.strftime("%H:%M"),
    }


def run(org, event_type, handler):
    """Deliver the latest outbox event of a type to one subscriber (as the dispatcher does)."""
    from django.test import TestCase

    with tenant_context(org), TestCase.captureOnCommitCallbacks(execute=True):
        row = OutboxEvent.objects.filter(event_type=event_type).order_by("-occurred_at").first()
        assert row is not None, event_type
        handler(EventEnvelope.from_payload(row.payload))


def messages(org, **filters):
    with tenant_context(org):
        return list(Message.objects.filter(**filters).order_by("created_at"))


# --- settings and templates (T01/T02) -----------------------------------------------------------


def test_disable_sms_reminders_and_set_timing(org, admin):
    """AC: email reminders stay on, SMS off, at 24h and 2h."""
    api, _user = admin
    rows = {r["key"]: r for r in api.get("/api/v1/notification-settings").json()}
    assert rows["lesson_reminder"]["channels"] == ["email", "sms"]
    assert rows["lesson_reminder"]["timing"] == [1440, 120]
    updated = api.put(
        "/api/v1/notification-settings/lesson_reminder",
        {"enabled": True, "channels": ["email"], "timing": [1440, 120]},
        format="json",
    ).json()
    assert (updated["channels"], updated["customised"]) == (["email"], True)
    bad = api.put(
        "/api/v1/notification-settings/invoice_issued",
        {"enabled": True, "channels": ["sms"]},
        format="json",
    )
    assert bad.status_code == 422
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    assert tutor.get("/api/v1/notification-settings").status_code == 403


def test_template_override_preview_revert_and_test_send(org, admin):
    api, user = admin
    url = "/api/v1/message-templates/lesson_cancelled/email"
    default = api.get(url).json()
    assert default["customised"] is False
    assert "lesson.title" in default["variables"]
    saved = api.put(
        url,
        {"subject": "Off: {{ lesson.title }}", "body": "Sorry {{ recipient.first_name }}!"},
        format="json",
    ).json()
    assert (saved["customised"], saved["version"]) == (True, 1)
    assert api.put(url, {"subject": "x", "body": "v2"}, format="json").json()["version"] == 2
    preview = api.post(f"{url}/preview", {}, format="json").json()
    assert preview["body"] == "v2"
    draft = api.post(
        f"{url}/preview",
        {"subject": "{{ lesson.title }}", "body": "{{ lesson.start|datetime('short') }}"},
        format="json",
    ).json()
    assert draft["subject"] == "GCSE Maths \N{EN DASH} Arjun Patel"
    assert draft["body"].startswith("02/11/2026")
    broken = api.put(url, {"subject": "", "body": "{% if %}"}, format="json")
    assert broken.status_code == 422
    assert api.delete(url).json()["customised"] is False
    sent = api.post(f"{url}/test").json()
    assert sent["status"] == "sent"
    assert mail.outbox[-1].to == [user.email]


def test_templates_are_sandboxed():
    from tutortrack.comms import render

    assert render.render("{{ x.__class__.__mro__ }}", {"x": 1}) == ""
    assert render.sms_segments("a" * 160) == 1
    assert render.sms_segments("a" * 161) == 2
    assert render.sms_segments("é" * 71) == 2


# --- the pipeline (T03..T05) --------------------------------------------------------------------


def test_cancellation_notifies_family_and_tutor_once(org, family):
    lesson = lesson_at(org, family, now() + timedelta(days=3))
    with tenant_context(org):
        delivery.cancel_lesson(lesson, cancelled_by="admin", reason="Tutor ill")
    run(org, "lesson.cancelled", handlers.lesson_cancelled)
    run(org, "lesson.cancelled", handlers.lesson_cancelled)  # redelivered
    sent = messages(org, type_key="lesson_cancelled")
    assert sorted((m.channel, m.to) for m in sent) == [
        ("email", "nia@example.com"),
        ("email", "priya@example.com"),
        ("in_app", str(family["tutor_user"].pk)),
    ]
    assert {m.status for m in sent if m.channel == "email"} == {"sent"}
    email = next(m for m in mail.outbox if m.to == ["priya@example.com"])
    assert "Reason: Tutor ill" in email.body
    assert email.alternatives[0][1] == "text/html"
    assert email.extra_headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    with tenant_context(org):
        note = InAppNotification.objects.get(user=family["tutor_user"])
    assert note.title == "Lesson cancelled"


def test_preferences_suppressions_and_transactional_fallback(org, family):
    contact = family["contact"]
    with tenant_context(org):
        services.set_preference("contact", str(contact.pk), "scheduling", ["sms"])
        services.update_setting("lesson_cancelled", enabled=True, channels=["email", "sms"])
        services.suppress("email", "nia@example.com", "manual")
    lesson = lesson_at(org, family, now() + timedelta(days=3))
    with tenant_context(org):
        delivery.cancel_lesson(lesson, cancelled_by="admin")
    run(org, "lesson.cancelled", handlers.lesson_cancelled)
    rows = {(m.recipient_type, m.channel): m for m in messages(org)}
    assert ("contact", "email") not in rows  # the contact chose texts only
    assert rows[("contact", "sms")].to == "+447700900123"
    assert rows[("tutor", "email")].status == "suppressed"
    with tenant_context(org):
        services.set_preference("contact", str(contact.pk), "billing", [])
        from tutortrack.billing import services as billing
        from tutortrack.core.money import Money

        billing.create_ad_hoc_charge(
            client=family["client"], description="Fee", unit_price=Money(Decimal("10"), "GBP")
        )
        invoice = billing.issue_invoice(billing.create_draft(family["client"]), send=False)
    from tutortrack.billing.tasks import send_invoice_email

    assert send_invoice_email(organisation_id=str(org.pk), invoice_id=str(invoice.pk)) is True
    [sent] = messages(org, type_key="invoice_issued")
    assert sent.to == "priya@example.com"  # invoices can't be switched off entirely
    assert mail.outbox[-1].attachments[0][0] == invoice.number + ".pdf"


def test_sms_quiet_hours_stop_and_credits(org, family, fake_sms):
    with tenant_context(org):
        settings_service.update_settings("comms", quiet_window(now_is_quiet=True))
        services.update_setting("lesson_cancelled", enabled=True, channels=["sms"])
    lesson = lesson_at(org, family, now() + timedelta(days=3))
    with tenant_context(org):
        delivery.cancel_lesson(lesson, cancelled_by="admin")
    run(org, "lesson.cancelled", handlers.lesson_cancelled)
    [deferred] = messages(org, recipient_type="contact")
    assert deferred.status == "queued"
    assert deferred.scheduled_for is not None  # held until quiet hours end
    assert fake_sms.outbox == []

    with tenant_context(org):
        settings_service.update_settings("comms", quiet_window(now_is_quiet=False))
        Message.objects.filter(pk=deferred.pk).update(scheduled_for=None)
        services.send_now(deferred)
    assert fake_sms.outbox[0]["to"] == "+447700900123"

    response = client_for(org).post(
        "/webhooks/twilio/inbound",
        {"From": "+447700900123", "Body": "STOP"},
        format="multipart",
        HTTP_X_TWILIO_SIGNATURE="fake-signature",
    )
    assert response.status_code == 200
    assert SmsOptOut.objects.filter(phone="+447700900123").exists()
    with tenant_context(org):
        assert services.suppressed("sms", "+447700900123")

    class NoCredit:
        def consume(self, segments, *, country):
            return False

    channels.set_credit_meter(NoCredit())
    SmsOptOut.objects.all().delete()
    later = lesson_at(org, family, now() + timedelta(days=5))
    with tenant_context(org):
        delivery.cancel_lesson(later, cancelled_by="admin")
        services.notify("lesson_cancelled", later, key="x", immediate=True)
        failed = Message.objects.get(dedupe_key__startswith="lesson_cancelled:x:contact")
    assert (failed.status, failed.error) == ("failed", "No SMS credits left.")


def test_delivery_webhooks_update_status_and_suppress_bounces(org, family, settings):
    settings.POSTMARK_WEBHOOK_TOKEN = "hook-token"
    lesson = lesson_at(org, family, now() + timedelta(days=3))
    with tenant_context(org):
        delivery.cancel_lesson(lesson, cancelled_by="admin")
    run(org, "lesson.cancelled", handlers.lesson_cancelled)
    email = next(m for m in messages(org) if m.to == "priya@example.com")
    web = client_for(org)

    def post(record, **extra):
        body = {"RecordType": record, "Metadata": {"message-id": str(email.pk), "org": str(org.pk)},
                **extra}  # fmt: skip
        return web.post(
            "/webhooks/postmark?token=hook-token", json.dumps(body), content_type="application/json"
        )

    assert web.post("/webhooks/postmark", "{}", content_type="application/json").status_code == 403
    assert post("Open").status_code == 200
    assert post("Delivery").status_code == 200  # late, out of order: stays "opened"
    with tenant_context(org):
        email.refresh_from_db()
        assert email.status == "opened"
    post("Bounce", Type="HardBounce")
    with tenant_context(org):
        email.refresh_from_db()
        assert email.status == "bounced"
        assert Suppression.objects.filter(address="priya@example.com").exists()
        assert [e.type for e in email.events.all()][-1] == "bounced"


def test_twilio_status_callback(org, family):
    with tenant_context(org):
        services.update_setting("lesson_cancelled", enabled=True, channels=["sms"])
        settings_service.update_settings("comms", quiet_window(now_is_quiet=False))
    lesson = lesson_at(org, family, now() + timedelta(days=3))
    with tenant_context(org):
        delivery.cancel_lesson(lesson, cancelled_by="admin")
        services.notify("lesson_cancelled", lesson, key="t", immediate=True)
        sms = Message.objects.get(channel="sms")
    response = client_for(org).post(
        f"/webhooks/twilio/status?org={org.pk}&message={sms.pk}",
        {"MessageStatus": "delivered"},
        format="multipart",
        HTTP_X_TWILIO_SIGNATURE="fake-signature",
    )
    assert response.status_code == 204
    with tenant_context(org):
        sms.refresh_from_db()
    assert sms.status == "delivered"
    bad = client_for(org).post(
        f"/webhooks/twilio/status?org={org.pk}&message={sms.pk}",
        {"MessageStatus": "failed"},
        format="multipart",
        HTTP_X_TWILIO_SIGNATURE="nope",
    )
    assert bad.status_code == 403


# --- reminders (T06) ----------------------------------------------------------------------------


def test_reminders_at_each_offset_once(org, family):
    tomorrow = lesson_at(org, family, now() + timedelta(hours=23, minutes=40))
    soon = lesson_at(org, family, now() + timedelta(hours=1, minutes=50))
    later = lesson_at(org, family, now() + timedelta(days=3))
    send_lesson_reminders(organisation_id=str(org.pk))
    send_lesson_reminders(organisation_id=str(org.pk))  # the next beat: nothing new
    reminders = messages(org, type_key="lesson_reminder", channel="email")
    lessons = {(m.related_id, m.recipient_type) for m in reminders}
    assert lessons == {
        (str(tomorrow.pk), "contact"),
        (str(tomorrow.pk), "tutor"),
        (str(soon.pk), "contact"),
        (str(soon.pk), "tutor"),
    }
    assert str(later.pk) not in {m.related_id for m in reminders}
    assert len(messages(org, type_key="lesson_reminder", channel="sms")) == 2  # contacts, tutors


# --- preferences, unsubscribe, in-app, log (T07..T09) -------------------------------------------


def test_unsubscribe_link_turns_off_that_category(org, family):
    lesson = lesson_at(org, family, now() + timedelta(days=3))
    with tenant_context(org):
        delivery.cancel_lesson(lesson, cancelled_by="admin")
    run(org, "lesson.cancelled", handlers.lesson_cancelled)
    email = next(m for m in mail.outbox if m.to == ["priya@example.com"])
    url = email.extra_headers["List-Unsubscribe"].strip("<>")
    token = url.rsplit("/", 1)[1]
    public = client_for(org)
    assert public.get(f"/api/v1/unsubscribe/{token}").json() == {
        "category": "scheduling",
        "done": False,
    }
    assert public.post(f"/api/v1/unsubscribe/{token}").json()["done"] is True
    with tenant_context(org):
        assert services.allowed_channels(
            services.registry.Recipient("contact", str(family["contact"].pk), "", ""),
            "scheduling",
        ) == {"sms", "in_app"}
    assert public.get("/api/v1/unsubscribe/forged").status_code == 404


def test_in_app_bell_and_staff_alerts(org, family, admin):
    api, _user = admin
    with tenant_context(org):
        handlers._alert(
            "staff_dispute",
            "A card payment was disputed",
            "Respond in Stripe",
            "/billing",
            key="d1",
        )
    assert api.get("/api/v1/notifications/unread-count").json() == {"unread": 1}
    rows = api.get("/api/v1/notifications").json()["results"]
    assert rows[0]["title"] == "A card payment was disputed"
    assert rows[0]["link"] == "/billing"
    assert api.post("/api/v1/notifications/read", {}, format="json").json() == {"unread": 0}
    tutor_api = client_for(org, family["tutor_user"])
    assert tutor_api.get("/api/v1/notifications").json()["results"] == []  # not for tutors


def test_message_log_and_timeline(org, family, admin):
    api, _user = admin
    lesson = lesson_at(org, family, now() + timedelta(days=3))
    with tenant_context(org):
        delivery.cancel_lesson(lesson, cancelled_by="admin")
    run(org, "lesson.cancelled", handlers.lesson_cancelled)
    log = api.get(
        f"/api/v1/messages?target_type=people.client&target_id={family['client'].pk}"
    ).json()["results"]
    assert [m["to"] for m in log] == ["priya@example.com"]
    assert log[0]["events"][0]["type"] == "sent"
    timeline = api.get(
        f"/api/v1/timeline?target_type=people.client&target_id={family['client'].pk}"
    ).json()
    assert any(item["kind"] == "message" for item in timeline)


def test_settings_used_by_staff_preferences_api(org, family, admin):
    api, _user = admin
    body = {
        "person_type": "contact",
        "person_id": str(family["contact"].pk),
        "preferences": [{"category": "reports", "channels": ["email"]}],
    }
    assert api.put("/api/v1/communication-preferences", body, format="json").status_code == 200
    got = api.get(
        f"/api/v1/communication-preferences?person_type=contact&person_id={family['contact'].pk}"
    ).json()
    assert got["preferences"] == [{"category": "reports", "channels": ["email"]}]


def test_platform_base_url_is_configured():
    assert settings.PLATFORM_BASE_URL


class TestMessageIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/messages"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return Message.objects.create(
                type_key="lesson_booked", channel="email", recipient_type="contact",
                recipient_id="1", to="a@example.com", body="x", dedupe_key=str(organisation.pk),
            )  # fmt: skip
