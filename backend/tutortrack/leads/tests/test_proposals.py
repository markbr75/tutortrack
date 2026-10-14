"""E17-T09: proposals with online acceptance (FR-17-3): pricing, drafting, sending with the
PDF, the public page, acceptance converting the enquiry with the chosen tutor and deposit,
declining, expiry and permissions."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest
from django.core import mail
from hypothesis import given, settings
from hypothesis import strategies as st

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads import proposals, services
from tutortrack.leads.models import Enquiry, PipelineStage, Proposal
from tutortrack.people.models import TutorSubject
from tutortrack.people.tests.factories import TutorProfileFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def enquiry(org) -> Enquiry:
    with tenant_context(org):
        return services.create_enquiry(
            contact={"first_name": "Priya", "last_name": "Patel", "email": "p@example.com"},
            students=[{"first_name": "Arjun", "subjects": [{"subject": "Maths", "level": ""}]}],
        )


@pytest.fixture
def tutor(org):
    with tenant_context(org):
        found = TutorProfileFactory(
            organisation=org, status="active", first_name="Nia", last_name="Adeyemi",
            phone="+44 7700 900123", headline="Maths specialist",
        )  # fmt: skip
        TutorSubject.objects.create(tutor=found, subject="Maths", approved=True)
    return found


@pytest.fixture
def service(org):
    with tenant_context(org):
        return ServiceFactory(organisation=org, name="GCSE Maths 1:1")


@pytest.fixture
def staff(org):
    return client_for(org, MembershipFactory(organisation=org, role="coordinator").user)


def draft(org, enquiry, service, tutor, **extra) -> Proposal:
    with tenant_context(org):
        return proposals.save_proposal(
            enquiry,
            title="GCSE Maths for Arjun",
            introduction="Thank you for talking to us.",
            schedule="Tuesdays at 16:00",
            lines=[{"service": str(service.pk), "quantity": "12", "unit_price": "45"}],
            tutors=[str(tutor.pk)],
            **extra,
        )


def sent(org, enquiry, service, tutor, capture, **extra) -> tuple[Proposal, str]:
    proposal = draft(org, enquiry, service, tutor, **extra)
    with tenant_context(org), capture(execute=True):
        proposal = proposals.send(proposal)
    return proposal, proposals.token_for(proposal)


# --- pricing (money: Hypothesis) ----------------------------------------------------------------


@settings(max_examples=60, deadline=None)
@given(
    rows=st.lists(
        st.tuples(
            st.decimals(min_value="0.25", max_value="200", places=2),
            st.decimals(min_value="0", max_value="999.999", places=3),
        ),
        min_size=1,
        max_size=6,
    )
)
def test_lines_round_half_up_per_line_and_total_is_their_sum(rows):
    lines, total = proposals.price_lines(
        [{"description": "Lesson", "quantity": str(q), "unit_price": str(u)} for q, u in rows],
        "GBP",
    )
    expected = [(q * u).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for q, u in rows]
    assert [Decimal(line["amount"]) for line in lines] == expected
    assert total == Money(sum(expected, Decimal(0)), "GBP")
    assert all(Decimal(line["unit_price"]).as_tuple().exponent == -2 for line in lines)


def test_line_validation():
    with pytest.raises(Exception, match="Describe"):
        proposals.price_lines([{"quantity": "1", "unit_price": "1"}], "GBP")
    with pytest.raises(Exception, match="negative"):
        proposals.price_lines([{"description": "x", "quantity": "1", "unit_price": "-1"}], "GBP")
    with pytest.raises(Exception, match="Quantities"):
        proposals.price_lines([{"description": "x", "quantity": "0", "unit_price": "1"}], "GBP")


# --- drafting and sending -----------------------------------------------------------------------


def test_staff_draft_edit_and_validate(org, enquiry, service, tutor, staff):
    body = {
        "enquiry": str(enquiry.pk),
        "title": "GCSE Maths for Arjun",
        "lines": [{"service": str(service.pk), "quantity": "10", "unit_price": "40.00"}],
        "tutors": [str(tutor.pk)],
        "deposit": "80.00",
    }
    created = staff.post("/api/v1/proposals", body, format="json")
    assert created.status_code == 201, created.content
    data = created.json()
    assert data["number"].startswith("PRO-")
    assert data["total"] == {"amount": "400.00", "currency": "GBP"}
    assert data["lines"][0]["description"] == "GCSE Maths 1:1"
    assert data["state"] == "draft"
    changed = staff.patch(
        f"/api/v1/proposals/{data['id']}",
        {
            **body,
            "deposit": None,
            "lines": [{"description": "Mock exam", "quantity": "1", "unit_price": "60"}],
        },
        format="json",
    )
    assert changed.status_code == 200, changed.content
    assert changed.json()["total"]["amount"] == "60.00"
    too_much = staff.post("/api/v1/proposals", {**body, "deposit": "500.00"}, format="json")
    assert too_much.status_code == 422
    stranger = staff.post("/api/v1/proposals", {**body, "tutors": [str(service.pk)]}, format="json")
    assert stranger.status_code == 422
    empty = staff.post(
        "/api/v1/proposals", {**body, "lines": [], "deposit": None}, format="json"
    ).json()
    assert staff.post(f"/api/v1/proposals/{empty['id']}/send").status_code == 422


def test_sending_emails_the_link_with_the_pdf_and_moves_the_stage(
    org, enquiry, service, tutor, django_capture_on_commit_callbacks
):
    with tenant_context(org):
        PipelineStage.objects.create(
            pipeline=enquiry.pipeline, name="Proposal", order=3, kind="open"
        )
    proposal, _token = sent(org, enquiry, service, tutor, django_capture_on_commit_callbacks)
    assert proposal.status == "sent"
    assert proposal.expires_at > now() + timedelta(days=13)
    with tenant_context(org):
        enquiry.refresh_from_db()
        assert enquiry.stage.name == "Proposal"
        assert OutboxEvent.objects.filter(event_type="proposal.sent").count() == 1
    [email] = [m for m in mail.outbox if "GCSE Maths for Arjun" in m.subject]
    assert "/proposals/" in email.body
    [(name, content, mime)] = email.attachments
    assert (name, mime) == (f"{proposal.number}.pdf", "application/pdf")
    assert content[:4] == b"%PDF"
    with tenant_context(org), pytest.raises(Exception, match="already been sent"):
        proposals.send(proposal)


def test_staff_pdf(org, enquiry, service, tutor, staff):
    proposal = draft(org, enquiry, service, tutor)
    response = staff.get(f"/api/v1/proposals/{proposal.pk}/pdf")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"


# --- the family ---------------------------------------------------------------------------------


def test_public_page_is_minimal(org, enquiry, service, tutor, django_capture_on_commit_callbacks):
    proposal, token = sent(org, enquiry, service, tutor, django_capture_on_commit_callbacks)
    body = client_for(org).get(f"/api/v1/public/proposals/{token}").json()
    assert (body["status"], body["total"], body["students"]) == ("sent", "540.00", ["Arjun"])
    assert body["tutors"][0]["name"] == "Nia A."
    dumped = json.dumps(body)
    for secret in ("Adeyemi", "7700", "p@example.com", str(service.pk)):
        assert secret not in dumped
    pdf = client_for(org).get(f"/api/v1/public/proposals/{token}/pdf")
    assert pdf.content[:4] == b"%PDF"
    with tenant_context(org):
        assert Proposal.objects.get(pk=proposal.pk).viewed_at is not None


def test_accepting_converts_offers_the_tutor_and_asks_for_the_deposit(
    org, enquiry, service, tutor, django_capture_on_commit_callbacks
):
    from tutortrack.billing.models import PaymentRequest
    from tutortrack.matching.models import OfferBatch

    MembershipFactory(organisation=org, role="coordinator")
    proposal, token = sent(
        org, enquiry, service, tutor, django_capture_on_commit_callbacks, deposit="90"
    )
    with tenant_context(org), django_capture_on_commit_callbacks(execute=True):
        response = client_for(org).post(
            f"/api/v1/public/proposals/{token}",
            {"name": "Priya Patel", "tutor": str(tutor.pk)},
            format="json",
        )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "accepted"
    assert body["pay_url"].startswith("/pay/")
    with tenant_context(org):
        proposal.refresh_from_db()
        enquiry.refresh_from_db()
        assert enquiry.status == "won"
        assert proposal.accepted_name == "Priya Patel"
        assert proposal.chosen_tutor_id == tutor.pk
        assert proposal.job_ids == enquiry.converted_job_ids
        [job_id] = proposal.job_ids
        batch = OfferBatch.objects.get(job_id=job_id)
        assert list(batch.offers.values_list("tutor_id", flat=True)) == [tutor.pk]
        request = PaymentRequest.objects.get(pk=proposal.payment_request_id)
        assert request.amount == Money("90.00", "GBP")
        event = OutboxEvent.objects.get(event_type="proposal.accepted")
        assert event.payload["data"]["job_ids"] == [job_id]
        from tutortrack.comms.models import Message

        assert Message.objects.filter(type_key="staff_proposal_response").exists()
    again = client_for(org).post(
        f"/api/v1/public/proposals/{token}", {"name": "Priya Patel"}, format="json"
    )
    assert (again.status_code, again.json()["code"]) == (422, "accepted")


def test_accept_needs_a_name_and_a_listed_tutor(
    org, enquiry, service, tutor, django_capture_on_commit_callbacks
):
    _proposal, token = sent(org, enquiry, service, tutor, django_capture_on_commit_callbacks)
    public = client_for(org)
    stranger = TutorProfileFactory(organisation=org)
    assert (
        public.post(
            f"/api/v1/public/proposals/{token}", {"name": "P", "tutor": None}, format="json"
        ).status_code
        == 422
    )
    assert (
        public.post(
            f"/api/v1/public/proposals/{token}",
            {"name": "Priya Patel", "tutor": str(stranger.pk)},
            format="json",
        ).status_code
        == 422
    )


def test_declining(org, enquiry, service, tutor, django_capture_on_commit_callbacks):
    proposal, token = sent(org, enquiry, service, tutor, django_capture_on_commit_callbacks)
    response = client_for(org).post(
        f"/api/v1/public/proposals/{token}/decline", {"reason": "Too far"}, format="json"
    )
    assert response.json()["status"] == "declined"
    with tenant_context(org):
        proposal.refresh_from_db()
        assert proposal.decline_reason == "Too far"
        assert Enquiry.objects.get(pk=enquiry.pk).status == "open"
    accept = client_for(org).post(
        f"/api/v1/public/proposals/{token}", {"name": "Priya Patel"}, format="json"
    )
    assert accept.json()["code"] == "declined"


def test_expiry_withdrawal_and_foreign_tokens(
    org, other_org, enquiry, service, tutor, django_capture_on_commit_callbacks, staff
):
    proposal, token = sent(org, enquiry, service, tutor, django_capture_on_commit_callbacks)
    assert client_for(other_org).get(f"/api/v1/public/proposals/{token}").status_code == 404
    with tenant_context(org):
        Proposal.objects.filter(pk=proposal.pk).update(expires_at=now() - timedelta(minutes=1))
    public = client_for(org)
    assert public.get(f"/api/v1/public/proposals/{token}").json()["status"] == "expired"
    late = public.post(f"/api/v1/public/proposals/{token}", {"name": "Priya"}, format="json")
    assert late.json()["code"] == "expired"
    with tenant_context(org):
        assert proposals.expire(proposal.pk) is True
        assert proposals.expire(proposal.pk) is False  # idempotent
        assert OutboxEvent.objects.filter(event_type="proposal.expired").count() == 1
    second, token2 = sent(org, enquiry, service, tutor, django_capture_on_commit_callbacks)
    assert staff.post(f"/api/v1/proposals/{second.pk}/withdraw").json()["state"] == "withdrawn"
    assert public.get(f"/api/v1/public/proposals/{token2}").status_code == 404


def test_permissions(org, enquiry, service, tutor):
    draft(org, enquiry, service, tutor)
    tutor_user = MembershipFactory(organisation=org, role="tutor").user
    assert client_for(org, tutor_user).get("/api/v1/proposals").status_code == 403
    finance = client_for(org, MembershipFactory(organisation=org, role="finance").user)
    assert finance.post("/api/v1/proposals", {"enquiry": str(enquiry.pk)}).status_code == 403


class TestProposalIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/proposals"

    def make_object(self, organisation):
        with tenant_context(organisation):
            found = services.create_enquiry(
                contact={"first_name": "Ola", "email": f"ola@{organisation.slug}.example"},
                students=[{"first_name": "Ade"}],
            )
            return proposals.save_proposal(
                found, lines=[{"description": "Lesson", "quantity": "1", "unit_price": "40"}]
            )


def test_proposals_are_in_dsar_exports_and_erased(
    org, enquiry, service, tutor, django_capture_on_commit_callbacks
):
    from tutortrack.leads import privacy
    from tutortrack.privacy import registry

    _proposal, token = sent(org, enquiry, service, tutor, django_capture_on_commit_callbacks)
    with tenant_context(org):
        proposals.decline(token, reason="Priya found another tutor")
        person = registry.resolve("people.client", str(enquiry.client_id))
        [section] = [s for s in privacy.export(person) if s.key == "leads.proposals"]
        assert section.records[0]["decline_reason"] == "Priya found another tutor"
        ctx = registry.ErasureContext(labels={}, financial_cutoff=now())
        ctx.prepare_scrub(person, "[erased]")
        privacy.erase(person, ctx)
        assert Proposal.objects.get().decline_reason == ""
