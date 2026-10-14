"""E13-T11: the conversations inbox (inbound email, texts and WhatsApp, staff replies,
notes, assignment, snooze, SLA, safeguarding flags, canned replies) and its API."""

from __future__ import annotations

import base64
import json
from datetime import timedelta

import pytest
from django.core import mail
from django.test import override_settings

from tutortrack.comms import channels, handlers, inbox, providers, selectors, senders
from tutortrack.comms.models import (
    InAppNotification,
    InboundRoute,
    Message,
    Thread,
    ThreadMessage,
)
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, TutorProfileFactory
from tutortrack.tenancy import settings_service

from .factories import CannedReplyFactory, PhoneNumberFactory, ThreadFactory
from .test_comms import run

pytestmark = pytest.mark.django_db
COMMS = {
    "REPLY_DOMAIN": "reply.tutortrack.test",
    "INBOUND_TOKEN": "inbound-secret",
    "POSTMARK_ACCOUNT_TOKEN": "",
    "WHATSAPP_WINDOW_HOURS": 24,
    "SMS_REPLY_ROUTE_DAYS": 30,
}


@pytest.fixture(autouse=True)
def fakes():
    channels.sms_provider.cache_clear()
    providers.whatsapp_provider.cache_clear()
    with override_settings(COMMS=COMMS):
        yield channels.sms_provider(), providers.whatsapp_provider()
    channels.sms_provider.cache_clear()
    providers.whatsapp_provider.cache_clear()


@pytest.fixture
def admin(org):
    membership = MembershipFactory(organisation=org, role="admin")
    return client_for(org, membership.user), membership.user


@pytest.fixture
def family(org):
    client = ClientFactory(organisation=org, display_name="The Patels")
    contact = ContactFactory(
        organisation=org,
        client=client,
        first_name="Priya",
        last_name="Patel",
        email="priya@example.com",
        mobile="07700 900123",
        is_primary=True,
    )
    return client, contact


def inbound_email(org, mailbox_hash, *, sender="priya@example.com", text="Hello!", **extra):
    payload = {
        "MailboxHash": mailbox_hash,
        "FromFull": {"Email": sender, "Name": "Priya Patel"},
        "Subject": "Thursday",
        "TextBody": text,
        "MessageID": extra.pop("message_id", "m-1"),
        **extra,
    }
    return client_for(org).post(
        "/webhooks/inbound/email?token=inbound-secret",
        json.dumps(payload),
        content_type="application/json",
    )


def inbound_text(
    org, *, sender="+447700900123", to="+447700900999", body="Running late", sid="SM1"
):
    return client_for(org).post(
        "/webhooks/twilio/inbound",
        {"From": sender, "To": to, "Body": body, "MessageSid": sid},
        format="multipart",
        HTTP_X_TWILIO_SIGNATURE="fake-signature",
    )


# --- inbound ------------------------------------------------------------------------------------


def test_email_to_the_inbox_address_opens_a_family_thread(org, family):
    client, contact = family
    assert inbound_email(org, org.slug).status_code == 200
    assert inbound_email(org, org.slug).status_code == 200  # Postmark retried: ignored
    with tenant_context(org):
        thread = Thread.objects.get()
        assert (thread.kind, thread.client_id, thread.channel) == ("client", client.pk, "email")
        entry = thread.messages.get()
        assert (entry.author_type, entry.author_id) == ("contact", str(contact.pk))
        assert thread.awaiting_reply_since is not None
        assert thread.participants.filter(email="priya@example.com").exists()
    # The staff alert goes to whoever assigns conversations.
    admin_member = MembershipFactory(organisation=org, role="admin")
    run(org, "message.received", handlers.inbox_message_received)
    with tenant_context(org):
        alert = InAppNotification.objects.get(user=admin_member.user)
    assert alert.title == "New message from Priya Patel"


def test_unknown_senders_and_bad_requests(org):
    assert inbound_email(org, org.slug, sender="stranger@example.com").status_code == 200
    with tenant_context(org):
        thread = Thread.objects.get()
        assert (thread.kind, thread.contact_email) == ("other", "stranger@example.com")
    bad = client_for(org).post(
        "/webhooks/inbound/email?token=wrong", "{}", content_type="application/json"
    )
    assert bad.status_code == 403
    # A forged thread address is dropped, not delivered.
    forged = f"{org.slug}.{'0' * 32}.badsignature"
    assert inbound_email(org, forged, message_id="m-2").status_code == 200
    with tenant_context(org):
        assert ThreadMessage.objects.count() == 1


