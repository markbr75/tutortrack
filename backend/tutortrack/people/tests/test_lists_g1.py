"""Gap batch G1 (FR-05-1/4/11): computed list fields, filters and sorting, and XLSX/selected
exports of the people list grids."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction

from tutortrack.billing import ledger
from tutortrack.billing.models import ClientLedgerEntry
from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry
from tutortrack.core.money import Money
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.courses.tests.factories import TermFactory
from tutortrack.delivery import services as delivery
from tutortrack.delivery.models import LessonReport
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people import selectors
from tutortrack.people.models import Client
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)
from tutortrack.scheduling import services as scheduling
from tutortrack.scheduling.models import AvailabilityTemplate, AvailabilityWindow

pytestmark = pytest.mark.django_db
LONDON = ZoneInfo("Europe/London")


def at_ten(days: int) -> datetime:
    day = now().astimezone(LONDON).date() + timedelta(days=days)
    return datetime.combine(day, time(10), tzinfo=LONDON)


@pytest.fixture
def owner(org):
    return client_for(org, MembershipFactory(organisation=org, role="owner").user)


@pytest.fixture
def world(org):
    tutor = TutorProfileFactory(organisation=org, status="active", first_name="Nia")
    service = ServiceFactory(organisation=org, name="Maths 1:1")
    rich = ClientFactory(organisation=org, display_name="Rich")
    poor = ClientFactory(organisation=org, display_name="Owes")
    idle = ClientFactory(organisation=org, display_name="Idle")
    students = {
        c.display_name: StudentFactory(organisation=org, client=c, first_name=c.display_name)
        for c in (rich, poor, idle)
    }
    with tenant_context(org), transaction.atomic():
        ledger.post(poor, ClientLedgerEntry.Type.INVOICE, Money(Decimal("120.00"), "GBP"))
        ledger.post(
            rich, ClientLedgerEntry.Type.PAYMENT_REQUEST_PAYMENT, Money(Decimal("-50.00"), "GBP")
        )
    return {"tutor": tutor, "service": service, "clients": [rich, poor, idle], "students": students}


def lesson(org, world, student, start, *, complete=False):
    with tenant_context(org):
        made = scheduling.create_lesson(
            start=start,
            end=start + timedelta(minutes=90),
            service=world["service"],
            attendees=[{"student": student}],
            tutors=[{"tutor": world["tutor"]}],
            timezone="Europe/London",
            override_conflicts=True,
            notify=False,
        ).lesson
        if complete:
            delivery.complete_lesson(made)
    return made


def rows(response):
    assert response.status_code == 200, response.json()
    return {r["display_name"]: r for r in response.json()["results"]}


def test_client_list_shows_balance_lessons_and_hours_this_term(org, world, owner):
    TermFactory(
        organisation=org,
        start_date=now().date() - timedelta(days=20),
        end_date=now().date() + timedelta(days=40),
    )
    students = world["students"]
    lesson(org, world, students["Rich"], at_ten(-2), complete=True)
    upcoming = lesson(org, world, students["Rich"], at_ten(3))
    found = rows(owner.get("/api/v1/clients"))
    rich, poor, idle = found["Rich"], found["Owes"], found["Idle"]
    assert (Decimal(rich["balance"]), Decimal(poor["balance"])) == (
        Decimal("-50.00"),
        Decimal("120.00"),
    )
    assert Decimal(idle["balance"]) == 0
    assert rich["next_lesson_at"].startswith(
        upcoming.start.astimezone(ZoneInfo("UTC")).date().isoformat()
    )
    assert rich["last_lesson_at"] is not None
    assert idle["next_lesson_at"] is None
    assert Decimal(rich["hours_this_term"]) == Decimal("3.00")  # 2 x 90 minutes, both booked
    student = owner.get(f"/api/v1/students/{students['Rich'].pk}").json()
    assert student["next_lesson_at"] is not None
    assert Decimal(student["hours_this_term"]) == 3


def test_computed_filters_and_sorting(org, world, owner):
    lesson(org, world, world["students"]["Rich"], at_ten(4))
    by_balance = owner.get("/api/v1/clients", {"ordering": "-balance"}).json()["results"]
    assert [r["display_name"] for r in by_balance] == ["Owes", "Idle", "Rich"]
    owing = rows(owner.get("/api/v1/clients", {"balance_min": "0.01"}))
    assert set(owing) == {"Owes"}
    upcoming = rows(owner.get("/api/v1/clients", {"has_upcoming_lesson": "true"}))
    assert set(upcoming) == {"Rich"}
    # Clients without a lesson sort after those with one (never-null sort key).
    by_next = owner.get("/api/v1/clients", {"ordering": "next_lesson_at"}).json()["results"]
    assert by_next[0]["display_name"] == "Rich"
    page = owner.get("/api/v1/clients", {"ordering": "next_lesson_at", "page_size": 1}).json()
    assert page["next"]  # cursor pagination works over the computed sort key
    second = owner.get(page["next"]).json()["results"]
    assert second
    assert second[0]["display_name"] != "Rich"


def test_figures_respect_permissions(org, world, monkeypatch):
    """Without billing access there is no balance (and its filter is ignored)."""
    from tutortrack.core import permissions

    real = permissions.has_perm
    monkeypatch.setattr(
        permissions,
        "has_perm",
        lambda user, codename, obj=None: (
            codename != "billing.invoice.view" and real(user, codename, obj)
        ),
    )
    user = MembershipFactory(organisation=org, role="owner").user
    with tenant_context(org):
        qs = selectors.with_client_figures(user, Client.objects.all())
        assert "balance" not in qs.query.annotations
        assert "next_lesson_at" in qs.query.annotations
    response = client_for(org, user).get("/api/v1/clients", {"balance_min": "100"})
    assert len(response.json()["results"]) == 3
    assert response.json()["results"][0]["balance"] is None


def test_tutor_hours_utilisation_and_report_sla(org, world, owner):
    tutor = world["tutor"]
    with tenant_context(org):
        template = AvailabilityTemplate.objects.create(
            tutor=tutor, effective_from=now().date() - timedelta(days=60), timezone="Europe/London"
        )
        for weekday in range(7):
            AvailabilityWindow.objects.create(
                template=template, weekday=weekday, start_time=time(9), end_time=time(17)
            )
    done = lesson(org, world, world["students"]["Rich"], at_ten(-1), complete=True)
    with tenant_context(org):
        report = LessonReport.objects.get(lesson=done)
        LessonReport.objects.filter(pk=report.pk).update(
            due_at=now() - timedelta(hours=1), submitted_at=now() - timedelta(hours=2)
        )
    body = owner.get(f"/api/v1/tutors/{tutor.pk}").json()
    assert Decimal(body["report_sla"]) == Decimal("100.0")
    listed = {t["id"]: t for t in owner.get("/api/v1/tutors").json()["results"]}[str(tutor.pk)]
    in_month = now().astimezone(LONDON).day > 1  # yesterday may be last month
    assert Decimal(listed["hours_this_month"]) == (Decimal("1.50") if in_month else 0)
    assert listed["utilisation"] is not None
    assert Decimal(listed["utilisation"]) < 100
    late = owner.get("/api/v1/tutors", {"report_sla_below": "50"}).json()["results"]
    assert str(tutor.pk) not in {t["id"] for t in late}


def test_xlsx_export_is_audited_and_formula_safe(org, world, owner):
    with tenant_context(org):
        Client.objects.filter(pk=world["clients"][2].pk).update(display_name="=HYPERLINK(1)")
    response = owner.get("/api/v1/clients/export", {"file_format": "xlsx"})
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    assert 'filename="clients.xlsx"' in response["Content-Disposition"]
    sheet = zipfile.ZipFile(io.BytesIO(response.content)).read("xl/worksheets/sheet1.xml").decode()
    assert "'=HYPERLINK(1)" in sheet
    assert "<v>120.00</v>" in sheet  # balances are number cells
    with tenant_context(org):
        entry = AuditEntry.objects.filter(action="export").latest("created_at")
        assert entry.changes["format"][1] == "xlsx"


def test_export_only_the_selected_rows(org, world, owner):
    picked = world["clients"][:2]
    response = owner.get("/api/v1/clients/export", {"ids": ",".join(str(c.pk) for c in picked)})
    names = [row["name"] for row in csv.DictReader(io.StringIO(response.content.decode()))]
    assert sorted(names) == ["Owes", "Rich"]


def test_contact_and_tutor_exports(org, world, owner):
    ContactFactory(organisation=org, client=world["clients"][0], first_name="Priya")
    contacts = owner.get("/api/v1/contacts/export", {"file_format": "csv"})
    assert contacts.status_code == 200
    assert "Priya" in contacts.content.decode()
    tutors = owner.get("/api/v1/tutors/export")
    assert "Nia" in tutors.content.decode()
    finance = client_for(org, MembershipFactory(organisation=org, role="finance").user)
    assert finance.get("/api/v1/tutors/export").status_code == 403
