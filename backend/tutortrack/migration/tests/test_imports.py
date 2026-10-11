"""E28-T01..T04: the import pipeline and the entity importers (FR-28-1)."""

from __future__ import annotations

import os
import time as clock
from datetime import timedelta
from decimal import Decimal

import pytest

from tutortrack.billing.models import ClientLedgerEntry, Invoice
from tutortrack.billing.selectors import has_opening_balance
from tutortrack.catalogue.models import Service
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.core.time import now
from tutortrack.crm.models import Note, TaggedItem
from tutortrack.jobs.models import Job
from tutortrack.leads.models import Enquiry
from tutortrack.migration import files, services
from tutortrack.migration.models import ExternalRef, ImportBatch, ImportRow
from tutortrack.payments.models import Payment
from tutortrack.people.models import Client, Contact, Student, TutorProfile
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, StudentFactory
from tutortrack.scheduling.models import AvailabilityWindow, Lesson, LessonSeries

from .conftest import make_batch, roll_back, run_import, validate

pytestmark = pytest.mark.django_db
B = ImportBatch.Status
R = ImportRow.Status


def statuses(batch: ImportBatch) -> list[str]:
    return list(batch.rows.order_by("row_number").values_list("status", flat=True))


# --- clients and households ---------------------------------------------------------------------


def test_household_rows_make_one_client_with_contacts_and_students(s3_tenant):
    batch = run_import(
        "clients",
        [
            {
                "Client ID": "F1",
                "Family": "The Smiths",
                "First name": "Jane",
                "Last name": "Smith",
                "Email": "jane@example.com",
                "Postcode": "SW1A 1AA",
                "Student first name": "Tom",
                "Labels": "VIP",
            },
            {
                "Client ID": "F1",
                "First name": "John",
                "Last name": "Smith",
                "Email": "john@example.com",
                "Student first name": "Lily",
            },
            {
                "Client ID": "F2",
                "First name": "Omar",
                "Last name": "Khan",
                "Email": "omar@example.com",
            },
        ],
    )
    assert batch.status == B.COMPLETED
    assert batch.stats["will"]["people.client"] == {"create": 2}
    smiths = Client.objects.get(display_name="The Smiths")
    assert sorted(c.first_name for c in smiths.contacts.all()) == ["Jane", "John"]
    assert sorted(s.first_name for s in smiths.students.all()) == ["Lily", "Tom"]
    assert smiths.billing_address.postcode == "SW1A 1AA"
    assert TaggedItem.objects.filter(target_id=str(smiths.pk)).count() == 1
    assert ExternalRef.objects.filter(system="file", external_id="F1").count() == 1
    # Created through the people services: audited, with domain events.
    assert AuditEntry.objects.filter(object_id=str(smiths.pk), action="create").exists()
    assert OutboxEvent.objects.filter(event_type="client.created").count() == 2


def test_upsert_by_email_updates_and_rollback_restores(s3_tenant):
    client = ClientFactory(organisation=s3_tenant, display_name="Old name")
    ContactFactory(organisation=s3_tenant, client=client, first_name="Ann", email="ann@example.com")
    batch = run_import(
        "clients", [{"Family": "New name", "First name": "Ann", "Email": "ann@example.com"}]
    )
    assert batch.stats["updated"] == 1
    client.refresh_from_db()
    assert client.display_name == "New name"
    result = roll_back(batch)
    assert result == {"reverted": 1, "kept": 0}
    client.refresh_from_db()
    assert client.display_name == "Old name"


def test_invalid_rows_are_reported_and_left_out(s3_tenant):
    batch = run_import(
        "tutors",
        [
            {"Email": "a@example.com", "First name": "Alex"},
            {"Email": "not-an-email", "First name": "Bo"},
            {"Email": "c@example.com", "First name": ""},
            {"Email": "a@example.com", "First name": "Alex again"},
        ],
    )
    assert statuses(batch) == [R.CREATED, R.INVALID, R.INVALID, R.INVALID]
    assert batch.stats["imported"] == 1
    assert batch.stats["invalid"] == 3
    report = files.read(batch.error_file).decode("utf-8-sig")
    assert "Not a valid email address" in report
    assert "First name is required" in report
    assert "appears earlier in the file" in report
    tutor = TutorProfile.objects.get(email="a@example.com")
    assert tutor.membership is None  # imported tutors are invited later (cutover step)


