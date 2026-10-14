"""E13-T10: segments, broadcasts (drafts, audience preview, consent, scheduling, batches,
tracking and statistics) and their API."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.core import mail
from django.db import transaction

from tutortrack.comms import broadcasts, channels, segments, services
from tutortrack.comms.models import Broadcast, BroadcastRecipient, Message
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.crm.tests.factories import SavedViewFactory, TagFactory
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)
from tutortrack.privacy import services as privacy
from tutortrack.tenancy import settings_service

from .factories import BroadcastFactory, SegmentFactory, WhatsAppTemplateFactory
from .test_comms import quiet_window

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fake_sms():
    channels.sms_provider.cache_clear()
    yield channels.sms_provider()
    channels.sms_provider.cache_clear()


@pytest.fixture
def staff(org):
    membership = MembershipFactory(organisation=org, role="admin")
    return client_for(org, membership.user)


def family(org, name, email, *, status="active", mobile="", student_status="active"):
    client = ClientFactory(organisation=org, display_name=name, status=status)
    contact = ContactFactory(
        organisation=org,
        client=client,
        first_name=name.split()[0],
        last_name=name.split()[-1],
        email=email,
        mobile=mobile,
        is_primary=True,
    )
    StudentFactory(organisation=org, client=client, status=student_status)
    return client, contact


def tag(org, client, label="VIP"):
    from tutortrack.crm.models import TaggedItem

    found = TagFactory(organisation=org, name=label)
    with tenant_context(org):
        TaggedItem.objects.create(tag=found, target_type="people.client", target_id=str(client.pk))
    return found


def consent(org, contact, key="marketing-email", granted=True):
    with tenant_context(org):
        privacy.ensure_default_types()
        privacy.record_consent(
            subject_type="people.contact",
            subject_id=str(contact.pk),
            key=key,
            granted=granted,
            method="staff",
        )


def names(members):
    return sorted(m.name for m in members)


# --- segments (FR-13-6) -------------------------------------------------------------------------


def test_segments_filter_contacts_by_status_tags_students_and_primary(org):
    patel, _priya = family(org, "Priya Patel", "priya@example.com")
    ContactFactory(organisation=org, client=patel, first_name="Raj", last_name="Patel",
                   email="raj@example.com")  # fmt: skip
    _smith, _sam = family(org, "Sam Smith", "sam@example.com", status="dormant")
    _jones, _jo = family(org, "Jo Jones", "jo@example.com", student_status="finished")
    vip = tag(org, patel)
    with tenant_context(org):
        active = segments.resolve("contacts", {"client_statuses": ["active"]})
        assert len(active) == 3  # the Patels (two contacts) and the Joneses
        primary = segments.resolve(
            "contacts", {"client_statuses": ["active"], "contacts": "primary"}
        )
        assert names(primary) == ["Jo Jones", "Priya Patel"]
        tagged = segments.resolve("contacts", {"tags": [str(vip.pk)]})
        assert {m.email for m in tagged} == {"priya@example.com", "raj@example.com"}
        learning = segments.resolve(
            "contacts", {"student_statuses": ["active"], "contacts": "primary"}
        )
        assert names(learning) == ["Priya Patel", "Sam Smith"]


def test_segments_use_saved_views_and_pipeline_stages(org):
    from tutortrack.leads import services as leads

    _patel, _priya = family(org, "Priya Patel", "priya@example.com")
    _smith, _sam = family(org, "Sam Smith", "sam@example.com", status="dormant")
    view = SavedViewFactory(organisation=org, filters={"status": "dormant"}, shared=True)
    with tenant_context(org), transaction.atomic():
        enquiry = leads.create_enquiry(
            contact={"first_name": "Ella", "last_name": "Lead", "email": "ella@example.com"}
        )
        dormant = segments.resolve("contacts", {"saved_view": str(view.pk)})
        assert [m.email for m in dormant] == ["sam@example.com"]
        staged = segments.resolve("contacts", {"pipeline_stage": str(enquiry.stage_id)})
        assert [m.email for m in staged] == ["ella@example.com"]


def test_tutor_segments_and_validation(org):
    TutorProfileFactory(
        organisation=org, status="active", first_name="Nia", email="nia@example.com"
    )
    TutorProfileFactory(
        organisation=org, status="inactive", first_name="Old", email="old@example.com"
    )
    with tenant_context(org):
        rows = segments.resolve("tutors", {"tutor_statuses": ["active"]})
        assert [m.email for m in rows] == ["nia@example.com"]
        with pytest.raises(BusinessRuleViolation):
            segments.clean("tutors", {"client_statuses": ["active"]})  # contacts only
        with pytest.raises(BusinessRuleViolation):
            segments.clean("contacts", {"nonsense": True})


# --- who it reaches -----------------------------------------------------------------------------


def test_marketing_needs_consent_and_respects_opt_outs_and_suppressions(org):
    _a, priya = family(org, "Priya Patel", "priya@example.com")
    _b, sam = family(org, "Sam Smith", "sam@example.com")
    _c, jo = family(org, "Jo Jones", "jo@example.com")
    _d, _kim = family(org, "Kim Kaur", "")
    _e, ann = family(org, "Ann Ahmed", "PRIYA@example.com")  # same address as Priya
    _f, lee = family(org, "Lee Lowe", "lee@example.com")
    for person in (priya, sam, jo, ann, lee):
        consent(org, person)
    consent(org, jo, granted=False)  # withdrew
    with tenant_context(org):
        services.set_preference("contact", str(sam.pk), "marketing", ["sms"])  # unsubscribed
        services.suppress("email", "lee@example.com", "bounced")
        preview = broadcasts.preview_recipients(
            audience="contacts", definition={}, channel="email", purpose="marketing"
        )
        operational = broadcasts.preview_recipients(
            audience="contacts", definition={}, channel="email", purpose="operational"
        )
    assert preview["skipped"] == {
        "duplicate": 1, "no_address": 1, "no_consent": 1, "opted_out": 1, "suppressed": 1,
    }  # fmt: skip
    assert preview["sendable"] == 1
    assert preview["sample"][0]["address"] == "priya@example.com"
    # Service announcements don't need marketing consent.
    assert operational["sendable"] == 3  # Priya (Ann shares her address), Sam and Jo
    assert "no_consent" not in operational["skipped"]


def test_without_a_consent_type_the_marketing_flag_counts(org):
    _a, priya = family(org, "Priya Patel", "priya@example.com")
    _b, _sam = family(org, "Sam Smith", "sam@example.com")
    with tenant_context(org):
        type(priya).objects.filter(pk=priya.pk).update(receives_marketing=True)
        result = broadcasts.preview_recipients(
            audience="contacts", definition={}, channel="email", purpose="marketing"
        )
    assert result["sendable"] == 1
    assert result["skipped"] == {"no_consent": 1}


def test_whatsapp_broadcasts_need_opt_in_and_an_approved_template(org):
    _a, priya = family(org, "Priya Patel", "priya@example.com", mobile="07700 900123")
    _b, _sam = family(org, "Sam Smith", "sam@example.com", mobile="07700 900456")
    template = WhatsAppTemplateFactory(organisation=org, status="pending")
    with tenant_context(org):
        services.set_preference("contact", str(priya.pk), "account", ["email", "whatsapp"])
        result = broadcasts.preview_recipients(
            audience="contacts", definition={}, channel="whatsapp", purpose="operational"
        )
        assert result["sendable"] == 1
        assert result["skipped"] == {"no_opt_in": 1}
        draft = broadcasts.create_broadcast(
            name="Closure", channel="whatsapp", whatsapp_template=template, body=""
        )
        with pytest.raises(BusinessRuleViolation):
            broadcasts.schedule(draft, scheduled_for=None)  # template not approved yet


# --- drafts, scheduling and sending -------------------------------------------------------------


def _send_all(org, broadcast, capture):
    """What the workflow does, with the Celery sends run after each batch commits."""
    with tenant_context(org):
        broadcasts.resolve_recipients(str(broadcast.pk))
        batch = 1
        while True:
            with capture(execute=True):
                left = broadcasts.send_batch(str(broadcast.pk), batch)["remaining"]
            if not left:
                break
            batch += 1
        return broadcasts.finish(str(broadcast.pk))


def test_a_broadcast_sends_in_batches_and_tracks_delivery(
    org, settings, django_capture_on_commit_callbacks
):
    for i in range(5):
        family(org, f"Parent{i} Family{i}", f"parent{i}@example.com")
    settings.POSTMARK_WEBHOOK_TOKEN = "tok"
    with tenant_context(org):
        settings_service.update_settings("comms", {"comms.broadcast_batch_size": 2})
        draft = broadcasts.create_broadcast(
            name="Half term", subject="Half term", channel="email",
            body="Hello {{ recipient.first_name }}, lessons pause next week.",
        )  # fmt: skip
        with transaction.atomic():
            broadcasts.schedule(draft, scheduled_for=None)
        assert OutboxEvent.objects.filter(event_type="broadcast.scheduled").count() == 1
        assert broadcasts.resolve_recipients(str(draft.pk)) == 5
        with django_capture_on_commit_callbacks(execute=True):
            first = broadcasts.send_batch(str(draft.pk), 1)
    assert first == {"queued": 2, "remaining": 3, "status": 1}
    assert _send_all(org, draft, django_capture_on_commit_callbacks) == "sent"
    assert len(mail.outbox) == 5
    assert mail.outbox[0].body.startswith("Hello Parent0, lessons pause next week.")
    with tenant_context(org):
        draft.refresh_from_db()
        assert draft.status == "sent"
        assert draft.stats["queued"] == 5
        messages = list(Message.objects.filter(related_id=str(draft.pk)))
        assert {m.type_key for m in messages} == {"broadcast_operational"}
        assert len(BroadcastRecipient.objects.filter(batch=1)) == 4  # numbered again by _send_all
    # Postmark tracks opens and clicks on each message.
    hook = client_for(org)
    for message, record in ((messages[0], "Open"), (messages[1], "Click")):
        hook.post(
            "/webhooks/postmark?token=tok",
            json.dumps({"RecordType": record, "Metadata": {
                "org": str(org.pk), "message-id": str(message.pk)}}),
            content_type="application/json",
        )  # fmt: skip
    with tenant_context(org):
        stats = broadcasts.stats(Broadcast.objects.get(pk=draft.pk))
    assert (stats["sent"], stats["opened"], stats["clicked"]) == (5, 2, 1)


def test_marketing_email_has_unsubscribe_and_counts_it(org, django_capture_on_commit_callbacks):
    _a, priya = family(org, "Priya Patel", "priya@example.com")
    consent(org, priya)
    with tenant_context(org):
        draft = broadcasts.create_broadcast(
            name="Offer", subject="Summer school", body="Book now!", purpose="marketing"
        )
        with transaction.atomic():
            broadcasts.schedule(draft, scheduled_for=None)
    _send_all(org, draft, django_capture_on_commit_callbacks)
    email = mail.outbox[-1]
    assert "List-Unsubscribe" in email.extra_headers
    token = email.extra_headers["List-Unsubscribe"].split("/unsubscribe/")[1].rstrip(">")
    assert client_for(org).post(f"/api/v1/unsubscribe/{token}").json()["done"] is True
    with tenant_context(org):
        assert broadcasts.stats(Broadcast.objects.get(pk=draft.pk))["unsubscribed"] == 1
        again = broadcasts.preview_recipients(
            audience="contacts", definition={}, channel="email", purpose="marketing"
        )
    assert again["skipped"] == {"opted_out": 1}


def test_marketing_texts_say_how_to_stop(org, fake_sms, django_capture_on_commit_callbacks):
    _a, priya = family(org, "Priya Patel", "priya@example.com", mobile="07700 900123")
    consent(org, priya, key="marketing-sms")
    with tenant_context(org):
        settings_service.update_settings("comms", quiet_window(now_is_quiet=False))
        draft = broadcasts.create_broadcast(
            name="Offer", channel="sms", body="Summer school is open.", purpose="marketing"
        )
        broadcasts.schedule(draft, scheduled_for=None)
    _send_all(org, draft, django_capture_on_commit_callbacks)
    assert fake_sms.outbox[-1]["body"] == "Summer school is open.\nReply STOP to opt out"


def test_pause_resume_and_cancel(org):
    family(org, "Priya Patel", "priya@example.com")
    with tenant_context(org):
        draft = broadcasts.create_broadcast(name="News", subject="News", body="Hi")
        with pytest.raises(BusinessRuleViolation):
            broadcasts.pause(draft)  # drafts aren't running
        broadcasts.schedule(draft, scheduled_for=now() + timedelta(days=1))
        assert broadcasts.pause(draft).status == "paused"
        assert broadcasts.resume(draft).status == "scheduled"
        with pytest.raises(BusinessRuleViolation):
            broadcasts.update_broadcast(draft, body="changed")  # only drafts change
        broadcasts.resolve_recipients(str(draft.pk))
        cancelled = broadcasts.cancel(draft)
        assert cancelled.status == "cancelled"
        assert set(cancelled.recipients.values_list("skip_reason", flat=True)) == {"cancelled"}
        assert broadcasts.send_batch(str(draft.pk), 1)["queued"] == 0
        assert broadcasts.finish(str(draft.pk)) == "cancelled"


def test_quiet_hours_hold_texts(org):
    with tenant_context(org):
        settings_service.update_settings("comms", quiet_window(now_is_quiet=True))
        texts = BroadcastFactory(organisation=org, channel="sms")
        emails = BroadcastFactory(organisation=org, channel="email")
        assert broadcasts.quiet_wait_seconds(str(texts.pk)) > 0
        assert broadcasts.quiet_wait_seconds(str(emails.pk)) == 0


# --- API ----------------------------------------------------------------------------------------


def test_broadcast_api_flow(org, staff, s3):
    from tutortrack.core.storage import services as storage

    family(org, "Priya Patel", "priya@example.com")
    segment = staff.post(
        "/api/v1/segments",
        {"name": "Active families", "audience": "contacts",
         "definition": {"client_statuses": ["active"], "contacts": "primary"}},
        format="json",
    )  # fmt: skip
    assert segment.status_code == 201, segment.json()
    preview = staff.post(
        "/api/v1/segments/preview",
        {"audience": "contacts", "definition": {"client_statuses": ["active"]}},
        format="json",
    )
    assert preview.json()["sendable"] == 1
    options = staff.get("/api/v1/segments/options").json()
    assert {"value": "active", "name": "Active"} in options["client_statuses"]
    with tenant_context(org):
        stored, _upload = storage.create_upload(
            filename="timetable.pdf", content_type="application/pdf", size_bytes=4
        )
    created = staff.post(
        "/api/v1/broadcasts",
        {"name": "Timetable", "subject": "New timetable", "body": "Hi {{ recipient.first_name }}",
         "segment": segment.json()["id"], "attachment_ids": [str(stored.pk)]},
        format="json",
    )  # fmt: skip
    assert created.status_code == 201, created.json()
    row = created.json()
    assert row["definition"] == {"client_statuses": ["active"], "contacts": "primary"}
    assert row["stats"]["recipients"] == 0
    pk = row["id"]
    rendered = staff.post(f"/api/v1/broadcasts/{pk}/preview").json()
    assert rendered["body"] == "Hi Priya"
    assert staff.post(f"/api/v1/broadcasts/{pk}/audience").json()["sendable"] == 1
    bad = staff.patch(f"/api/v1/broadcasts/{pk}", {"body": "{% if %}"}, format="json")
    assert bad.status_code == 422
    scheduled = staff.post(
        f"/api/v1/broadcasts/{pk}/schedule", {"scheduled_for": None}, format="json"
    )
    assert scheduled.json()["status"] == "scheduled"
    assert staff.post(f"/api/v1/broadcasts/{pk}/pause").json()["status"] == "paused"
    assert staff.post(f"/api/v1/broadcasts/{pk}/cancel").json()["status"] == "cancelled"
    assert staff.delete(f"/api/v1/broadcasts/{pk}").status_code == 422  # not a draft
    recipients = staff.get(f"/api/v1/broadcasts/{pk}/recipients")
    assert recipients.status_code == 200
    assert recipients.json()["results"] == []


def test_broadcast_permissions(org):
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    assert tutor.get("/api/v1/broadcasts").status_code == 403
    finance = client_for(org, MembershipFactory(organisation=org, role="finance").user)
    assert finance.post("/api/v1/segments", {}, format="json").status_code == 403
    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    assert coordinator.get("/api/v1/broadcasts").status_code == 200


class TestBroadcastIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/broadcasts"

    def make_object(self, organisation):
        return BroadcastFactory(organisation=organisation)


class TestSegmentIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/segments"

    def make_object(self, organisation):
        return SegmentFactory(organisation=organisation)


def test_send_failures_are_skipped_not_fatal(org):
    _a, priya = family(org, "Priya Patel", "priya@example.com")
    with tenant_context(org):
        draft = broadcasts.create_broadcast(name="News", subject="News", body="Hi")
        broadcasts.schedule(draft, scheduled_for=None)
        broadcasts.resolve_recipients(str(draft.pk))
        Broadcast.objects.filter(pk=draft.pk).update(body="{{ recipient.first_name|nope }}")
        result = broadcasts.send_batch(str(draft.pk), 1)
    assert result["queued"] == 0
    with tenant_context(org):
        row = BroadcastRecipient.objects.get(recipient_id=str(priya.pk))
    assert (row.status, row.skip_reason) == ("failed", "template")
