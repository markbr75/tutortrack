"""G6 (FR-29-3): consent columns in imports become E29 consent records, with the import
recorded as their source."""

from __future__ import annotations

import pytest

from tutortrack.migration.models import ImportBatch
from tutortrack.people.models import Contact, Student
from tutortrack.privacy.models import ConsentRecord
from tutortrack.privacy.services import ensure_default_types

from .conftest import roll_back, run_import

pytestmark = pytest.mark.django_db
ROW = {
    "Client ID": "F9",
    "First name": "Jane",
    "Last name": "Smith",
    "Email": "jane.c@example.com",
    "Student first name": "Tom",
    "Newsletter": "yes",
    "SMS opt in": "no",
    "Photo consent": "yes",
}


def test_consent_columns_are_recorded_with_the_import_as_source(s3_tenant):
    ensure_default_types()
    batch = run_import("clients", [ROW])
    assert batch.status == ImportBatch.Status.COMPLETED, batch.stats
    contact = Contact.objects.get(email="jane.c@example.com")
    student = Student.objects.get(first_name="Tom", client=contact.client)
    records = ConsentRecord.objects.select_related("consent_type")
    email = records.get(consent_type__key="marketing-email")
    assert (email.subject_id, email.granted, email.method) == (str(contact.pk), True, "import")
    assert email.source == f"import:file:{batch.pk}"
    assert email.given_by_name == "Imported from file"
    assert records.get(consent_type__key="marketing-sms").granted is False
    photo = records.get(consent_type__key="photo-video")
    assert (photo.subject_id, photo.on_behalf_of_child) == (str(student.pk), True)


def test_reimporting_adds_no_duplicates_and_rollback_removes_the_records(s3_tenant):
    ensure_default_types()
    first = run_import("clients", [ROW])
    records = ConsentRecord.objects.all()
    assert records.count() == 3
    again = run_import("clients", [ROW])
    assert again.status == ImportBatch.Status.COMPLETED
    assert records.count() == 3  # the same state is not recorded twice
    roll_back(first)
    assert not records.exists()


def test_student_import_records_photo_consent(s3_tenant):
    ensure_default_types()
    batch = run_import(
        "students",
        [{"First name": "Ada", "Parent email": "p@example.com", "Photo consent": "y"}],
    )
    assert batch.status == ImportBatch.Status.COMPLETED, batch.stats
    record = ConsentRecord.objects.get()
    assert record.subject_id == str(Student.objects.get(first_name="Ada").pk)
