"""E18: applications, pipeline, interviews, references, approval and onboarding, compliance
and restrictions, subject competency."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest
from django.conf import settings
from django.test import Client as HttpClient

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.money import Money
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.identity.models import Invitation
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads.models import Form
from tutortrack.people.models import TutorProfile
from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory
from tutortrack.recruitment import compliance, services
from tutortrack.recruitment.models import (
    ChecklistInstance,
    ComplianceRecord,
    JobOpening,
    ReferenceRequest,
    RequirementType,
    TutorApplication,
)

pytestmark = pytest.mark.django_db

SCHEMA = {"steps": [{"title": "You", "fields": [
    {"key": "first_name", "label": "First name", "type": "text", "required": True,
     "maps_to": "applicant.first_name"},
    {"key": "last_name", "label": "Last name", "type": "text", "maps_to": "applicant.last_name"},
    {"key": "email", "label": "Email", "type": "email", "required": True,
     "maps_to": "applicant.email"},
    {"key": "subjects", "label": "Subjects", "type": "text", "maps_to": "applicant.subjects"},
    {"key": "experience", "label": "Experience", "type": "textarea",
     "maps_to": "applicant.experience"},
    {"key": "referees", "label": "Referees", "type": "referees", "required": True,
     "maps_to": "referees"},
    {"key": "why", "label": "Why tutoring?", "type": "textarea"},
]}]}  # fmt: skip


def anonymous(org: Any) -> HttpClient:
    return HttpClient(HTTP_HOST=f"{org.slug}.{settings.TENANT_BASE_DOMAIN}")


@pytest.fixture
def opening(org) -> JobOpening:
    with tenant_context(org):
        form = Form.objects.create(
            name="Apply", slug="apply", type="application", schema=SCHEMA, published=True
        )
        return JobOpening.objects.create(
            title="Maths tutors in Leeds", slug="maths-leeds", form=form, published=True
        )


APPLICATION = {
    "first_name": "Nia", "last_name": "Okafor", "email": "nia@example.com",
    "subjects": "Maths, Physics", "experience": "3 years", "why": "I love it",
    "referees": [{"name": "Dr Ade", "email": "ade@example.com", "relationship": "Head of maths"},
                 {"name": "Sam Lee", "email": "sam@example.com"}],
}  # fmt: skip


def apply(org, data: dict[str, Any] | None = None) -> Any:
    return anonymous(org).post(
        "/api/v1/public/job-openings/maths-leeds",
        data=json.dumps({"data": data or APPLICATION}),
        content_type="application/json",
    )


@pytest.fixture
def application(org, opening) -> TutorApplication:
    assert apply(org).status_code == 201
    with tenant_context(org):
        return TutorApplication.objects.select_related("stage").get()


@pytest.fixture
def recruiter(org) -> Any:
    with tenant_context(org):
        return MembershipFactory(organisation=org, role="admin").user


# --- applications (T01, T02, T04) -----------------------------------------------------------


def test_public_openings_and_application(org, opening, application):
    listed = anonymous(org).get("/api/v1/public/job-openings").json()
    assert [o["slug"] for o in listed] == ["maths-leeds"]
    assert (application.stage.name, application.status) == ("Applied", "open")
    assert [s["subject"] for s in application.subjects] == ["Maths", "Physics"]
    assert application.answers == {"Why tutoring?": "I love it"}
    with tenant_context(org):
        refs = list(ReferenceRequest.objects.order_by("referee_email"))
        assert [r.referee_email for r in refs] == ["ade@example.com", "sam@example.com"]


def test_referees_need_emails(org, opening):
    bad = apply(org, {**APPLICATION, "referees": [{"name": "X", "email": "nope"}]})
    assert bad.status_code == 422
    assert "referees" in bad.json()["errors"]


def test_application_forms_are_not_enquiry_forms(org, opening):
    assert anonymous(org).get("/api/v1/public/forms/apply").status_code in (404, 200)
    response = anonymous(org).post(
        "/api/v1/public/forms/apply",
        data=json.dumps({"data": APPLICATION}),
        content_type="application/json",
    )
    assert response.status_code == 404


def test_pipeline_scorecard_interview_and_reference(org, application, recruiter):
    api = client_for(org, recruiter)
    stages = api.get("/api/v1/application-stages").json()
    interview_stage = next(s["id"] for s in stages if s["name"] == "Interview")
    moved = api.post(f"/api/v1/applications/{application.pk}/move", {"stage": interview_stage})
    assert moved.json()["stage_name"] == "Interview"
    scored = api.post(
        f"/api/v1/applications/{application.pk}/score",
        {"scores": {"Communication": 5}, "recommendation": "yes"},
        format="json",
    )
    assert scored.json()["scorecards"][0]["recommendation"] == "yes"
    start = (now() + timedelta(days=2)).replace(microsecond=0)
    with tenant_context(org):
        _interview, token = services.propose_interview(
            application, interviewer=recruiter, options=[start, start + timedelta(hours=1)]
        )
    page = anonymous(org).get(f"/api/v1/public/interviews/{token}").json()
    assert page["status"] == "proposed"
    booked = anonymous(org).post(
        f"/api/v1/public/interviews/{token}",
        data=json.dumps({"start": page["options"][1]}),
        content_type="application/json",
    )
    assert booked.json()["status"] == "booked"
    with tenant_context(org):
        _ref, ref_token = services.request_reference(application, name="Jo", email="jo@x.com")
    given = anonymous(org).post(
        f"/api/v1/public/references/{ref_token}",
        data=json.dumps({"responses": {"q1": "Great"}, "rating": 5, "concerns": False}),
        content_type="application/json",
    )
    assert given.json()["status"] == "received"
    again = anonymous(org).post(
        f"/api/v1/public/references/{ref_token}",
        data=json.dumps({"responses": {}, "rating": 5}),
        content_type="application/json",
    )
    assert again.status_code == 422


def test_approval_creates_onboarding_tutor_invitation_and_checklist(org, application, recruiter):
    """AC FR-18-2."""
    api = client_for(org, recruiter)
    approved = api.post(f"/api/v1/applications/{application.pk}/approve", {})
    assert approved.status_code == 200, approved.content
    assert approved.json()["status"] == "hired"
    with tenant_context(org):
        tutor = TutorProfile.objects.get(email="nia@example.com")
        assert tutor.status == "onboarding"
        assert sorted(s.subject for s in tutor.subjects.all()) == ["Maths", "Physics"]
        assert Invitation.objects.filter(email="nia@example.com", role="tutor").exists()
        instance = ChecklistInstance.objects.get(tutor=tutor)
        assert {i["key"] for i in instance.items} >= {"agreement", "documents", "payout"}


def test_rejection_emails_the_applicant(org, application, recruiter):
    api = client_for(org, recruiter)
    api.post(f"/api/v1/applications/{application.pk}/reject", {"reason": "No availability"})
    with tenant_context(org):
        application.refresh_from_db()
        assert (application.status, application.stage.name) == ("rejected", "Rejected")
        assert Message.objects.filter(
            type_key="application_rejected", to="nia@example.com"
        ).exists()


# --- compliance (T06, T07, T08) -------------------------------------------------------------


@pytest.fixture
def active_tutor(org) -> TutorProfile:
    with tenant_context(org):
        membership = MembershipFactory(organisation=org, role="tutor")
        return TutorProfileFactory(organisation=org, status="active", membership=membership)


def make_compliant(org, tutor, *, dbs_expiry: date) -> None:
    with tenant_context(org):
        verifier = MembershipFactory(organisation=org, role="admin").user
        for requirement in compliance.applicable(tutor):
            if not (requirement.mandatory and requirement.blocking):
                continue
            expiry = (
                dbs_expiry
                if requirement.key == "dbs_enhanced"
                else (date.today() + timedelta(days=400) if requirement.has_expiry else None)
            )
            record = compliance.submit(
                tutor,
                requirement,
                number="001234567890",
                issue_date=date.today() - timedelta(days=10),
                expiry_date=expiry,
            )
            compliance.verify(record, user=verifier)


def test_uk_requirements_and_dbs_expiring_today_restricts(org, active_tutor):
    """AC FR-18-6: nightly job, dashboard, assignment guard and override."""
    with tenant_context(org):
        keys = {r.key for r in compliance.applicable(active_tutor)}
        assert {"dbs_enhanced", "right_to_work", "photo_id"} <= keys
    make_compliant(org, active_tutor, dbs_expiry=date.today() + timedelta(days=30))
    with tenant_context(org):
        assert compliance.problems(active_tutor) == []
        ComplianceRecord.objects.filter(requirement__key="dbs_enhanced").update(
            expiry_date=compliance.today()
        )
        assert compliance.sweep() == 1
        active_tutor.refresh_from_db()
        assert active_tutor.status == "restricted"
        board = compliance.dashboard()
        row = next(r for r in board["rows"] if r["tutor"].pk == active_tutor.pk)
        assert row["cells"]["dbs_enhanced"]["status"] == "expired"
        client = ClientFactory(organisation=org)
        student = StudentFactory(organisation=org, client=client)
        service = ServiceFactory(organisation=org)
        coordinator = MembershipFactory(organisation=org, role="coordinator").user
        admin = MembershipFactory(organisation=org, role="admin").user
    start = (now() + timedelta(days=3)).replace(minute=0, second=0, microsecond=0)
    body = {
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
        "service": str(service.pk),
        "attendees": [{"student": str(student.pk)}],
        "tutors": [{"tutor": str(active_tutor.pk)}],
        "timezone": "Europe/London",
    }
    blocked = client_for(org, coordinator).post("/api/v1/lessons", body, format="json")
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "tutor_not_compliant"
    denied = client_for(org, coordinator).post(
        "/api/v1/lessons?compliance_override=urgent", body, format="json"
    )
    assert denied.status_code == 403
    allowed = client_for(org, admin).post(
        "/api/v1/lessons?compliance_override=Cover+for+tomorrow", body, format="json"
    )
    assert allowed.status_code == 201, allowed.content


def test_renewal_lifts_the_restriction_and_pay_holds_follow(org, active_tutor):
    from tutortrack.payroll import services as payroll

    make_compliant(org, active_tutor, dbs_expiry=date.today() + timedelta(days=30))
    with tenant_context(org):
        item = payroll.create_manual_item(
            tutor=active_tutor,
            kind="bonus",
            description="Bonus",
            amount=Money("10.00", "GBP"),
            day=date.today(),
        )
        dbs = RequirementType.objects.get(key="dbs_enhanced")
        ComplianceRecord.objects.filter(requirement=dbs).update(expiry_date=compliance.today())
        compliance.sweep()
        item.refresh_from_db()
        assert (item.status, item.hold_reasons) == ("held", ["compliance"])
        verifier = MembershipFactory(organisation=org, role="admin").user
        record = compliance.submit(
            active_tutor, dbs, number="999", expiry_date=date.today() + timedelta(days=1000)
        )
        compliance.verify(record, user=verifier)
        active_tutor.refresh_from_db()
        item.refresh_from_db()
    assert active_tutor.status == "active"
    assert item.status == "ready"


def test_manual_restrictions_are_left_alone(org, active_tutor):
    from tutortrack.people.services import change_tutor_status

    make_compliant(org, active_tutor, dbs_expiry=date.today() + timedelta(days=30))
    with tenant_context(org):
        change_tutor_status(active_tutor, "restricted")
        compliance.evaluate(active_tutor)
        active_tutor.refresh_from_db()
    assert active_tutor.status == "restricted"


def test_tutors_upload_their_own_documents_but_cannot_verify(org, active_tutor):
    with tenant_context(org):
        MembershipFactory(organisation=org, role="admin")
    tutor_api = client_for(org, active_tutor.membership.user)
    mine = tutor_api.get("/api/v1/me/compliance").json()
    dbs = next(r for r in mine["requirements"] if r["key"] == "dbs_enhanced")
    missing = tutor_api.post("/api/v1/me/compliance", {"requirement": dbs["id"]}, format="json")
    assert missing.status_code == 422
    sent = tutor_api.post(
        "/api/v1/me/compliance",
        {
            "requirement": dbs["id"],
            "number": "001234567890",
            "issue_date": date.today().isoformat(),
        },
        format="json",
    )
    assert sent.status_code == 200, sent.content
    record = next(r for r in sent.json()["records"] if r["requirement_key"] == "dbs_enhanced")
    assert record["status"] == "submitted"
    assert record["number"].endswith("7890")
    assert record["number"].startswith("•")
    assert record["expiry_date"] == (date.today().replace(year=date.today().year + 3)).isoformat()
    with tenant_context(org):
        obj = ComplianceRecord.objects.get(pk=record["id"])
        with pytest.raises(PermissionDenied):
            compliance.verify(obj, user=active_tutor.membership.user)
        assert Message.objects.filter(type_key="staff_compliance_submitted").exists()
    assert tutor_api.get(f"/api/v1/tutors/{active_tutor.pk}/compliance").status_code == 403


def test_reject_needs_a_reason(org, active_tutor):
    with tenant_context(org):
        verifier = MembershipFactory(organisation=org, role="admin").user
        compliance.ensure_requirement_types()
        photo = RequirementType.objects.get(key="photo_id")
        record = compliance.submit(active_tutor, photo)
        with pytest.raises(BusinessRuleViolation):
            compliance.reject(record, user=verifier, reason=" ")
        compliance.reject(record, user=verifier, reason="Blurry")
        record.refresh_from_db()
    assert record.status == "rejected"


# --- onboarding (T05) -----------------------------------------------------------------------


def test_onboarding_completes_and_activates(org, application, recruiter):
    from tutortrack.payroll import services as payroll
    from tutortrack.scheduling.models import AvailabilityTemplate

    with tenant_context(org):
        tutor = services.approve(application, user=recruiter)
        membership = MembershipFactory(organisation=org, role="tutor")
        TutorProfile.objects.filter(pk=tutor.pk).update(membership=membership)
        tutor.refresh_from_db()
        assert services.check_onboarding(tutor.pk) == "waiting"
    tutor_api = client_for(org, membership.user)
    for key in ("agreement", "safeguarding_policy"):
        assert tutor_api.post(f"/api/v1/me/onboarding/{key}/done").status_code == 200
    assert tutor_api.post("/api/v1/me/onboarding/payout/done").status_code == 400
    with tenant_context(org):
        payroll.update_profile(
            tutor,
            bank={
                "country": "GB",
                "account_name": "N Okafor",
                "sort_code": "309634",
                "account_number": "12345678",
            },
        )
        AvailabilityTemplate.objects.create(
            tutor=tutor, effective_from=date.today(), timezone="Europe/London"
        )
    make_compliant(org, tutor, dbs_expiry=date.today() + timedelta(days=300))
    state = tutor_api.get("/api/v1/me/onboarding").json()
    assert all(i["done"] for i in state["items"] if i["mandatory"])
    with tenant_context(org):
        assert services.check_onboarding(tutor.pk) == "complete"
        tutor.refresh_from_db()
    assert tutor.status == "active"


# --- subject competency (T09) and file access -----------------------------------------------


def test_subject_competency(org, active_tutor, recruiter):
    from tutortrack.people.services import set_tutor_subjects

    with tenant_context(org):
        [subject] = set_tutor_subjects(active_tutor, [{"subject": "Maths", "level": "GCSE"}])
    api = client_for(org, recruiter)
    url = f"/api/v1/tutors/{active_tutor.pk}/subjects/{subject.pk}/assess"
    assert api.post(url, {"status": "assessed", "evidence": "Test 92%"}).status_code == 204
    with tenant_context(org):
        subject.refresh_from_db()
        assert (subject.competency, subject.approved) == ("assessed", False)
    api.post(url, {"status": "approved", "evidence": "Interview"})
    with tenant_context(org):
        subject.refresh_from_db()
    assert (subject.competency, subject.approved) == ("approved", True)


def test_compliance_files_are_visible_to_compliance_staff_only(org, active_tutor):
    from tutortrack.core.models import StoredFile
    from tutortrack.core.storage.services import attach, can_access

    with tenant_context(org):
        stored = StoredFile.objects.create(
            filename="dbs.pdf",
            content_type="application/pdf",
            size_bytes=10,
            storage_key="k",
            uploaded_by=active_tutor.membership.user,
        )
        record = compliance.record_for(
            active_tutor,
            RequirementType.objects.get(key="dbs_enhanced")
            if RequirementType.objects.exists()
            else compliance.ensure_requirement_types()[0],
        )
        attach(stored, record)
        stored.refresh_from_db()
        admin = MembershipFactory(organisation=org, role="admin").user
        coordinator = MembershipFactory(organisation=org, role="coordinator").user
        assert can_access(admin, stored)
        assert not can_access(coordinator, stored)
        assert can_access(active_tutor.membership.user, stored)