def test_dry_run_counts_creates_and_updates(s3_tenant):
    TutorProfile.objects.create(email="known@example.com", first_name="Known")
    batch = validate(
        make_batch(
            "tutors",
            [
                {"Email": "known@example.com", "First name": "K"},
                {"Email": "n@example.com", "First name": "N"},
            ],
        )
    )
    assert batch.status == B.VALIDATED
    assert batch.stats["actions"] == {"update": 1, "create": 1}
    assert not TutorProfile.objects.filter(email="n@example.com").exists()  # nothing written yet


def test_students_create_households_from_parent_columns(s3_tenant):
    existing = ClientFactory(organisation=s3_tenant)
    ContactFactory(organisation=s3_tenant, client=existing, email="kim@example.com")
    batch = run_import(
        "students",
        [
            {
                "First name": "Ava",
                "Last name": "Brown",
                "Parent email": "kate@example.com",
                "Parent first name": "Kate",
                "Status": "Waiting List",
                "Subjects": "Maths: GCSE; Physics",
            },
            {"First name": "Noah", "Last name": "Brown", "Parent email": "kate@example.com"},
            {"First name": "Mia", "Last name": "Lee", "Parent email": "kim@example.com"},
            {"First name": "Sam", "Last name": "Adult"},
        ],
        preset="tutorbird",
    )
    assert batch.stats["imported"] == 4, list(batch.rows.values_list("errors", flat=True))
    ava = Student.objects.get(first_name="Ava")
    assert ava.status == "waiting"  # TutorBird status word mapped by the preset
    assert ava.subjects == [
        {"subject": "Maths", "level": "GCSE"},
        {"subject": "Physics", "level": ""},
    ]
    assert Student.objects.get(first_name="Noah").client_id == ava.client_id
    assert Student.objects.get(first_name="Mia").client_id == existing.pk
    assert Student.objects.get(first_name="Sam").client.type == "individual"


def test_duplicate_students_are_flagged_and_skipped(s3_tenant):
    client = ClientFactory(organisation=s3_tenant, display_name="The Lees")
    StudentFactory(organisation=s3_tenant, client=client, first_name="Mia", last_name="Lee")
    batch = run_import(
        "students", [{"First name": "Mia", "Last name": "Lee", "Client": "The Lees"}]
    )
    row = batch.rows.get()
    assert row.status == R.SKIPPED
    assert "Already a student" in row.warnings[0]["message"]


def test_value_mapping_and_custom_fields(s3_tenant):
    from tutortrack.crm import services as crm

    crm.save_custom_field(
        None, entity_type="people.student", key="house", label="House", type="text"
    )
    batch = run_import(
        "students",
        [{"First name": "Ella", "Parent email": "p@example.com", "State": "Gone", "House": "Red"}],
        column_map={
            "First name": "first_name",
            "Parent email": "parent_email",
            "State": "status",
            "House": "cf.house",
        },
        value_map={"status": {"Gone": "finished"}},
    )
    student = Student.objects.get(first_name="Ella")
    assert student.status == "finished"
    assert student.custom_fields == {"house": "Red"}
    assert batch.stats["imported"] == 1


# --- services, jobs and lessons -----------------------------------------------------------------


def _people(tenant):
    run_import(
        "clients",
        [
            {
                "Client ID": "C1",
                "First name": "Jane",
                "Last name": "Smith",
                "Student first name": "Tom",
                "Email": "jane@example.com",
            }
        ],
    )
    run_import(
        "tutors",
        [
            {
                "Tutor ID": "T1",
                "Email": "alex@example.com",
                "First name": "Alex",
                "Last name": "Jones",
            }
        ],
    )
    run_import(
        "services",
        [{"Name": "GCSE Maths", "Duration": "60", "Charge rate": "£45.00", "Pay rate": "25"}],
    )


