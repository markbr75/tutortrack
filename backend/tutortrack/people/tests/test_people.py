"""E05-T01..T03: clients, contacts, students, tutors, addresses, duplicates."""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from unittest import mock

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for, result_ids
from tutortrack.identity.models import Invitation, Membership
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people import services
from tutortrack.people.models import Client, Contact, Student
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)

pytestmark = pytest.mark.django_db

FAMILY = {
    "contact": {"first_name": "Priya", "last_name": "Patel", "email": "Priya@Example.com"},
    "students": [
        {
            "first_name": "Arjun",
            "year_group": "Year 10",
            "subjects": [{"subject": "Maths", "level": "GCSE"}],
        },
        {"first_name": "Maya"},
    ],
    "billing_address": {
        "line1": "1 High St",
        "city": "Leeds",
        "postcode": "LS1 1AA",
        "country": "GB",
    },
}


@pytest.fixture
def admin_api(org):
    return client_for(org, MembershipFactory(organisation=org, role="admin").user)


def events(*types):
    return list(
        OutboxEvent.objects.filter(event_type__in=types).values_list("event_type", flat=True)
    )


# --- clients and quick add ------------------------------------------------------------------------


def test_quick_add_family_in_one_step(org, admin_api):
    """AC FR-05-1: client + primary contact + students in one transaction."""
    response = admin_api.post("/api/v1/clients/quick-add", FAMILY, format="json")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["display_name"] == "The Patel Family"
    assert (body["type"], body["currency"]) == ("household", "GBP")
    assert body["billing_address"]["postcode"] == "LS1 1AA"
    [contact] = body["contacts"]
    assert (contact["email"], contact["is_primary"], contact["is_bill_payer"]) == (
        "priya@example.com", True, True,
    )  # fmt: skip
    assert body["primary_contact"] == contact["id"]
    names = sorted((s["first_name"], s["last_name"]) for s in body["students"])
    assert names == [("Arjun", "Patel"), ("Maya", "Patel")]
    assert body["students_count"] == 2
    assert (
        events("client.created", "contact.created", "student.created").count("student.created") == 2
    )


def test_quick_add_is_all_or_nothing(org, admin_api):
    bad = {**FAMILY, "students": [{"first_name": "Arjun", "subjects": [{"subject": ""}]}]}
    assert admin_api.post("/api/v1/clients/quick-add", bad, format="json").status_code == 400
    with tenant_context(org):
        assert not Client.objects.exists()
        assert not Contact.objects.exists()


def test_quick_add_adult_learner(org, admin_api):
    body = admin_api.post(
        "/api/v1/clients/quick-add",
        {
            "contact": {"first_name": "Sam", "last_name": "Lee", "relationship": "self"},
            "students": [],
        },
        format="json",
    ).json()
    assert (body["type"], body["display_name"]) == ("individual", "Sam Lee")
    [student] = body["students"]
    assert student["contact"] == body["contacts"][0]["id"]


def test_archive_hides_client_and_archives_students(org, admin_api):
    client = ClientFactory(organisation=org)
    student = StudentFactory(organisation=org, client=client)
    assert admin_api.delete(f"/api/v1/clients/{client.pk}").status_code == 204
    assert str(client.pk) not in result_ids(admin_api.get("/api/v1/clients"))
    assert str(client.pk) in result_ids(admin_api.get("/api/v1/clients?include_archived=true"))
    with tenant_context(org):
        student.refresh_from_db()
    assert student.status == Student.Status.ARCHIVED
    assert admin_api.post(f"/api/v1/clients/{client.pk}/restore").json()["status"] == "active"
    # New students can't join an archived client.
    admin_api.delete(f"/api/v1/clients/{client.pk}")
    assert (
        admin_api.post(
            "/api/v1/students", {"client": str(client.pk), "first_name": "X"}, format="json"
        ).status_code
        == 422
    )


