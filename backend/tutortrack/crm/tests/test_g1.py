"""Gap batch G1: timeline lessons/invoices/payments (FR-05-10), search over jobs and
invoices (FR-05-11), bulk send message / invite to portal (FR-05-12) and @mention
notifications (FR-05-7)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.test import TestCase

from tutortrack.billing import services as billing
from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.comms.models import InAppNotification, Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events import EventEnvelope
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.crm import handlers
from tutortrack.crm import services as crm
from tutortrack.crm.models import BulkJob
from tutortrack.delivery import services as delivery
from tutortrack.identity.models import Invitation
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.jobs import services as jobs
from tutortrack.payments import services as payments
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)
from tutortrack.privacy import services as privacy
from tutortrack.scheduling import services as scheduling

pytestmark = pytest.mark.django_db
LONDON = ZoneInfo("Europe/London")


def api_as(org, role):
    return client_for(org, MembershipFactory(organisation=org, role=role).user)


@pytest.fixture
def family(org):
    client = ClientFactory(organisation=org, display_name="The Patels")
    contact = ContactFactory(
        organisation=org,
        client=client,
        email="priya@example.com",
        first_name="Priya",
        is_primary=True,
    )
    with tenant_context(org):
        client.primary_contact = client.billing_contact = contact
        client.save()
    student = StudentFactory(organisation=org, client=client, first_name="Arjun")
    tutor = TutorProfileFactory(organisation=org, status="active", first_name="Nia")
    service = ServiceFactory(organisation=org, name="Maths 1:1")
    return {
        "client": client,
        "contact": contact,
        "student": student,
        "tutor": tutor,
        "service": service,
    }


def billed(org, family):
    day = now().astimezone(LONDON).date() - timedelta(days=1)
    start = datetime.combine(day, time(10), tzinfo=LONDON)
    with tenant_context(org):
        job = jobs.create_job(
            client=family["client"],
            service=family["service"],
            students=[{"student": family["student"]}],
            tutors=[{"tutor": family["tutor"]}],
            status="active",
        )
        lesson = scheduling.create_lesson(
            start=start,
            end=start + timedelta(hours=1),
            service=family["service"],
            job=job,
            attendees=[{"student": family["student"]}],
            tutors=[{"tutor": family["tutor"]}],
            timezone="Europe/London",
            override_conflicts=True,
            notify=False,
        ).lesson
        delivery.complete_lesson(lesson)
        billing.sync_lesson_charges(lesson.pk)
        invoice = billing.issue_invoice(billing.create_draft(family["client"]), send=False)
        payment = payments.record_manual_payment(
            client=family["client"], amount=Money(Decimal("5.00"), invoice.currency), method="cash"
        )
    return job, lesson, invoice, payment


# --- timeline (FR-05-10)


def test_timeline_includes_lessons_invoices_and_payments(org, family):
    _job, lesson, invoice, payment = billed(org, family)
    owner = api_as(org, "owner")
    items = owner.get(
        "/api/v1/timeline", {"target_type": "people.client", "target_id": family["client"].pk}
    ).json()
    kinds = {(i["kind"], i["id"]) for i in items}
    assert ("lesson", str(lesson.pk)) in kinds
    assert ("invoice", str(invoice.pk)) in kinds
    assert ("payment", str(payment.pk)) in kinds
    student = owner.get(
        "/api/v1/timeline", {"target_type": "people.student", "target_id": family["student"].pk}
    ).json()
    assert ("lesson", str(lesson.pk)) in {(i["kind"], i["id"]) for i in student}
    contact = owner.get(
        "/api/v1/timeline",
        {"target_type": "people.contact", "target_id": family["contact"].pk, "kinds": "invoice"},
    ).json()
    assert [i["id"] for i in contact] == [str(invoice.pk)]
    # The coordinator sees lessons and invoices but not payments (no payments.payment.view).
    coordinator = (
        api_as(org, "coordinator")
        .get("/api/v1/timeline", {"target_type": "people.client", "target_id": family["client"].pk})
        .json()
    )
    assert "payment" not in {i["kind"] for i in coordinator}
    assert "lesson" in {i["kind"] for i in coordinator}


# --- search (FR-05-11)


def test_search_finds_jobs_and_invoices_within_permissions(org, other_org, family):
    job, _lesson, invoice, _payment = billed(org, family)
    owner = api_as(org, "owner")
    hits = owner.get("/api/v1/search", {"q": job.reference}).json()
    assert ("job", str(job.pk)) in {(h["type"], h["id"]) for h in hits}
    hits = owner.get("/api/v1/search", {"q": invoice.number}).json()
    invoice_hit = next(h for h in hits if h["type"] == "invoice")
    assert (invoice_hit["id"], invoice_hit["client_id"]) == (
        str(invoice.pk),
        str(family["client"].pk),
    )
    finance = api_as(org, "finance").get("/api/v1/search", {"q": job.reference}).json()
    assert "job" not in {h["type"] for h in finance}  # finance can't see jobs
    tutor = api_as(org, "tutor").get("/api/v1/search", {"q": invoice.number}).json()
    assert "invoice" not in {h["type"] for h in tutor}
    elsewhere = client_for(other_org, MembershipFactory(organisation=other_org, role="owner").user)
    assert elsewhere.get("/api/v1/search", {"q": invoice.number}).json() == []


# --- bulk actions (FR-05-12)


def bulk(api, entity, action, ids, params, capture):
    with capture(execute=True):
        return api.post(
            f"/api/v1/bulk/{entity}/{action}",
            {"target_ids": [str(i) for i in ids], "params": params},
            format="json",
        )


def test_bulk_send_service_message_to_families(org, family, django_capture_on_commit_callbacks):
    other = ClientFactory(organisation=org)  # no contact: reported, not sent
    message = {
        "channel": "email",
        "purpose": "service",
        "subject": "Half term",
        "body": "Hello {{ recipient.first_name }}",
    }
    owner = api_as(org, "owner")
    response = bulk(
        owner,
        "client",
        "send_message",
        [family["client"].pk, other.pk],
        message,
        django_capture_on_commit_callbacks,
    )
    assert response.status_code == 202, response.json()
    job = owner.get(f"/api/v1/bulk-jobs/{response.json()['id']}").json()
    assert (job["succeeded"], list(job["errors"])) == (1, [str(other.pk)])
    with tenant_context(org):
        sent = Message.objects.get(recipient_id=str(family["contact"].pk))
    assert (sent.to, sent.body, sent.target_id) == (
        "priya@example.com",
        "Hello Priya",
        str(family["client"].pk),
    )


def test_bulk_marketing_needs_consent(org, family, django_capture_on_commit_callbacks):
    second = ContactFactory(organisation=org, email="tom@example.com")
    with tenant_context(org):
        privacy.ensure_default_types()
        privacy.record_consent(
            subject_type="people.contact",
            subject_id=str(second.pk),
            key="marketing-email",
            granted=True,
            method="form",
        )
    owner = api_as(org, "owner")
    response = bulk(
        owner,
        "contact",
        "send_message",
        [family["contact"].pk, second.pk],
        {"channel": "email", "purpose": "marketing", "subject": "Offer", "body": "News"},
        django_capture_on_commit_callbacks,
    )
    job = owner.get(f"/api/v1/bulk-jobs/{response.json()['id']}").json()
    assert job["succeeded"] == 1
    assert job["errors"] == {str(family["contact"].pk): "no_consent"}
    with tenant_context(org):
        assert list(Message.objects.values_list("to", flat=True)) == ["tom@example.com"]


def test_bulk_message_is_validated_and_permissioned(org, family):
    owner = api_as(org, "owner")
    response = owner.post(
        "/api/v1/bulk/client/send_message",
        {"target_ids": [str(family["client"].pk)], "params": {"channel": "email"}},
        format="json",
    )
    assert response.status_code == 422
    assert {"subject", "body"} <= set(response.json()["errors"])
    finance = api_as(org, "finance").post(
        "/api/v1/bulk/client/send_message",
        {"target_ids": [str(family["client"].pk)], "params": {"subject": "a", "body": "b"}},
        format="json",
    )
    assert finance.status_code == 403
    with tenant_context(org):
        assert not BulkJob.objects.exists()


def test_bulk_invite_to_portal(org, family, django_capture_on_commit_callbacks):
    no_email = ContactFactory(organisation=org, email="")
    owner = api_as(org, "owner")
    response = bulk(
        owner,
        "contact",
        "invite_portal",
        [family["contact"].pk, no_email.pk],
        {},
        django_capture_on_commit_callbacks,
    )
    job = owner.get(f"/api/v1/bulk-jobs/{response.json()['id']}").json()
    assert job["succeeded"] == 1
    assert list(job["errors"]) == [str(no_email.pk)]
    with tenant_context(org):
        invitation = Invitation.objects.get(email="priya@example.com")
    assert (invitation.target_type, invitation.target_id) == (
        "people.contact",
        str(family["contact"].pk),
    )


# --- @mentions (FR-05-7)


def run_mentions(org):
    with tenant_context(org), TestCase.captureOnCommitCallbacks(execute=True):
        row = OutboxEvent.objects.filter(event_type="note.created").latest("occurred_at")
        handlers.notify_mentions(EventEnvelope.from_payload(row.payload))


def test_mentions_notify_staff_who_can_read_the_note(org, family):
    colleague = MembershipFactory(organisation=org, role="coordinator").user
    tutor = MembershipFactory(organisation=org, role="tutor").user  # can't see staff-only notes
    author = MembershipFactory(organisation=org, role="owner").user
    body = (
        f'<p><span data-mention="{colleague.pk}">@Sam</span> and '
        f'<span data-mention="{tutor.pk}">@Nia</span>, please call them.</p>'
    )
    owner = client_for(org, author)
    response = owner.post(
        "/api/v1/notes",
        {
            "target_type": "people.client",
            "target_id": str(family["client"].pk),
            "body": body,
            "visibility": "staff_only",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    run_mentions(org)
    run_mentions(org)  # redelivered: still one notification
    with tenant_context(org):
        notes = list(InAppNotification.objects.filter(type_key="note_mention"))
    assert [n.user_id for n in notes] == [colleague.pk]
    assert "The Patels" in notes[0].title
    assert notes[0].link == f"/clients/{family['client'].pk}"
    assert "please call them" in notes[0].body


def test_mention_of_nobody_sends_nothing(org, family):
    with tenant_context(org):
        crm.create_note(target_type="people.client", target_id=family["client"].pk, body="<p>x</p>")
    run_mentions(org)
    with tenant_context(org):
        assert not InAppNotification.objects.exists()