def test_replies_by_email_carry_the_thread_address(org, family, admin):
    staff, _user = admin
    inbound_email(org, org.slug)
    with tenant_context(org):
        thread = Thread.objects.get()
    reply = staff.post(
        f"/api/v1/threads/{thread.pk}/messages",
        {"body": "Yes, 5pm is fine."},
        format="json",
    )
    assert reply.status_code == 201, reply.json()
    assert reply.json()["channel"] == "email"
    # The reply email (sent on commit) has the thread's signed reply address.
    with tenant_context(org):
        message = Message.objects.get(type_key="inbox_reply")
        assert message.thread_id == thread.pk
        address = senders.thread_reply_address(thread)
        from tutortrack.comms import services

        services.send_now(message)
        thread.refresh_from_db()
        assert thread.awaiting_reply_since is None  # answered: the SLA timer stops
    assert mail.outbox[-1].reply_to == [address]
    assert mail.outbox[-1].subject == "Re: Thursday"
    # Their answer to that address lands in the same thread.
    mailbox = address.split("+", 1)[1].split("@")[0]
    inbound_email(org, mailbox, text="Thanks!", message_id="m-3")
    with tenant_context(org):
        assert thread.messages.count() == 3


def test_texts_route_by_number_and_reply_route(org, family, fakes, admin):
    _client, contact = family
    with tenant_context(org):
        number = PhoneNumberFactory(organisation=org, number="+447700900999")
        InboundRoute.objects.create(
            channel="sms", kind="number", address=number.number, organisation_id=org.pk
        )
    assert inbound_text(org).status_code == 200
    with tenant_context(org):
        thread = Thread.objects.get()
        assert thread.channel == "sms"
        assert thread.messages.get().author_id == str(contact.pk)
    # STOP still opts out and isn't a conversation message.
    inbound_text(org, body="STOP", sid="SM2")
    with tenant_context(org):
        assert thread.messages.count() == 1
    # A reply to the shared sender reaches the organisation that last texted them.
    inbound_text(org, sender="+447700900555", to="+440000000000", body="Who is this?", sid="SM3")
    with tenant_context(org):
        assert Thread.objects.count() == 1  # no route yet: dropped
        senders.remember_reply_route("sms", "+447700900555")
    inbound_text(org, sender="+447700900555", to="+440000000000", body="Who is this?", sid="SM4")
    with tenant_context(org):
        assert Thread.objects.filter(kind="other", contact_phone="+447700900555").exists()


def test_staff_text_replies_use_the_organisations_number(org, family, fakes, admin):
    fake_sms, _wa = fakes
    staff, _user = admin
    with tenant_context(org):
        senders.add_phone_number(channel="sms", number="+447700900999")
    inbound_text(org)
    with tenant_context(org):
        thread = Thread.objects.get()
    response = staff.post(
        f"/api/v1/threads/{thread.pk}/messages", {"body": "On our way"}, format="json"
    )
    assert response.status_code == 201
    with tenant_context(org):
        from tutortrack.comms import services

        services.send_now(Message.objects.get(type_key="inbox_reply"))
    assert fake_sms.outbox[-1]["from"] == "+447700900999"
    assert fake_sms.outbox[-1]["to"] == "+447700900123"


def test_whatsapp_free_replies_only_within_24_hours(org, family, fakes, admin):
    _sms, fake_wa = fakes
    _staff, user = admin
    with tenant_context(org):
        InboundRoute.objects.create(
            channel="whatsapp", kind="number", address="+447700900888", organisation_id=org.pk
        )
    inbound_text(org, sender="whatsapp:+447700900123", to="whatsapp:+447700900888", sid="WA1")
    with tenant_context(org):
        thread = Thread.objects.get()
        assert thread.channel == "whatsapp"
        entry = inbox.reply(thread, user, body="Hi Priya")
        from tutortrack.comms import services

        services.send_now(entry.message)
        assert fake_wa.outbox[-1]["to"] == "whatsapp:+447700900123"
        assert fake_wa.outbox[-1]["body"] == "Hi Priya"
        ThreadMessage.objects.filter(channel="whatsapp", direction="inbound").update(
            created_at=now() - timedelta(hours=30)
        )
        with pytest.raises(BusinessRuleViolation):
            inbox.reply(thread, user, body="Still there?")


# --- the team inbox -----------------------------------------------------------------------------


def test_notes_assignment_snooze_close_and_counts(org, family, admin):
    staff, user = admin
    inbound_email(org, org.slug)
    with tenant_context(org):
        thread = Thread.objects.get()
    note = staff.post(f"/api/v1/threads/{thread.pk}/notes", {"body": "VIP family"}, format="json")
    assert note.json()["direction"] == "internal"
    assigned = staff.post(
        f"/api/v1/threads/{thread.pk}/assign", {"assignee": str(user.pk)}, format="json"
    )
    assert assigned.json()["assignee_name"]
    counts = staff.get("/api/v1/threads/counts").json()
    assert (counts["open"], counts["mine"], counts["unassigned"]) == (1, 1, 0)
    until = (now() + timedelta(hours=3)).isoformat()
    snoozed = staff.post(f"/api/v1/threads/{thread.pk}/snooze", {"until": until}, format="json")
    assert snoozed.json()["status"] == "snoozed"
    assert staff.get("/api/v1/threads?box=snoozed").json()["results"][0]["id"] == str(thread.pk)
    # The snooze ends by itself (no sweeper): read-time status.
    with tenant_context(org):
        Thread.objects.filter(pk=thread.pk).update(snoozed_until=now() - timedelta(minutes=1))
    rows = staff.get("/api/v1/threads?box=open").json()["results"]
    assert rows[0]["status"] == "open"
    closed = staff.post(f"/api/v1/threads/{thread.pk}/close")
    assert closed.json()["status"] == "closed"
    assert staff.get("/api/v1/threads?box=open").json()["results"] == []
    # A new message from them reopens it.
    inbound_email(org, org.slug, text="One more thing", message_id="m-9")
    with tenant_context(org):
        thread.refresh_from_db()
        assert thread.status == "open"
    messages = staff.get(f"/api/v1/threads/{thread.pk}/messages").json()
    assert [m["direction"] for m in messages] == ["inbound", "internal", "inbound"]
    assert staff.get(f"/api/v1/threads/{thread.pk}").json()["unread"] == 0


