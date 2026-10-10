"""E17: forms and public capture, pipeline work, trials, conversion, registration, waitlist,
funnel and the inbound email webhook."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings
from django.test import Client as HttpClient

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads import services
from tutortrack.leads.models import Enquiry, Form, FormSubmission, PipelineStage
from tutortrack.people.models import Client, Student
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db

SCHEMA = {
    "steps": [
        {
            "title": "You",
            "fields": [
                {
                    "key": "first_name",
                    "label": "First name",
                    "type": "text",
                    "required": True,
                    "maps_to": "contact.first_name",
                },
                {
                    "key": "last_name",
                    "label": "Last name",
                    "type": "text",
                    "maps_to": "contact.last_name",
                },
                {
                    "key": "email",
                    "label": "Email",
                    "type": "email",
                    "required": True,
                    "maps_to": "contact.email",
                },
                {
                    "key": "postcode",
                    "label": "Postcode",
                    "type": "postcode",
                    "maps_to": "client.postcode",
                },
            ],
        },
        {
            "title": "Students",
            "fields": [
                {
                    "key": "children",
                    "label": "Children",
                    "type": "students",
                    "required": True,
                    "maps_to": "students",
                },
                {
                    "key": "how_heard",
                    "label": "How did you hear about us?",
                    "type": "select",
                    "options": ["Google", "Friend"],
                },
                {
                    "key": "friend",
                    "label": "Friend's name",
                    "type": "text",
                    "required": True,
                    "show_if": {"field": "how_heard", "equals": "Friend"},
                },
            ],
        },
    ]
}


def anonymous(org: Any) -> HttpClient:
    return HttpClient(HTTP_HOST=f"{org.slug}.{settings.TENANT_BASE_DOMAIN}")


@pytest.fixture
def form(org) -> Form:
    with tenant_context(org):
        return Form.objects.create(name="Enquire", slug="enquire", schema=SCHEMA, published=True)


def submit(org, payload: dict[str, Any]) -> Any:
    return anonymous(org).post(
        "/api/v1/public/forms/enquire", data=json.dumps(payload), content_type="application/json"
    )


ANSWERS = {
    "first_name": "Priya",
    "last_name": "Patel",
    "email": "priya@example.com",
    "postcode": "LS1 4AP",
    "how_heard": "Google",
    "children": [
        {"first_name": "Arjun", "subjects": ["Maths"]},
        {"first_name": "Mira", "last_name": "Patel", "subjects": ["English"]},
    ],
}


# --- capture (T01, T03) ---------------------------------------------------------------------


def test_public_form_creates_the_enquiry_and_family_in_one_go(org, form):
    """AC FR-17-1."""
    response = submit(org, {"data": ANSWERS, "utm": {"utm_source": "google", "bogus": "x"}})
    assert response.status_code == 201, response.content
    with tenant_context(org):
        enquiry = Enquiry.objects.get()
        assert (enquiry.stage.name, enquiry.status, enquiry.source) == ("New", "open", "form")
        assert enquiry.client.status == Client.Status.PROSPECT
        assert enquiry.contact.email == "priya@example.com"
        assert sorted(s.status for s in enquiry.students.all()) == ["lead", "lead"]
        assert enquiry.utm == {"utm_source": "google"}
        assert "How did you hear about us?: Google" in enquiry.notes
        assert enquiry.title.startswith("Priya Patel - ")
        assert OutboxEvent.objects.filter(event_type="enquiry.received").exists()
        assert FormSubmission.objects.get().created_records["enquiry"] == str(enquiry.pk)


def test_form_validation_and_conditional_fields(org, form):
    missing = submit(org, {"data": {**ANSWERS, "email": "nope"}})
    assert missing.status_code == 422
    assert "email" in missing.json()["errors"]
    friend = submit(org, {"data": {**ANSWERS, "how_heard": "Friend"}})
    assert friend.json()["errors"] == {"friend": ["Required."]}
    with tenant_context(org):
        assert not Enquiry.objects.exists()


def test_honeypot_submissions_are_kept_but_ignored(org, form):
    response = submit(org, {"data": ANSWERS, "website": "http://spam.example"})
    assert response.status_code == 201
    with tenant_context(org):
        assert FormSubmission.objects.get().spam
        assert not Enquiry.objects.exists()


def test_unpublished_forms_are_not_found(org, form):
    with tenant_context(org):
        Form.objects.update(published=False)
    assert anonymous(org).get("/api/v1/public/forms/enquire").status_code == 404


def test_duplicate_contact_links_to_the_existing_family(org):
    with tenant_context(org):
        family = ClientFactory(organisation=org, status="active")
        ContactFactory(organisation=org, client=family, email="priya@example.com")
        StudentFactory(organisation=org, client=family, first_name="Arjun")
        enquiry = services.create_enquiry(
            contact={"first_name": "Priya", "email": "PRIYA@example.com"},
            students=[{"first_name": "arjun"}, {"first_name": "Leo"}],
        )
        assert enquiry.client_id == family.pk
        assert Client.objects.count() == 1
        assert sorted(s.first_name for s in enquiry.students.all()) == ["Arjun", "Leo"]


def test_public_enquiry_api_and_inbound_email(org, settings):
    response = anonymous(org).post(
        "/api/v1/public/enquiries",
        data=json.dumps(
            {
                "first_name": "Sam",
                "email": "sam@example.com",
                "students": [{"first_name": "Ola"}],
                "subjects": [{"subject": "Physics"}],
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    settings.INBOUND_EMAIL_TOKEN = "secret"
    body = {
        "MailboxHash": org.slug,
        "FromFull": {"Email": "dee@example.com", "Name": "Dee Jones"},
        "Subject": "Chemistry help",
        "TextBody": "For my son, Year 10.",
    }
    hook = HttpClient().post(
        "/webhooks/inbound-email?token=secret",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert hook.status_code == 200
    forged = HttpClient().post(
        "/webhooks/inbound-email?token=wrong", data="{}", content_type="application/json"
    )
    assert forged.status_code == 403
    with tenant_context(org):
        sources = sorted(Enquiry.objects.values_list("source", flat=True))
        assert sources == ["api", "email"]
        email = Enquiry.objects.get(source="email")
        assert email.contact.first_name == "Dee"
        assert "Year 10" in email.notes


# --- pipeline work (T02) --------------------------------------------------------------------


@pytest.fixture
def enquiry(org) -> Enquiry:
    with tenant_context(org):
        return services.create_enquiry(
            contact={"first_name": "Priya", "last_name": "Patel", "email": "p@example.com"},
            students=[{"first_name": "Arjun", "subjects": [{"subject": "Maths", "level": ""}]}],
            value_estimate=Money("400.00", "GBP"),
        )


def stage(enquiry: Enquiry, name: str) -> PipelineStage:
    return enquiry.pipeline.stages.get(name=name)


def test_round_robin_assignment(org):
    with tenant_context(org):
        a = MembershipFactory(organisation=org, role="coordinator").user
        b = MembershipFactory(organisation=org, role="coordinator").user
        from tutortrack.leads.models import AssignmentRule

        AssignmentRule.objects.create(subject="Maths", owners=[str(a.pk), str(b.pk)])
        owners = [
            services.create_enquiry(
                contact={"first_name": f"P{i}", "email": f"p{i}@example.com"},
                subjects=[{"subject": "Maths", "level": ""}],
            ).owner_id
            for i in range(3)
        ]
        other = services.create_enquiry(
            contact={"first_name": "Z", "email": "z@example.com"},
            subjects=[{"subject": "Art", "level": ""}],
        )
    assert owners == [a.pk, b.pk, a.pk]
    assert other.owner_id is None


def test_moving_records_history_and_first_response(org, enquiry):
    with tenant_context(org):
        moved = services.move(enquiry, stage(enquiry, "Contacted"))
        assert moved.first_response_at is not None
        assert [h.to_stage.name for h in moved.history.all()] == ["New", "Contacted"]
        with pytest.raises(BusinessRuleViolation) as won:
            services.move(moved, stage(enquiry, "Won"))
        assert won.value.extra["code"] == "convert_required"
        with pytest.raises(BusinessRuleViolation):
            services.lose(moved, reason="no reason")
        lost = services.lose(moved, reason="too_expensive", note="Budget", nurture=True)
        from tutortrack.crm.models import Tag

        assert Tag.objects.filter(name="nurture").exists()
    assert (lost.status, lost.stage.name, lost.lost_reason) == ("lost", "Lost", "too_expensive")


def test_pipelines_need_won_and_lost_stages(tenant):
    with pytest.raises(BusinessRuleViolation):
        services.save_pipeline(
            name="Schools", stages=[{"name": "New"}, {"name": "Won", "kind": "won"}]
        )
    pipeline = services.save_pipeline(
        name="Schools",
        stages=[
            {"name": "New", "sla_hours": 4},
            {"name": "Won", "kind": "won"},
            {"name": "Lost", "kind": "lost"},
        ],
    )
    assert [s.name for s in pipeline.stages.all()] == ["New", "Won", "Lost"]


# --- trials and conversion (T05, T06) -------------------------------------------------------


def test_free_trial_then_outcome(org, enquiry):
    with tenant_context(org):
        tutor = TutorProfileFactory(organisation=org, status="active")
        service = ServiceFactory(organisation=org)
        start = (now() + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
        booked = services.book_trial(
            enquiry,
            start=start,
            end=start + timedelta(hours=1),
            service=service,
            tutor=tutor,
            price=Money("0", "GBP"),
        )
        assert booked.stage.name == "Trial booked"
        attendee = booked.trial_lesson.attendees.get()
        assert attendee.charge_amount == Money("0.00", "GBP")
        assert Student.objects.get(first_name="Arjun").status == "trial"
        done = services.record_trial_outcome(booked, outcome="continuing", feedback="Loved it")
    assert (done.stage.name, done.trial_outcome) == ("Trial done", "continuing")


def test_convert_creates_jobs_and_wins(org, enquiry):
    with tenant_context(org):
        service = ServiceFactory(organisation=org)
        result = services.convert(enquiry, jobs=[{"service": service}], invite_to_portal=True)
        won = result["enquiry"]
        assert (won.status, won.stage.name) == ("won", "Won")
        assert won.client.status == "active"
        assert Student.objects.get(first_name="Arjun").status == "active"
        [job] = result["jobs"]
        assert job.status == "seeking_tutor"
        assert won.converted_job_ids == [str(job.pk)]
        assert result["invited"]
        assert OutboxEvent.objects.filter(event_type="enquiry.won").exists()


def test_registration_form_creates_an_active_family_and_fee(org):
    with tenant_context(org):
        Form.objects.create(
            name="Register",
            slug="register",
            type="registration",
            schema=SCHEMA,
            published=True,
            settings={"fee": {"amount": "25.00", "currency": "GBP"}},
        )
    response = anonymous(org).post(
        "/api/v1/public/forms/register",
        data=json.dumps({"data": ANSWERS}),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    with tenant_context(org):
        family = Client.objects.get()
        assert family.status == "active"
        assert not Enquiry.objects.exists()
        assert sorted(s.status for s in family.students.all()) == ["active", "active"]
        from tutortrack.billing.models import PaymentRequest

        request = PaymentRequest.objects.get(client=family)
        assert request.amount == Money("25.00", "GBP")


# --- waitlist (T07) -------------------------------------------------------------------------


def test_waitlist_offer_accept_and_cascade(org):
    with tenant_context(org):
        family = ClientFactory(organisation=org)
        first = services.add_to_waitlist(
            student=StudentFactory(organisation=org, client=family, status="lead"), subject="Maths"
        )
        second = services.add_to_waitlist(
            student=StudentFactory(organisation=org, client=family), subject="Maths"
        )
        assert (services.position(first), services.position(second)) == (1, 2)
        assert Student.objects.get(pk=first.student_id).status == "waiting"
        token = services.offer_place(first, details="Tuesdays 4pm with Nia", hours=24)
    page = anonymous(org).get(f"/api/v1/public/offers/{token}").json()
    assert (page["details"], page["status"]) == ("Tuesdays 4pm with Nia", "offered")
    accepted = anonymous(org).post(
        f"/api/v1/public/offers/{token}", data={"accept": True}, content_type="application/json"
    )
    assert accepted.json()["status"] == "accepted"
    with tenant_context(org):
        token2 = services.offer_place(second, details="Thursdays 5pm", hours=1)
        assert token2
        assert services.expire_offer(second.pk) == ""  # nobody else waiting
        third = services.add_to_waitlist(
            student=StudentFactory(organisation=org, client=family), subject="Maths"
        )
        fourth = services.add_to_waitlist(
            student=StudentFactory(organisation=org, client=family), subject="Maths"
        )
        services.offer_place(third, details="Fridays")
        assert services.expire_offer(third.pk) == str(fourth.pk)
        fourth.refresh_from_db()
    assert (fourth.status, fourth.offer_details) == ("offered", "Fridays")
    late = anonymous(org).post(
        f"/api/v1/public/offers/{token2}", data={"accept": True}, content_type="application/json"
    )
    assert late.status_code == 422


# --- SLA, acknowledgement and reporting -----------------------------------------------------


def test_sla_breach_is_recorded_once_and_alerts_staff(org, enquiry):
    with tenant_context(org):
        status = services.sla_status(enquiry.pk)
        assert status["open"]
        assert status["deadline"]
        assert services.breach_sla(enquiry.pk, status["stage"])
        assert not services.breach_sla(enquiry.pk, status["stage"])
        assert OutboxEvent.objects.filter(event_type="enquiry.sla_breached").count() == 1


def test_acknowledgement_and_owner_notice(org):
    from tutortrack.comms.models import Message

    with tenant_context(org):
        owner = MembershipFactory(organisation=org, role="coordinator").user
        enquiry = services.create_enquiry(
            contact={"first_name": "Priya", "email": "p@example.com"}, owner=owner
        )
        services.acknowledge(enquiry.pk)
        kinds = set(Message.objects.values_list("type_key", "channel"))
    assert ("enquiry_acknowledgement", "email") in kinds
    assert ("enquiry_assigned", "in_app") in kinds


def test_funnel_report(org, enquiry):
    with tenant_context(org):
        services.move(enquiry, stage(enquiry, "Contacted"))
        other = services.create_enquiry(contact={"first_name": "Lee", "email": "lee@x.com"})
        services.lose(other, reason="no_response")
        service = ServiceFactory(organisation=org)
        services.convert(enquiry, jobs=[{"service": service}])
        coordinator = MembershipFactory(organisation=org, role="coordinator").user
    report = client_for(org, coordinator).get("/api/v1/leads/reports/funnel").json()
    assert report["total"] == 2
    reached = {s["stage"]: s["reached"] for s in report["stages"]}
    assert (reached["New"], reached["Contacted"], reached["Won"], reached["Lost"]) == (2, 1, 1, 1)
    assert report["win_rate"] == 50.0
    assert report["won_value"] == {"GBP": "400.00"}
    assert report["lost_reasons"] == [{"lost_reason": "no_response", "count": 1}]


# --- API ------------------------------------------------------------------------------------


def test_board_and_actions_api(org, enquiry):
    with tenant_context(org):
        coordinator = MembershipFactory(organisation=org, role="coordinator").user
    api = client_for(org, coordinator)
    board = api.get("/api/v1/enquiries/board").json()
    assert [c["stage"]["name"] for c in board] == ["New", "Contacted", "Trial booked", "Trial done"]
    assert board[0]["enquiries"][0]["id"] == str(enquiry.pk)
    contacted = next(c["stage"]["id"] for c in board if c["stage"]["name"] == "Contacted")
    moved = api.post(f"/api/v1/enquiries/{enquiry.pk}/move", {"stage": contacted})
    assert moved.json()["stage_name"] == "Contacted"
    history = api.get(f"/api/v1/enquiries/{enquiry.pk}/history").json()
    assert [h["to_stage_name"] for h in history] == ["New", "Contacted"]
    created = api.post(
        "/api/v1/enquiries",
        {"first_name": "Phone", "phone": "07700 900123", "source": "phone"},
        format="json",
    )
    assert created.status_code == 201, created.content


def test_tutors_cannot_see_enquiries(org, enquiry):
    with tenant_context(org):
        tutor = MembershipFactory(organisation=org, role="tutor").user
    assert client_for(org, tutor).get("/api/v1/enquiries").status_code == 403


class TestEnquiryIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/enquiries"

    def make_object(self, organisation: Any) -> Enquiry:
        with tenant_context(organisation):
            return services.create_enquiry(
                contact={"first_name": "Iso", "email": f"iso@{organisation.slug}.example"}
            )


def test_settings_change_lost_reasons(org, enquiry):
    with tenant_context(org):
        settings_service.update_settings("leads", {"leads.lost_reasons": ["moved_away"]})
        lost = services.lose(enquiry, reason="moved_away")
    assert lost.lost_reason == "moved_away"