def test_client_search_and_filters(org, admin_api):
    patel = ClientFactory(organisation=org, display_name="The Patel Family")
    ContactFactory(organisation=org, client=patel, email="priya@example.com")
    ClientFactory(organisation=org, display_name="The Jones Family", status="prospect")
    assert result_ids(admin_api.get("/api/v1/clients?q=priya@")) == {str(patel.pk)}
    assert len(admin_api.get("/api/v1/clients?status=prospect").json()["results"]) == 1


def test_client_export_is_audited(org, admin_api):
    ClientFactory(organisation=org, display_name="=cmd|calc")
    response = admin_api.get("/api/v1/clients/export")
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0][:3] == ["id", "name", "type"]
    assert rows[1][1] == "'=cmd|calc"
    with tenant_context(org):
        assert AuditEntry.objects.filter(
            action="export", object_repr="people.client export"
        ).exists()


def test_client_tax_id_is_encrypted_and_permissioned(org, admin_api):
    created = admin_api.post(
        "/api/v1/clients",
        {"display_name": "Acme School", "type": "organisation", "tax_id": "GB123"},
        format="json",
    ).json()
    assert created["tax_id"] == "GB123"
    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    assert "tax_id" not in coordinator.get(f"/api/v1/clients/{created['id']}").json()


# --- contacts -------------------------------------------------------------------------------------


def test_add_contacts_and_change_primary(org, admin_api):
    client = ClientFactory(organisation=org)
    first = admin_api.post(
        f"/api/v1/clients/{client.pk}/contacts", {"first_name": "A"}, format="json"
    ).json()
    second = admin_api.post(
        f"/api/v1/clients/{client.pk}/contacts",
        {"first_name": "B", "phone": "0113 496 0000"},
        format="json",
    ).json()
    assert (first["is_primary"], second["is_primary"]) == (True, False)
    admin_api.patch(f"/api/v1/contacts/{second['id']}", {"is_primary": True}, format="json")
    contacts = {c["id"]: c for c in admin_api.get(f"/api/v1/clients/{client.pk}/contacts").json()}
    assert contacts[second["id"]]["is_primary"] is True
    assert contacts[first["id"]]["is_primary"] is False
    with tenant_context(org):
        assert str(Client.objects.get(pk=client.pk).primary_contact_id) == second["id"]


# --- students -------------------------------------------------------------------------------------


def test_student_status_changes_are_timestamped_and_announced(org, admin_api):
    student = StudentFactory(organisation=org)
    body = admin_api.post(
        f"/api/v1/students/{student.pk}/status", {"status": "waiting"}, format="json"
    ).json()
    assert body["status"] == "waiting"
    assert body["status_changed_at"] is not None
    event = OutboxEvent.objects.get(event_type="student.status_changed")
    assert event.payload["data"] == {"old_status": "active", "new_status": "waiting"}
    assert (
        admin_api.post(
            f"/api/v1/students/{student.pk}/status", {"status": "nope"}, format="json"
        ).status_code
        == 422
    )


def test_sensitive_student_data_is_encrypted_permissioned_and_read_logged(org, admin_api):
    from django.db import connection

    student = StudentFactory(organisation=org)
    admin_api.patch(
        f"/api/v1/students/{student.pk}",
        {"learning_needs": "Dyslexia; EpiPen", "date_of_birth": "2012-05-01"},
        format="json",
    )
    with tenant_context(org), connection.cursor() as cursor:
        cursor.execute("SELECT learning_needs FROM people_student WHERE id = %s", [student.pk])
        assert "EpiPen" not in cursor.fetchone()[0]
    body = admin_api.get(f"/api/v1/students/{student.pk}").json()
    assert body["learning_needs"] == "Dyslexia; EpiPen"
    with tenant_context(org):
        assert AuditEntry.objects.filter(action="read", object_id=str(student.pk)).exists()
    finance = client_for(org, MembershipFactory(organisation=org, role="finance").user)
    assert finance.get(f"/api/v1/students/{student.pk}").status_code in (403, 404)


