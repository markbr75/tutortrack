"""Editing a person's details from their record (follow-up to ADR 0045): tutors, students,
clients and contacts update through PATCH, and renaming yourself on your account renames
your own tutor record."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import AuditEntry
from tutortrack.people.models import TutorProfile
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)

pytestmark = pytest.mark.django_db


def test_a_tutor_record_is_edited_and_audited(org, api):
    with tenant_context(org):
        tutor = TutorProfileFactory(organisation=org, first_name="Nia", phone="")
    edited = api.patch(
        f"/api/v1/tutors/{tutor.pk}",
        {"first_name": "Niamh", "last_name": "Adeyemi", "phone": "07700 900123", "invite": False},
        format="json",
    )
    assert edited.status_code == 200, edited.json()
    assert (edited.json()["full_name"], edited.json()["phone"]) == (
        "Niamh Adeyemi",
        "07700 900123",
    )
    with tenant_context(org):
        assert AuditEntry.objects.filter(object_id=str(tutor.pk), action="update").exists()


def test_a_student_record_is_edited(org, api):
    with tenant_context(org):
        student = StudentFactory(organisation=org, first_name="Arjun", school="")
    edited = api.patch(
        f"/api/v1/students/{student.pk}",
        {"preferred_name": "AJ", "school": "Hill Park", "year_group": "Year 10"},
        format="json",
    )
    assert edited.status_code == 200, edited.json()
    assert (edited.json()["school"], edited.json()["year_group"]) == ("Hill Park", "Year 10")


def test_a_client_and_its_contact_are_edited(org, api):
    with tenant_context(org):
        client = ClientFactory(organisation=org, display_name="Patel family")
        contact = ContactFactory(organisation=org, client=client, first_name="Priya")
    renamed = api.patch(
        f"/api/v1/clients/{client.pk}",
        {"display_name": "The Patel family", "po_number": "PO-17", "payment_terms_days": 30},
        format="json",
    )
    assert renamed.status_code == 200, renamed.json()
    assert renamed.json()["display_name"] == "The Patel family"
    edited = api.patch(
        f"/api/v1/contacts/{contact.pk}",
        {"first_name": "Priyanka", "mobile": "07700 900456"},
        format="json",
    )
    assert edited.status_code == 200, edited.json()
    assert edited.json()["full_name"].startswith("Priyanka")


def test_renaming_yourself_renames_your_own_tutor_record(org, api, user):
    mine = api.post("/api/v1/tutors/add-me").json()
    with tenant_context(org):
        other = TutorProfileFactory(organisation=org, first_name="Sam", last_name="Clarke")
    response = api.patch(
        "/api/v1/me", {"first_name": "Robin", "last_name": "Hale"}, format="json"
    )
    assert response.status_code == 200, response.json()
    with tenant_context(org):
        dispatch_batch()
        assert TutorProfile.objects.get(pk=mine["id"]).full_name == "Robin Hale"
        assert TutorProfile.objects.get(pk=other.pk).full_name == "Sam Clarke"
        # Idempotent: handling the event again changes nothing.
        dispatch_batch()
        assert TutorProfile.objects.get(pk=mine["id"]).full_name == "Robin Hale"


def test_changing_other_account_details_leaves_the_tutor_record_alone(org, api, user):
    from tutortrack.core.models import OutboxEvent

    api.post("/api/v1/tutors/add-me")
    api.patch("/api/v1/me", {"pronouns": "they/them"}, format="json")
    with tenant_context(org):
        assert not OutboxEvent.objects.filter(event_type="membership.renamed").exists()
