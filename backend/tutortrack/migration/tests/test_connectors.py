"""E28-T05..T09: cutover assistant, TutorCruncher and Teachworks connectors (fakes),
TutorBird presets and Google Sheets."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction

from tutortrack.billing.models import ClientLedgerEntry, Invoice
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict
from tutortrack.core.time import now
from tutortrack.identity.models import Invitation
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import Credentials
from tutortrack.jobs.models import Job
from tutortrack.migration import services
from tutortrack.migration.connectors import fake
from tutortrack.migration.connectors.base import source_for
from tutortrack.migration.models import ImportBatch, MigrationProject
from tutortrack.people.models import Client, Student, TutorProfile
from tutortrack.scheduling.models import Lesson, LessonSeries

from .conftest import execute, run_import

pytestmark = pytest.mark.django_db
KEY = Credentials(secret="tc-key-123456")


def finish_step_imports(project: MigrationProject, step: str) -> list[ImportBatch]:
    batches = list(project.batches.filter(project_step=step).order_by("created_at"))
    out = []
    for batch in batches:
        services.validate(batch.pk)
        out.append(execute(batch))
    return out


def test_tutorcruncher_records_map_to_our_fields(tenant):
    source = source_for("tutorcruncher")
    cutover = now().date()
    clients = list(source.fetch(KEY, "clients", cutover=cutover))
    assert clients[0]["email"] == "jane.smith@example.com"
    assert clients[0]["status"] == "active"
    assert clients[0]["tags"] == "VIP"
    students = list(source.fetch(KEY, "students", cutover=cutover))
    assert students[0]["client_external_id"] == 11
    balances = list(source.fetch(KEY, "opening_balances", cutover=cutover))
    assert {b["balance"] for b in balances} == {"90.00", "-30.00"}  # their credit is negative
    totals = source.totals(KEY, cutover=cutover)
    assert totals["clients"] == 2
    assert totals["future_lessons"] == 4
    assert totals["not_imported_agents"] == 1


def test_wrong_api_key_is_rejected(tenant, user):
    with pytest.raises(BusinessRuleViolation):
        services.create_project(
            user=user,
            name="",
            source="tutorcruncher",
            cutover_date=now().date(),
            api_key="wrong-key",
        )
    with pytest.raises(BusinessRuleViolation):
        services.create_project(user=user, name="", source="teachworks", cutover_date=now().date())


def test_tutorcruncher_migration_end_to_end(tenant, user, member, s3):
    with transaction.atomic():
        project = services.create_project(
            user=user,
            name="From TC",
            source="tutorcruncher",
            cutover_date=now().date(),
            api_key="tc-key-123456",
        )
    connection = IntegrationConnection.objects.get(pk=project.connection_id)
    assert connection.provider == "tutorcruncher"
    assert connection.secret == "tc-key-123456"
    assert project.current_step == "people"

    services.start_step(project.pk, "people")
    people = finish_step_imports(project, "people")
    assert [b.entity for b in people] == ["clients", "students", "tutors"]
    assert all(b.status == "completed" for b in people), [b.stats for b in people]
    assert Student.objects.count() == 3
    assert TutorProfile.objects.count() == 2
    with pytest.raises(Conflict):
        services.complete_step(project, "jobs")  # not the current step
    services.complete_step(project, "people")

    services.start_step(project.pk, "services")
    finish_step_imports(project, "services")
    services.complete_step(project, "services")
    services.start_step(project.pk, "jobs")
    jobs = finish_step_imports(project, "jobs")
    assert all(b.stats.get("failed", 0) == 0 for b in jobs), [
        list(b.rows.values_list("errors", flat=True)) for b in jobs
    ]
    job = Job.objects.get()
    assert job.charge_rate.amount == Decimal("45.00")
    assert LessonSeries.objects.count() == 1
    assert Lesson.objects.filter(status="completed").count() == 2  # history
    services.complete_step(project, "jobs")

    services.start_step(project.pk, "balances")
    balances = finish_step_imports(project, "balances")
    assert {b.entity for b in balances} == {"opening_balances", "invoices"}
    assert Invoice.objects.count() == 2
    jane = Client.objects.get(contacts__email="jane.smith@example.com")
    assert sum(e.amount.amount for e in ClientLedgerEntry.objects.filter(client=jane)) == Decimal(
        "90.00"
    )
    services.complete_step(project, "balances")
    services.complete_step(project, "payment_methods")
    assert services.invite_imported_tutors(project) == 2
    assert Invitation.objects.filter(email="alex.jones@example.com").exists()
    services.complete_step(project, "invite_users")
    services.complete_step(project, "reminders")

    report = services.reconcile(project.pk)
    lines = {line["metric"]: line for line in report["lines"]}
    assert lines["clients"]["ok"]
    assert lines["students"]["ok"]
    assert lines["tutors"]["ok"]
    assert lines["balances_sum"]["source"] == "60.00"
    assert lines["balances_sum"]["ok"]
    assert lines["future_lessons"]["ok"], lines["future_lessons"]
    project.refresh_from_db()
    assert project.status == "completed"
    assert project.reconciliation["ok"]


def test_teachworks_pulls_customers_services_lessons_and_packages(tenant, user, s3):
    with transaction.atomic():
        project = services.create_project(
            user=user, name="", source="teachworks", cutover_date=now().date(), api_key="tw-key"
        )
    services.start_step(project.pk, "people")
    finish_step_imports(project, "people")
    services.complete_step(project, "people")
    services.start_step(project.pk, "services")
    finish_step_imports(project, "services")
    services.complete_step(project, "services")
    services.start_step(project.pk, "jobs")
    finish_step_imports(project, "jobs")
    assert LessonSeries.objects.get().lessons.count() == 4
    services.complete_step(project, "jobs")
    services.start_step(project.pk, "balances")
    finish_step_imports(project, "balances")
    leo = Student.objects.get(first_name="Leo")
    assert sum(e.amount.amount for e in ClientLedgerEntry.objects.filter(client=leo.client)) == (
        Decimal("-120.00")
    )
    assert TutorProfile.objects.get().pay_rate_amount == Decimal("30.00")


def test_steps_wait_for_their_imports(tenant, user, s3):
    with transaction.atomic():
        project = services.create_project(
            user=user, name="Files", source="tutorbird", cutover_date=now().date()
        )
    from .conftest import make_batch

    make_batch("clients", [{"First Name": "Kim"}], project=project, step="people")
    with pytest.raises(BusinessRuleViolation, match="Finish or cancel"):
        services.complete_step(project, "people")
    services.complete_step(project, "people", skip=True)
    project.refresh_from_db()
    assert project.steps["people"]["status"] == "skipped"
    assert project.current_step == "services"


def test_tutorbird_files_reconcile_from_their_rows(tenant, user, s3):
    with transaction.atomic():
        project = services.create_project(
            user=user, name="TB", source="tutorbird", cutover_date=now().date()
        )
    run_import(
        "students",
        [
            {"First Name": "Ava", "Parent Email": "k@example.com", "Status": "Active"},
            {"First Name": "Noah", "Parent Email": "k@example.com", "Status": "Inactive"},
        ],
        preset="tutorbird",
        project=project,
        step="people",
    )
    report = services.reconcile(project.pk)
    students = next(line for line in report["lines"] if line["metric"] == "students")
    assert students == {
        "metric": "students",
        "source": "2",
        "imported": "2",
        "difference": "0",
        "ok": True,
    }
    assert Student.objects.get(first_name="Noah").status == "finished"


def test_google_sheet_import(tenant, user, member):
    with pytest.raises(BusinessRuleViolation, match="Connect your Google"):
        services.create_from_google_sheet(
            user=user,
            url="https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit",
            entity="students",
        )
    IntegrationConnection.objects.create(
        user=user,
        level="user",
        provider="google_sheets",
        access_token="fake-token",
        expires_at=now() + timedelta(hours=1),
    )
    with pytest.raises(BusinessRuleViolation, match="Google Sheet"):
        services.create_from_google_sheet(user=user, url="https://example.com/x", entity="students")
    fake.set_dataset("google_sheets", fake.sheet_sample())
    batch = services.create_from_google_sheet(
        user=user,
        url="https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit#gid=0",
        entity="students",
    )
    assert batch.source == "google_sheets"
    assert batch.filename == "Students"
    assert batch.mapping["Parent email"] == "parent_email"
    assert batch.rows.count() == 2