def test_student_subject_filter(org, admin_api):
    maths = StudentFactory(organisation=org, subjects=[{"subject": "Maths", "level": "GCSE"}])
    StudentFactory(organisation=org, subjects=[{"subject": "English", "level": ""}])
    assert result_ids(admin_api.get("/api/v1/students?subject=Maths")) == {str(maths.pk)}


def test_tutors_see_no_students_until_they_have_jobs(org):
    StudentFactory(organisation=org)
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    response = tutor.get("/api/v1/students")
    assert response.status_code in (200, 403)
    if response.status_code == 200:
        assert response.json()["results"] == []


# --- branch scoping -------------------------------------------------------------------------------


def test_branch_restricted_staff_see_their_branch_only(org):
    from tutortrack.identity.services import set_branch_scope
    from tutortrack.tenancy.tests.factories import BranchFactory

    north = BranchFactory(organisation=org, code="N")
    mine = ClientFactory(organisation=org, branch=north)
    ClientFactory(organisation=org)  # default branch
    membership = MembershipFactory(organisation=org, role="branch_manager")
    with tenant_context(org):
        set_branch_scope(membership, Membership.BranchScope.SELECTED, [north])
    assert result_ids(client_for(org, membership.user).get("/api/v1/clients")) == {str(mine.pk)}


# --- tutors ---------------------------------------------------------------------------------------


def test_adding_a_tutor_invites_them_and_joining_links_the_profile(
    org, admin_api, django_capture_on_commit_callbacks
):
    from rest_framework.test import APIClient

    with django_capture_on_commit_callbacks(execute=True):
        created = admin_api.post(
            "/api/v1/tutors", {"email": "Nia@example.com", "first_name": "Nia"}, format="json"
        )
    assert created.status_code == 201, created.json()
    assert (created.json()["status"], created.json()["has_joined"]) == ("onboarding", False)
    with tenant_context(org):
        invitation = Invitation.objects.get(email="nia@example.com")
    assert (invitation.role, invitation.target_type) == ("tutor", "people.tutor")
    assert (
        admin_api.post(
            "/api/v1/tutors", {"email": "nia@example.com", "first_name": "N"}, format="json"
        ).status_code
        == 422
    )

    import re

    from django.core import mail

    token = re.search(r"token=(\S+)", mail.outbox[-1].body).group(1)
    APIClient(HTTP_HOST="brightminds.tutortrack.test").post(
        "/api/v1/invitations/accept",
        {"token": token, "first_name": "Nia", "password": "violet-harbour-lantern-42"},
        format="json",
    )
    dispatch_batch()  # user.joined -> link the profile
    body = admin_api.get(f"/api/v1/tutors/{created.json()['id']}").json()
    assert (body["has_joined"], body["status"]) == (True, "active")


def test_tutor_subjects_and_approval(org, admin_api):
    tutor = TutorProfileFactory(organisation=org)
    subjects = admin_api.put(
        f"/api/v1/tutors/{tutor.pk}/subjects",
        [{"subject": "Maths", "level": "A level"}],
        format="json",
    ).json()
    assert subjects[0]["approved"] is False
    approved = admin_api.post(
        f"/api/v1/tutors/{tutor.pk}/subjects/{subjects[0]['id']}/approve"
    ).json()
    assert approved["approved"] is True
    again = admin_api.put(
        f"/api/v1/tutors/{tutor.pk}/subjects",
        [{"subject": "Maths", "level": "A level"}, {"subject": "Physics"}],
        format="json",
    ).json()
    assert {(s["subject"], s["approved"]) for s in again} == {("Maths", True), ("Physics", False)}
    finance = client_for(org, MembershipFactory(organisation=org, role="finance").user)
    other = admin_api.get(f"/api/v1/tutors/{tutor.pk}").json()["subjects"]
    physics = next(s for s in other if s["subject"] == "Physics")
    approve_url = f"/api/v1/tutors/{tutor.pk}/subjects/{physics['id']}/approve"
    assert finance.post(approve_url).status_code == 403