def test_services_jobs_and_upsert_by_name(s3_tenant):
    _people(s3_tenant)
    service = Service.objects.get(name="GCSE Maths")
    assert service.charge_rate.amount == Decimal("45.00")
    batch = run_import("services", [{"Name": "GCSE Maths", "Charge rate": "50"}])
    assert batch.stats["updated"] == 1
    service.refresh_from_db()
    assert service.charge_rate.amount == Decimal("50.00")
    job_batch = run_import(
        "jobs",
        [
            {
                "Job ID": "J1",
                "Client ID": "C1",
                "Students": "Tom Smith",
                "Service": "GCSE Maths",
                "Tutor email": "alex@example.com",
                "Charge rate": "48",
                "Status": "active",
            }
        ],
    )
    assert job_batch.stats["imported"] == 1, job_batch.rows.get().errors
    job = Job.objects.get()
    assert job.status == "active"
    assert job.charge_rate.amount == Decimal("48.00")
    assert job.tutors.get().tutor.email == "alex@example.com"


def test_lessons_history_and_weekly_series(s3_tenant):
    _people(s3_tenant)
    run_import(
        "jobs", [{"Job ID": "J1", "Client ID": "C1", "Service": "GCSE Maths", "Tutor ID": "T1"}]
    )
    today = now().date()
    rows = [
        {
            "Job ID": "J1",
            "Date": (today - timedelta(days=14)).isoformat(),
            "Start": "16:00",
            "End": "17:00",
            "Status": "completed",
        },
        {
            "Job ID": "J1",
            "Date": (today - timedelta(days=7)).isoformat(),
            "Start": "16:00",
            "End": "17:00",
        },
    ]
    rows += [
        {
            "Job ID": "J1",
            "Date": (today + timedelta(days=7 * w + 1)).isoformat(),
            "Start": "16:00",
            "End": "17:00",
        }
        for w in range(4)
    ]
    rows.append(
        {
            "Job ID": "J1",
            "Date": (today + timedelta(days=3)).isoformat(),
            "Start": "10:00",
            "Duration": "45",
        }
    )
    batch = run_import("lessons", rows, options={"cutover_date": today.isoformat()})
    assert batch.stats["will"]["scheduling.lessonseries"] == {"create": 1}
    assert batch.stats["imported"] == 4  # 2 history, 1 series, 1 single
    history = Lesson.objects.filter(start__date__lt=today)
    assert history.count() == 2
    assert {lesson.status for lesson in history} == {"completed"}
    assert all(lesson.lock_state == "paid" for lesson in history)
    series = LessonSeries.objects.get()
    assert series.until == today + timedelta(days=22)
    assert series.lessons.count() == 4
    # History never creates charges or pay, and imports don't notify anyone.
    from tutortrack.billing.models import Charge
    from tutortrack.billing.services import sync_lesson_charges

    for lesson in history:
        assert sync_lesson_charges(lesson.pk) == []
    assert not Charge.objects.exists()
    assert all(
        e.payload["data"].get("notify") is False
        for e in OutboxEvent.objects.filter(
            event_type__in=["lesson.scheduled", "lesson_series.created"]
        )
    )
    result = roll_back(batch)
    assert result["reverted"] == 4
    assert not Lesson.objects.exists()
    assert not LessonSeries.objects.exists()


# --- finance --------------------------------------------------------------------------------------