def test_sla_timer(org, family, admin):
    staff, _user = admin
    inbound_email(org, org.slug)
    with tenant_context(org):
        settings_service.update_settings("comms", {"comms.inbox_sla_hours": 2})
        Thread.objects.update(awaiting_reply_since=now() - timedelta(hours=3))
    row = staff.get("/api/v1/threads").json()["results"][0]
    assert row["sla_breached"] is True
    assert row["sla_due_at"]


def test_staff_start_a_portal_conversation(org, family, admin):
    staff, _user = admin
    client, _contact = family
    created = staff.post(
        "/api/v1/threads",
        {"kind": "client", "client": str(client.pk), "subject": "Next term", "body": "Hi!"},
        format="json",
    )
    assert created.status_code == 201, created.json()
    detail = created.json()
    assert detail["party"] == "The Patels"
    assert [p["role"] for p in detail["participants"]] == ["family"]
    with tenant_context(org):
        # The family hears about it by email ("you have a new message").
        assert Message.objects.filter(type_key="conversation_message_family").exists()


def test_safeguarding_flags_and_blocking(org, family):
    client, contact = family
    tutor = TutorProfileFactory(organisation=org, status="active")
    author = inbox.Author("contact", str(contact.pk), contact.full_name)
    with tenant_context(org):
        thread = inbox.start_from_portal(
            author, kind="tutor_family", body="Hello", client=client, tutor=tutor
        )
        entry = inbox.post_from_portal(thread, author, body="Text me on 07700 900123, damn it")
        assert entry.flags == ["contact_details"]
        thread.refresh_from_db()
        assert thread.flagged is True
        settings_service.update_settings("comms", {"comms.block_contact_sharing": True})
        with pytest.raises(BusinessRuleViolation):
            inbox.post_from_portal(thread, author, body="email me at priya@example.com")
        assert inbox.detect_flags("what the fuck") == ["profanity"]


def test_tutors_see_only_their_conversations(org, family):
    client, contact = family
    member = MembershipFactory(organisation=org, role="tutor")
    tutor = TutorProfileFactory(organisation=org, status="active", membership=member)
    other = TutorProfileFactory(organisation=org, status="active")
    author = inbox.Author("contact", str(contact.pk), contact.full_name)
    with tenant_context(org):
        mine = inbox.start_from_portal(
            author, kind="tutor_family", body="Hi", client=client, tutor=tutor
        )
        inbox.start_from_portal(author, kind="tutor_family", body="Hi", client=client, tutor=other)
    api = client_for(org, member.user)
    rows = api.get("/api/v1/threads").json()["results"]
    assert [r["id"] for r in rows] == [str(mine.pk)]
    assert api.post(f"/api/v1/threads/{mine.pk}/close").status_code == 403  # can't manage


def test_canned_replies(org, admin):
    staff, _user = admin
    created = staff.post(
        "/api/v1/canned-replies",
        {"title": "Thanks", "body": "Thanks, we'll call you."},
        format="json",
    )
    assert created.status_code == 201
    pk = created.json()["id"]
    updated = staff.patch(f"/api/v1/canned-replies/{pk}", {"body": "Thank you!"}, format="json")
    assert updated.json()["body"] == "Thank you!"
    duplicate = staff.post(
        "/api/v1/canned-replies", {"title": "Thanks", "body": "Again"}, format="json"
    )
    assert duplicate.status_code == 422
    assert staff.delete(f"/api/v1/canned-replies/{pk}").status_code == 204


def test_transcript_and_digest_for_e31(org, family):
    inbound_email(org, org.slug)
    with tenant_context(org):
        thread = Thread.objects.get()
        digest = selectors.thread_digest(thread)
    assert digest.party == "The Patels"
    assert [line.body for line in digest.lines] == ["Hello!"]
    assert digest.status == "open"


def test_inbound_email_attachments_are_stored_and_scanned(org, family, s3):
    content = base64.b64encode(b"%PDF-1.4 hello").decode()
    inbound_email(
        org,
        org.slug,
        Attachments=[{"Name": "note.pdf", "Content": content, "ContentType": "application/pdf"}],
    )
    with tenant_context(org):
        entry = ThreadMessage.objects.get()
    assert [a["filename"] for a in entry.attachments] == ["note.pdf"]


class TestThreadIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/threads"

    def make_object(self, organisation):
        return ThreadFactory(organisation=organisation)


class TestCannedReplyIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/canned-replies"

    def make_object(self, organisation):
        return CannedReplyFactory(organisation=organisation)