def test_tutor_pay_and_tax_are_hidden_from_coordinators(org, admin_api):
    tutor = TutorProfileFactory(
        organisation=org, pay_rate_amount=Decimal("25.0000"), tax_reference="UTR 1"
    )
    assert admin_api.get(f"/api/v1/tutors/{tutor.pk}").json()["pay_rate_amount"] == "25.0000"
    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    body = coordinator.get(f"/api/v1/tutors/{tutor.pk}").json()
    assert "pay_rate_amount" not in body
    assert "tax_reference" not in body


def test_tutors_see_their_own_profile_only(org):
    membership = MembershipFactory(organisation=org, role="tutor")
    mine = TutorProfileFactory(organisation=org, membership=membership, email=membership.user.email)
    TutorProfileFactory(organisation=org)
    api = client_for(org, membership.user)
    assert result_ids(api.get("/api/v1/tutors")) == {str(mine.pk)}
    assert (
        api.patch(
            f"/api/v1/tutors/{mine.pk}", {"headline": "Maths whizz"}, format="json"
        ).status_code
        == 200
    )
    assert "pay_rate_amount" not in api.get(f"/api/v1/tutors/{mine.pk}").json()


# --- addresses, duplicates, consent subjects ----------------------------------------------------


def test_addresses_are_geocoded_in_the_background(
    org, settings, admin_api, django_capture_on_commit_callbacks
):
    from tutortrack.core import geo

    class FakeGeocoder:
        def geocode(self, address, country=""):
            return geo.GeoPoint(Decimal("53.800755"), Decimal("-1.549077"))

    with (
        mock.patch("tutortrack.core.geo.geocoder", return_value=FakeGeocoder()),
        django_capture_on_commit_callbacks(execute=True),
    ):
        body = admin_api.post("/api/v1/clients/quick-add", FAMILY, format="json").json()
    detail = admin_api.get(f"/api/v1/clients/{body['id']}").json()
    assert (detail["billing_address"]["lat"], detail["billing_address"]["lng"]) == (
        "53.800755",
        "-1.549077",
    )


def test_possible_duplicates(org, admin_api):
    contact = ContactFactory(organisation=org, email="priya@example.com", phone="+44 113 496 0000")
    student = StudentFactory(organisation=org, first_name="Arjun", last_name="Patel")
    found = admin_api.get("/api/v1/people/duplicates", {"email": "PRIYA@example.com"}).json()
    assert [(d["type"], d["id"]) for d in found] == [("contact", str(contact.pk))]
    by_phone = admin_api.get("/api/v1/people/duplicates", {"phone": "0113 496 0000"}).json()
    assert by_phone[0]["reason"] == "phone"
    by_name = admin_api.get(
        "/api/v1/people/duplicates", {"first_name": "arjun", "last_name": "PATEL"}
    ).json()
    assert by_name[0]["id"] == str(student.pk)


def test_people_are_consent_subjects(org):
    from tutortrack.privacy import services as privacy

    student = StudentFactory(organisation=org)
    with tenant_context(org):
        privacy.ensure_default_types()
        record = privacy.record_consent(
            subject_type="people.student",
            subject_id=str(student.pk),
            key="photo-video",
            granted=True,
            method="staff",
            on_behalf_of_child=True,
        )
    assert record.on_behalf_of_child is True


# --- isolation ------------------------------------------------------------------------------------


class TestClientIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/clients"

    def make_object(self, organisation):
        return ClientFactory(organisation=organisation)


class TestContactIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/contacts"

    def make_object(self, organisation):
        return ContactFactory(organisation=organisation)


class TestStudentIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/students"

    def make_object(self, organisation):
        return StudentFactory(organisation=organisation)


class TestTutorIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/tutors"

    def make_object(self, organisation):
        return TutorProfileFactory(organisation=organisation)


def test_quick_add_service_names_households():
    assert services.household_name("Patel") == "The Patel Family"
