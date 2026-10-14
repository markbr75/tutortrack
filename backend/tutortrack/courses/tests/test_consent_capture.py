"""G6 (FR-29-3): terms and consents ticked when enrolling online are E29 consent records."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.testing import client_for
from tutortrack.courses.models import Enrolment
from tutortrack.privacy.models import ConsentRecord
from tutortrack.privacy.services import ensure_default_types

from .test_courses import future_class, world  # noqa: F401 - the world fixture

pytestmark = pytest.mark.django_db


def enrol_body(group_class, **extra):
    return {
        "group_class": str(group_class.pk),
        "contact": {"first_name": "Sam", "last_name": "Okafor", "email": "sam@example.com"},
        "student": {"first_name": "Tobi"},
        **extra,
    }


def test_online_enrolment_records_terms_and_ticked_consents(org, world):  # noqa: F811
    group_class = future_class(org, world)
    with tenant_context(org):
        ensure_default_types()
    body = enrol_body(group_class, accept_terms=True, consents=["photo-video", "marketing-email"])
    response = client_for(org, None).post("/api/v1/public/enrol", body, format="json")
    assert response.status_code == 201, response.json()
    with tenant_context(org):
        enrolment = Enrolment.objects.get(pk=response.json()["id"])
        records = {
            (r.consent_type.key, r.subject_type): r
            for r in ConsentRecord.objects.select_related("consent_type")
        }
        assert set(records) == {
            ("terms", "people.contact"),
            ("marketing-email", "people.contact"),
            ("photo-video", "people.student"),
        }
        photo = records[("photo-video", "people.student")]
        assert photo.subject_id == str(enrolment.student_id)
        assert photo.on_behalf_of_child
        assert photo.given_by_name == "Sam Okafor"
        assert photo.source == f"enrolment:{group_class.pk}"
        assert {r.method for r in records.values()} == {"form"}


def test_joining_the_waitlist_records_the_terms(org, world):  # noqa: F811
    group_class = future_class(org, world)
    with tenant_context(org):
        ensure_default_types()
    body = enrol_body(group_class, accept_terms=True, join_waitlist=True)
    response = client_for(org, None).post("/api/v1/public/enrol", body, format="json")
    assert response.status_code == 201, response.json()
    with tenant_context(org):
        record = ConsentRecord.objects.select_related("consent_type").get()
        assert (record.consent_type.key, record.subject_type) == ("terms", "people.contact")


def test_no_ticks_no_records(org, world):  # noqa: F811
    group_class = future_class(org, world)
    response = client_for(org, None).post(
        "/api/v1/public/enrol", enrol_body(group_class), format="json"
    )
    assert response.status_code == 201, response.json()
    with tenant_context(org):
        assert not ConsentRecord.objects.exists()
