"""E29-T06: the erasure / anonymisation engine across the apps (FR-29-4)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection, transaction

from tutortrack.billing import services as billing
from tutortrack.billing.models import Invoice, InvoiceLine
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, OutboxEvent, StoredFile
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.crm.models import Document, Note
from tutortrack.crm.selectors import search
from tutortrack.identity.models import Membership
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.people.models import Client, Contact, Student
from tutortrack.privacy import erasure, holds, registry
from tutortrack.privacy.models import ErasureRecord

pytestmark = pytest.mark.django_db


def _file(org, s3, name="report.pdf"):
    key = f"org/{org.pk}/test/{name}"
    s3.put_object(Bucket="tutortrack-test", Key=key, Body=b"%PDF-1.4 test")
    with tenant_context(org):
        return StoredFile.objects.create(
            filename=name,
            content_type="application/pdf",
            size_bytes=13,
            storage_key=key,
            status=StoredFile.Status.UPLOADED,
            scan_status=StoredFile.ScanStatus.CLEAN,
        )


def _invoice(org, family, description, *, issued_days_ago=0):
    with tenant_context(org), transaction.atomic():
        billing.create_ad_hoc_charge(
            client=family.client,
            description=description,
            unit_price=Money(Decimal("25.00"), "GBP"),
            student=family.student,
        )
        invoice = billing.create_draft(family.client)
        invoice = billing.issue_invoice(invoice, send=False)
        if issued_days_ago:
            Invoice.objects.filter(pk=invoice.pk).update(
                issue_date=(now() - timedelta(days=issued_days_ago)).date()
            )
        return Invoice.objects.get(pk=invoice.pk)


def test_every_app_with_personal_data_registers_a_provider():
    keys = {p.key for p in registry.providers()}
    assert {
        "people",
        "identity",
        "crm",
        "comms",
        "billing",
        "payments",
        "scheduling",
        "jobs",
        "delivery",
        "learning",
        "courses",
        "leads",
        "recruitment",
        "growth",
        "payroll",
        "privacy",
        "calendar_sync",
        "migration",
        "sites",
        "developer",
        "ai",
    } <= keys


def test_a_client_expands_to_its_contacts_students_and_logins(org, family):
    with tenant_context(org):
        person = registry.resolve("people.client", str(family.client.pk))
    assert person.of("people.contact") == [str(family.contact.pk)]
    assert person.of("people.student") == [str(family.student.pk)]
    assert person.of("identity.user") == [str(family.parent.pk)]
    assert "priya@example.com" in person.emails
    assert "Arjun Patel" in person.names


def test_a_student_does_not_expand_to_their_household(org, family):
    with tenant_context(org):
        person = registry.resolve("people.student", str(family.student.pk))
    assert person.of("people.client") == []
    assert person.context["people.client"] == {str(family.client.pk)}


def test_erasing_a_student_meets_the_acceptance_criteria(org, family, s3):
    """AC: erasing a student removes name/DOB/notes/files, replaces it with "Erased Student
    #n", keeps invoice lines with an anonymised description, and the student no longer
    appears in search or exports."""
    attachment = _file(org, s3, "assessment.pdf")
    with tenant_context(org):
        Note.objects.create(
            target_type="people.student",
            target_id=str(family.student.pk),
            body="Arjun finds fractions hard",
        )
        Document.objects.create(
            target_type="people.student",
            target_id=str(family.student.pk),
            file=attachment,
            title="Educational psychologist report",
        )
    invoice = _invoice(org, family, "Maths workbook for Arjun Patel")

    with tenant_context(org):
        record = erasure.erase_now("people.student", str(family.student.pk))
        student = Student.objects.get(pk=family.student.pk)
        label = record.labels[f"people.student:{family.student.pk}"]
        assert label.startswith("Erased Student #")
        assert student.full_name == label
        assert student.date_of_birth is None
        assert student.school == ""
        assert student.learning_needs == ""
        assert student.goals == ""
        assert student.archived_at is not None
        assert not Note.objects.filter(target_id=str(family.student.pk)).exists()
        assert not Document.objects.filter(target_id=str(family.student.pk)).exists()
        stored = StoredFile.objects.get(pk=attachment.pk)
        assert stored.filename == "erased"
        assert "Contents" not in s3.list_objects_v2(
            Bucket="tutortrack-test", Prefix=attachment.storage_key
        )
        # Financial records stay, with the name anonymised.
        line = InvoiceLine.objects.get(invoice=invoice)
        assert line.student_name == label
        assert line.description == f"Maths workbook for {label}"
        assert line.gross == invoice.total
        assert Invoice.objects.get(pk=invoice.pk).status == invoice.status
        # Gone from search, and the family (not erased) is untouched.
        owner = MembershipFactory(organisation=org, role="owner").user
        assert not [h for h in search(owner, "Arjun") if h.type == "student"]
        assert Contact.objects.get(pk=family.contact.pk).first_name == "Priya"
        assert Client.objects.get(pk=family.client.pk).display_name == "The Patels"
        assert record.status == ErasureRecord.Status.COMPLETED
        assert record.scrub_terms == ""  # personal search terms are dropped when done
        entry = AuditEntry.objects.get(object_id=str(record.pk), action="erase")
        assert entry.changes["anonymised"] > 0
        assert OutboxEvent.objects.filter(event_type="data_subject.erased").exists()


def test_erasing_a_student_scrubs_their_name_from_job_names_and_search(org, family):
    """Release test 2026-10-28 (TP-E29-031): the job named after the student loses the name."""
    from tutortrack.catalogue.tests.factories import ServiceFactory
    from tutortrack.jobs import services as jobs
    from tutortrack.jobs.models import Job

    with tenant_context(org):
        job = jobs.create_job(
            client=family.client,
            service=ServiceFactory(organisation=org),
            students=[{"student": family.student}],
            name="GCSE Maths – Arjun Patel",
            notes_for_tutor="Arjun likes worked examples",
        )
        record = erasure.erase_now("people.student", str(family.student.pk))
        label = record.labels[f"people.student:{family.student.pk}"]
        job = Job.objects.get(pk=job.pk)
        assert job.name == f"GCSE Maths – {label}"
        assert "Arjun" not in job.notes_for_tutor
        owner = MembershipFactory(organisation=org, role="owner").user
        assert not [h for h in search(owner, "Arjun Patel") if h.type == "job"]


def test_erased_student_has_no_personal_data_left_in_the_export(org, family, s3):

    with tenant_context(org):
        erasure.erase_now("people.student", str(family.student.pk))
        person = registry.resolve("people.student", str(family.student.pk))
        exported = {
            s.key: s.records for p in registry.providers() if p.export for s in p.export(person)
        }
    student = exported["people.students"][0]
    assert "Arjun" not in str(student)
    assert student["date_of_birth"] is None


def test_a_legal_hold_blocks_erasure(org, family, owner):
    with tenant_context(org):
        holds.place(
            subject_type="people.client",
            subject_id=str(family.client.pk),
            reason="Fee dispute",
            user=owner,
        )
        with pytest.raises(erasure.ErasureBlocked):
            erasure.erase_now("people.student", str(family.student.pk))
        assert Student.objects.get(pk=family.student.pk).first_name == "Arjun"
        assert ErasureRecord.objects.get().status == ErasureRecord.Status.BLOCKED


def test_released_holds_no_longer_block(org, family, owner):
    with tenant_context(org):
        hold = holds.place(
            subject_type="people.student",
            subject_id=str(family.student.pk),
            reason="Police enquiry",
            user=owner,
        )
        holds.release(hold, reason="Enquiry closed", user=owner)
        record = erasure.erase_now("people.student", str(family.student.pk))
    assert record.status == ErasureRecord.Status.COMPLETED


def test_erasing_a_client_keeps_recent_invoice_details_until_the_retention_period(org, family):
    recent = _invoice(org, family, "October lessons")
    old = _invoice(org, family, "Lessons in 2018", issued_days_ago=365 * 7)
    with tenant_context(org):
        record = erasure.erase_now("people.client", str(family.client.pk))
        label = record.labels[f"people.client:{family.client.pk}"]
        assert Client.objects.get(pk=family.client.pk).display_name == label
        assert Contact.objects.get(pk=family.contact.pk).email == ""
        # A recent invoice keeps the bill payer (legal requirement); an old one doesn't.
        assert Invoice.objects.get(pk=recent.pk).billing_snapshot["client_name"] == "The Patels"
        assert Invoice.objects.get(pk=old.pk).billing_snapshot["client_name"] == label
        assert Invoice.objects.get(pk=old.pk).billing_snapshot["email"] == ""
        assert record.report["billing"]["retained"] == 1
        assert record.financial_retained_until > now() + timedelta(days=365 * 5)
        # After the period, the erased_financial category anonymises the rest.
        ErasureRecord.objects.filter(pk=record.pk).update(
            financial_retained_until=now() - timedelta(days=1)
        )
        from tutortrack.privacy import retention

        assert retention._purge_erased_financial(now(), True, 10) == 1
        assert retention._purge_erased_financial(now(), False, 10) == 1
        assert Invoice.objects.get(pk=recent.pk).billing_snapshot["client_name"] == label
        assert Invoice.objects.filter(client=family.client).count() == 2  # never deleted


def test_erasure_ends_the_portal_login_here(org, family):
    with tenant_context(org):
        erasure.erase_now("people.contact", str(family.contact.pk))
        membership = Membership.objects.get(user=family.parent)
        assert membership.status == Membership.Status.REMOVED
        assert Contact.objects.get(pk=family.contact.pk).user_id is None


def test_steps_are_idempotent(org, family):
    with tenant_context(org):
        record = erasure.plan("people.student", str(family.student.pk))
        first = erasure.run_provider(record, "people")
        again = erasure.run_provider(record, "people")
        assert first == again
        record.refresh_from_db()
        assert record.steps_done == ["people"]


def test_the_erasure_number_is_a_per_organisation_sequence(org, family):
    other = UserFactory()
    MembershipFactory(organisation=org, role="client", user=other)
    with tenant_context(org):
        first = erasure.erased_label("people.student")
        second = erasure.erased_label("people.student")
    assert first != second
    assert int(second.rsplit("#", 1)[1]) == int(first.rsplit("#", 1)[1]) + 1


def test_scrub_replaces_whole_words_only(org, family):
    with tenant_context(org):
        person = registry.resolve("people.student", str(family.student.pk))
    ctx = registry.ErasureContext(labels={}, financial_cutoff=now())
    ctx.prepare_scrub(person, "Erased Student #9")
    assert ctx.scrub("Arjun's algebra with Arjun Patel") == (
        "Erased Student #9's algebra with Erased Student #9"
    )
    assert ctx.scrub("Arjunite") == "Arjunite"


def test_scrub_terms_are_encrypted_at_rest(org, family):
    with tenant_context(org):
        record = erasure.plan("people.student", str(family.student.pk))
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT scrub_terms FROM privacy_erasurerecord WHERE id = %s", [record.pk]
            )
            raw = cursor.fetchone()[0]
    assert "Arjun" not in raw


def test_erasure_scrubs_the_person_from_ai_proposals(org, family, s3):
    from tutortrack.ai.models import AIProposal

    with tenant_context(org):
        proposal = AIProposal.objects.create(
            feature="command_bar",
            action="lesson.move",
            params={"student": "Arjun Patel", "time": "17:00"},
            summary="Move Arjun Patel's Thursday maths to 5pm",
        )
        erasure.erase_now("people.student", str(family.student.pk))
        proposal.refresh_from_db()
    assert "Arjun" not in proposal.summary
    assert "Arjun" not in str(proposal.params)
    assert proposal.params["time"] == "17:00"