def test_opening_balances_invoices_payments_and_packages(s3_tenant):
    run_import(
        "clients",
        [
            {"Client ID": "C1", "First name": "Jane", "Email": "jane@example.com"},
            {"Client ID": "C2", "First name": "Omar"},
        ],
    )
    batch = run_import(
        "opening_balances",
        [
            {"Client ID": "C1", "Balance": "90.00"},
            {"Client ID": "C2", "Balance": "-30", "Type": ""},
        ],
    )
    assert batch.stats["updated"] == 2
    c1 = ExternalRef.objects.get(external_id="C1").target_id
    ledger = ClientLedgerEntry.objects.filter(client_id=c1)
    assert [e.amount.amount for e in ledger] == [Decimal("90.00")]
    assert has_opening_balance(Client.objects.get(pk=c1))
    again = run_import("opening_balances", [{"Client ID": "C1", "Balance": "90.00"}])
    assert again.rows.get().status == R.SKIPPED  # idempotent: one opening balance per client

    invoices = run_import(
        "invoices",
        [
            {
                "Invoice #": "INV-9",
                "Client ID": "C1",
                "Date": "2026-09-01",
                "Total": "90",
                "Paid": "0",
                "Status": "Unpaid",
            },
            {
                "Invoice #": "INV-8",
                "Client ID": "C1",
                "Date": "2026-08-01",
                "Total": "60",
                "Status": "Paid",
            },
        ],
        preset="tutorbird",
    )
    assert invoices.stats["created"] == 2
    open_invoice = Invoice.objects.get(number="INV-9")
    assert open_invoice.status == "issued"
    assert open_invoice.balance_due.amount == Decimal("90.00")
    assert Invoice.objects.get(number="INV-8").status == "paid"
    assert ledger.count() == 1  # history: no ledger entries for imported invoices

    payments = run_import(
        "payments",
        [
            {
                "Client ID": "C1",
                "Amount": "90",
                "Date": "2026-10-02",
                "Invoice number": "INV-9",
                "Reference": "BACS 1",
            }
        ],
    )
    assert payments.stats["created"] == 1, payments.rows.get().errors
    open_invoice.refresh_from_db()
    assert open_invoice.status == "paid"
    dup = run_import(
        "payments",
        [{"Client ID": "C1", "Amount": "90", "Date": "2026-10-02", "Reference": "BACS 1"}],
    )
    assert dup.rows.get().status == R.SKIPPED

    packages = run_import(
        "packages",
        [
            {
                "Client ID": "C2",
                "Package": "10 hours",
                "Remaining value": "135",
                "Remaining hours": "3",
            }
        ],
    )
    assert packages.stats["updated"] == 1
    c2 = ExternalRef.objects.get(external_id="C2").target_id
    assert sum(e.amount.amount for e in ClientLedgerEntry.objects.filter(client_id=c2)) == Decimal(
        "-165.00"
    )

    # Rolling back financial imports reverses, never deletes.
    assert roll_back(payments) == {"reverted": 1, "kept": 0}
    assert Payment.objects.get().status == "refunded"
    assert roll_back(batch)["reverted"] == 2
    assert not has_opening_balance(Client.objects.get(pk=c1))
    assert roll_back(invoices)["kept"] == 1  # INV-9 had money recorded against it
    assert Invoice.objects.get(number="INV-8").status == "void"


# --- tags, notes, enquiries, availability -------------------------------------------------------


def test_tags_notes_enquiries_and_availability(s3_tenant):
    run_import("clients", [{"Client ID": "C1", "First name": "Jane", "Email": "jane@example.com"}])
    run_import("tutors", [{"Email": "alex@example.com", "First name": "Alex"}])
    tags = run_import("tags", [{"Type": "client", "ID": "C1", "Tags": "VIP; Sibling discount"}])
    assert tags.stats["updated"] == 1
    assert TaggedItem.objects.count() == 2
    notes = run_import(
        "notes",
        [
            {
                "Type": "tutor",
                "Email": "alex@example.com",
                "Note": "Great <b>tutor</b>",
                "Date": "2025-01-31",
            }
        ],
    )
    assert notes.stats["created"] == 1
    assert "2025-01-31" in Note.objects.get().body
    enquiries = run_import(
        "enquiries",
        [
            {
                "First name": "Sam",
                "Email": "sam@example.com",
                "Student": "Ava",
                "Subjects": "English: KS3",
            }
        ],
    )
    enquiry = Enquiry.objects.get()
    assert enquiry.source == "import"
    assert enquiries.stats["created"] == 1
    availability = run_import(
        "availability",
        [
            {"Tutor email": "alex@example.com", "Day": "Monday", "From": "15:00", "To": "19:00"},
            {"Tutor email": "alex@example.com", "Day": "Wed", "From": "3:30 PM", "To": "6pm"},
        ],
    )
    assert availability.stats["updated"] == 2, list(
        availability.rows.values_list("errors", flat=True)
    )
    assert AvailabilityWindow.objects.count() == 2
    for batch in (availability, enquiries, notes, tags):
        roll_back(batch)
    assert not TaggedItem.objects.exists()
    assert not Note.objects.exists()
    assert not Enquiry.objects.exists()
    assert not AvailabilityWindow.objects.exists()


# --- rollback rules -----------------------------------------------------------------------------


def test_records_changed_after_the_import_are_kept(s3_tenant):
    batch = run_import(
        "tutors",
        [
            {"Email": "a@example.com", "First name": "A"},
            {"Email": "b@example.com", "First name": "B"},
        ],
    )
    from tutortrack.people import services as people

    clock.sleep(2.1)
    people.update_tutor(TutorProfile.objects.get(email="a@example.com"), headline="Edited")
    assert roll_back(batch) == {"reverted": 1, "kept": 1}
    assert list(TutorProfile.objects.values_list("email", flat=True)) == ["a@example.com"]
    assert statuses(ImportBatch.objects.get(pk=batch.pk)) == [R.KEPT, R.ROLLED_BACK]


def test_rollback_window_and_finalise(s3_tenant):
    batch = run_import("tutors", [{"Email": "a@example.com", "First name": "A"}])
    assert batch.can_rollback
    assert batch.rollback_until.date() == (now() + timedelta(days=7)).date()
    assert services.finalise(batch.pk)
    batch.refresh_from_db()
    assert batch.status == B.FINALISED
    assert not batch.can_rollback
    from tutortrack.core.exceptions import Conflict

    with pytest.raises(Conflict):
        services.request_rollback(batch)


def test_rows_are_idempotent(s3_tenant):
    batch = validate(make_batch("tutors", [{"Email": "a@example.com", "First name": "A"}]))
    services.start_import(batch.pk)
    services.import_chunk(batch.pk, 0, 10)
    services.import_chunk(batch.pk, 0, 10)  # a retried activity
    assert TutorProfile.objects.count() == 1


def test_template_lists_the_fields_and_reimports(s3_tenant):
    text = services.template_csv("students").decode("utf-8-sig")
    header = text.splitlines()[0]
    assert "First name" in header
    assert "Parent email" in header
    from tutortrack.migration import parsing

    table = parsing.parse(text.encode(), filename="t.csv")
    batch = make_batch("students", table.rows, headers=table.headers)
    assert batch.mapping["First name"] == "first_name"
    assert batch.mapping["Parent email"] == "parent_email"


def test_saved_mappings_are_reused(s3_tenant):
    batch = make_batch(
        "tutors", [{"E": "a@example.com", "F": "A"}], column_map={"E": "email", "F": "first_name"}
    )
    saved = services.save_mapping(batch, name="Our sheet", user=None)
    from django.db import transaction

    with transaction.atomic():
        again = services.create_batch(
            user=None,
            entity="tutors",
            headers=["E", "F"],
            rows=[{"E": "b@example.com", "F": "B"}],
            source="csv",
            saved_mapping=saved,
        )
    assert again.mapping == {"E": "email", "F": "first_name"}


# --- FR-28-1 AC: 5,000 students with 12 invalid rows in under two minutes ----------------------
# The full-size timed run is opt-in (PERF_TESTS=1): shared CI runners are too slow and noisy for
# a wall-clock assertion. By default the same import runs with 600 rows.

PERF = bool(os.environ.get("PERF_TESTS"))
SIZE = 5000 if PERF else 600
BAD = {5 + k * (SIZE // 12) for k in range(12)}  # 12 rows with an invalid email


def test_five_thousand_students_with_twelve_invalid_rows(s3_tenant):
    rows = []
    for i in range(SIZE):
        family = i // 2
        rows.append(
            {
                "First name": f"Student{i}",
                "Last name": f"Family{family}",
                "Parent email": "broken" if i in BAD else f"parent{family}@example.com",
                "Date of birth": "2012-03-04",
            }
        )
    started = clock.monotonic()
    batch = run_import("students", rows)
    elapsed = clock.monotonic() - started
    assert batch.stats["invalid"] == 12
    assert batch.stats["imported"] == SIZE - 12
    assert Student.objects.count() == SIZE - 12
    report = files.read(batch.error_file).decode("utf-8-sig").splitlines()
    assert len(report) == 13  # header + 12 rows with their reasons
    if PERF:
        assert elapsed < 120, elapsed
    assert Contact.objects.count() <= SIZE // 2
