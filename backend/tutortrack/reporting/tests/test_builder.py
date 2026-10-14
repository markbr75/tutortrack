"""E26-T08: the custom report builder on the semantic layer (FR-26-3): whitelisted
dimensions and measures (no field paths or SQL from users), permission-scoped data,
aggregation maths (Hypothesis), saved and shared reports, exports and isolation."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from unittest import mock

import pytest
from django.db import OperationalError
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import ClientFactory
from tutortrack.reporting import builder, periods
from tutortrack.reporting.models import CustomReport, FactCharge, ReportRun

pytestmark = pytest.mark.django_db

RUN = "/api/v1/reporting/builder/run"


def charge(org, client=None, *, kind="lesson", gross="10.00", currency="GBP", day=None, **extra):
    with tenant_context(org):
        today = periods.org_today()
        row = FactCharge(
            client_id=client.pk if client else None,
            date=day or today.replace(day=1),
            kind=kind,
            status="invoiced",
            currency=currency,
            **extra,
        )
        row.net = Money(Decimal(gross), currency)
        row.tax = Money(Decimal(0), currency)
        row.gross = Money(Decimal(gross), currency)
        row.save()
        return row


@pytest.fixture
def finance(org):
    return client_for(org, MembershipFactory(organisation=org, role="finance").user)


def q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- aggregation maths (Hypothesis) -------------------------------------------------------------


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    rows=st.lists(
        st.tuples(
            st.sampled_from(["lesson", "late_fee", "package"]),
            st.sampled_from(["GBP", "EUR"]),
            st.decimals(min_value="0.01", max_value="999.99", places=2),
        ),
        min_size=1,
        max_size=25,
    )
)
def test_grouped_sums_counts_and_averages_match_the_rows(org, rows):
    from tutortrack.identity.tests.factories import UserFactory

    user = UserFactory(is_superuser=True)
    with tenant_context(org):
        FactCharge.objects.all().delete()
    for kind, currency, gross in rows:
        charge(org, kind=kind, currency=currency, gross=str(gross))
    with tenant_context(org):
        output = builder.run(
            user,
            {
                "dataset": "charges",
                "group_by": ["kind"],
                "measures": ["count", "gross", "average_gross"],
                "period": "this_month",
            },
        )
    groups: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    for kind, currency, gross in rows:
        groups[(kind, currency)].append(gross)
    got = {(r["kind"], r["currency"]): r for r in output.result.rows}
    assert len(got) == len(groups)
    for (kind, currency), values in groups.items():
        row = got[(str(kind), currency)]
        assert row["count"] == len(values)
        assert Decimal(row["gross"]) == q2(sum(values, Decimal(0)))
        assert Decimal(row["average_gross"]) == q2(sum(values, Decimal(0)) / len(values))
    by_currency: dict[str, list[Decimal]] = defaultdict(list)
    for _kind, currency, gross in rows:
        by_currency[currency].append(gross)
    totals = {t["currency"]: t for t in output.result.totals}
    for currency, values in by_currency.items():
        total = totals[currency]
        assert total["count"] == len(values)
        assert Decimal(total["gross"]) == q2(sum(values, Decimal(0)))
        # The total average is the overall average, not an average of averages.
        assert Decimal(total["average_gross"]) == q2(sum(values, Decimal(0)) / len(values))


@settings(max_examples=50, deadline=None)
@given(
    minutes=st.integers(min_value=0, max_value=100_000),
    money=st.decimals(min_value="-99999.995", max_value="99999.995", places=3),
)
def test_measure_formatting_rounds_half_up(minutes, money):
    hours = builder.Measure("h", "Hours", "sum", "minutes", "hours")
    cash = builder.Measure("m", "Money", "sum", "gross_amount", "money")
    assert Decimal(builder.format_measure(hours, minutes, "")) == (Decimal(minutes) / 60).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    assert Decimal(builder.format_measure(cash, money, "GBP")) == q2(money)
    assert builder.format_measure(cash, Decimal("1.5"), "JPY") == "2"


# --- the semantic layer -------------------------------------------------------------------------


def test_datasets_are_whitelisted_and_permission_filtered(org, finance, api):
    keys = {d["key"] for d in finance.get("/api/v1/reporting/builder/datasets").json()}
    assert {"charges", "payments", "invoices", "lessons", "pay_items"} <= keys
    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    mine = {d["key"] for d in coordinator.get("/api/v1/reporting/builder/datasets").json()}
    assert "charges" not in mine  # coordinators have no finance reports
    assert {"lessons", "students", "enquiries", "lesson_feedback"} <= mine
    denied = coordinator.post(RUN, {"dataset": "charges", "measures": ["count"]}, format="json")
    assert denied.status_code == 403
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    assert tutor.get("/api/v1/reporting/builder/datasets").status_code == 403


@pytest.mark.parametrize(
    "bad",
    [
        {"dataset": "auth_user", "measures": ["count"]},
        {"dataset": "charges", "measures": ["gross_amount"]},
        {"dataset": "charges", "measures": ["count"], "group_by": ["client__custom_fields__x"]},
        {"dataset": "charges", "measures": ["count"], "group_by": ["kind:month"]},
        {
            "dataset": "charges",
            "measures": ["count"],
            "filters": [{"field": "gross_amount", "op": "gte", "value": "1"}],
        },
        {
            "dataset": "charges",
            "measures": ["count"],
            "filters": [{"field": "client", "op": "contains", "value": "x"}],
        },
        {"dataset": "charges", "measures": ["count"], "ordering": "organisation_id"},
        {"dataset": "charges", "group_by": [], "measures": []},
        {"dataset": "charges", "measures": ["count"], "period": "custom"},
    ],
)
def test_only_known_names_are_accepted(org, finance, bad):
    response = finance.post(RUN, bad, format="json")
    assert response.status_code in (400, 422), response.content


def test_filters_dates_and_labels(org, finance):
    family = ClientFactory(organisation=org, display_name="The Patels")
    other = ClientFactory(organisation=org, display_name="The Smiths")
    charge(org, family, kind="lesson", gross="40.00")
    charge(org, family, kind="late_fee", gross="15.00")
    charge(org, other, kind="lesson", gross="30.00")
    body = finance.post(
        RUN,
        {
            "dataset": "charges",
            "group_by": ["client", "date:month"],
            "measures": ["count", "gross"],
            "filters": [{"field": "kind", "op": "in", "value": ["lesson"]}],
            "period": "this_month",
            "ordering": "-gross",
            "chart": "bar",
        },
        format="json",
    ).json()
    assert [(r["client"], r["gross"]) for r in body["rows"]] == [
        ("The Patels", "40.00"),
        ("The Smiths", "30.00"),
    ]
    assert body["rows"][0]["date:month"].endswith("-01")
    assert body["chart"] == {
        "kind": "bar",
        "x": "client",
        "y": ["count", "gross"],
        "stacked": False,
    }
    assert body["totals"] == [{"currency": "GBP", "count": 2, "gross": "70.00"}]
    smiths = finance.post(
        RUN,
        {
            "dataset": "charges",
            "measures": ["gross"],
            "filters": [{"field": "client", "op": "eq", "value": str(other.pk)}],
        },
        format="json",
    ).json()
    assert smiths["rows"][0]["gross"] == "30.00"


def test_list_mode_and_row_cap(org, finance):
    family = ClientFactory(organisation=org, display_name="The Patels")
    for _ in range(3):
        charge(org, family)
    body = finance.post(
        RUN, {"dataset": "charges", "group_by": ["client", "kind"], "limit": 2}, format="json"
    ).json()
    assert body["truncated"] is True
    assert len(body["rows"]) == 2
    assert body["rows"][0] == {"client": "The Patels", "kind": "lesson"}


def test_client_custom_fields_are_dimensions(org, finance):
    from tutortrack.crm.models import CustomFieldDefinition

    with tenant_context(org):
        CustomFieldDefinition.objects.create(
            entity_type="people.client", key="school_type", label="School type", type="text"
        )
    state = ClientFactory(organisation=org, custom_fields={"school_type": "state"})
    private = ClientFactory(organisation=org, custom_fields={"school_type": "private"})
    charge(org, state, gross="10.00")
    charge(org, private, gross="25.00")
    datasets = finance.get("/api/v1/reporting/builder/datasets").json()
    charges = next(d for d in datasets if d["key"] == "charges")
    assert "cf.client.school_type" in {d["key"] for d in charges["dimensions"]}
    body = finance.post(
        RUN,
        {"dataset": "charges", "group_by": ["cf.client.school_type"], "measures": ["gross"]},
        format="json",
    ).json()
    assert {r["cf.client.school_type"]: r["gross"] for r in body["rows"]} == {
        "private": "25.00",
        "state": "10.00",
    }


def test_branch_scope_applies(org, finance):
    from tutortrack.identity.models import MembershipBranch
    from tutortrack.tenancy.tests.factories import BranchFactory

    charge(org, gross="10.00")
    north = BranchFactory(organisation=org, name="North")
    member = MembershipFactory(organisation=org, role="branch_manager", branch_scope="selected")
    with tenant_context(org):
        MembershipBranch.objects.create(membership=member, branch=north)
    manager = client_for(org, member.user)
    body = manager.post(RUN, {"dataset": "charges", "measures": ["count"]}, format="json").json()
    assert body["rows"] == [] or body["rows"][0]["count"] == 0
    assert (
        finance.post(RUN, {"dataset": "charges", "measures": ["count"]}, format="json").json()[
            "rows"
        ][0]["count"]
        == 1
    )


def test_lesson_feedback_dataset(org, api):
    from datetime import timedelta

    from tutortrack.core.time import now
    from tutortrack.delivery.models import LessonFeedback
    from tutortrack.people.tests.factories import StudentFactory, TutorProfileFactory
    from tutortrack.scheduling import services as scheduling

    family = ClientFactory(organisation=org)
    student = StudentFactory(organisation=org, client=family)
    tutor = TutorProfileFactory(organisation=org, first_name="Nia", last_name="Adeyemi")
    with tenant_context(org):
        from tutortrack.catalogue.tests.factories import ServiceFactory

        service = ServiceFactory(organisation=org)
        start = (now() - timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
        for days, rating in ((0, 5), (1, 4)):
            lesson = scheduling.create_lesson(
                start=start - timedelta(days=days),
                end=start - timedelta(days=days) + timedelta(hours=1),
                service=service,
                attendees=[{"student": student}],
                tutors=[{"tutor": tutor}],
                timezone="Europe/London",
                override_conflicts=True,
            ).lesson
            LessonFeedback.objects.create(
                lesson=lesson,
                student=student,
                client=family,
                tutor=tutor,
                lesson_date=periods.org_today(),
                status="answered",
                rating=rating,
                expires_at=now() + timedelta(days=7),
            )
    body = api.post(
        RUN,
        {
            "dataset": "lesson_feedback",
            "group_by": ["tutor"],
            "measures": ["answered", "average_rating", "lowest_rating"],
        },
        format="json",
    ).json()
    assert body["rows"] == [
        {"tutor": "Nia Adeyemi", "answered": 2, "average_rating": "4.50", "lowest_rating": "4.00"}
    ]


def test_slow_queries_are_stopped(org, finance):
    with mock.patch.object(builder, "_run", side_effect=OperationalError("canceling statement")):
        response = finance.post(RUN, {"dataset": "charges", "measures": ["count"]}, format="json")
    assert response.status_code == 422
    assert "took too long" in response.json()["detail"]


# --- saved, shared and exported -----------------------------------------------------------------

DEFINITION = {"dataset": "charges", "group_by": ["kind"], "measures": ["count", "gross"]}


def test_save_share_run_and_only_the_owner_edits(org, finance):
    charge(org, gross="12.50")
    created = finance.post(
        "/api/v1/custom-reports",
        {"name": "Charges by type", "definition": DEFINITION, "shared": True},
        format="json",
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert (body["dataset"], body["is_mine"]) == ("charges", True)
    assert body["definition"]["measures"] == ["count", "gross"]
    with tenant_context(org):
        assert OutboxEvent.objects.filter(event_type="custom_report.saved").exists()
    colleague = client_for(org, MembershipFactory(organisation=org, role="finance").user)
    listed = colleague.get("/api/v1/custom-reports").json()["results"]
    assert [r["id"] for r in listed] == [body["id"]]
    ran = colleague.get(f"/api/v1/custom-reports/{body['id']}/run").json()
    assert ran["rows"][0]["gross"] == "12.50"
    edit = {"name": "Mine now", "definition": DEFINITION}
    assert (
        colleague.patch(f"/api/v1/custom-reports/{body['id']}", edit, format="json").status_code
        == 403
    )
    assert colleague.delete(f"/api/v1/custom-reports/{body['id']}").status_code == 403
    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    assert coordinator.get("/api/v1/custom-reports").json()["results"] == []  # no finance data
    renamed = finance.patch(
        f"/api/v1/custom-reports/{body['id']}",
        {"name": "Renamed", "definition": DEFINITION, "shared": False},
        format="json",
    )
    assert renamed.json()["name"] == "Renamed"
    assert colleague.get("/api/v1/custom-reports").json()["results"] == []
    assert finance.delete(f"/api/v1/custom-reports/{body['id']}").status_code == 204


def test_exports_are_audited(org, finance):
    charge(org, gross="9.99")
    saved = finance.post(
        "/api/v1/custom-reports", {"name": "By type", "definition": DEFINITION}, format="json"
    ).json()
    response = finance.get(f"/api/v1/custom-reports/{saved['id']}/export", {"file_format": "csv"})
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0][:2] == ["Type", "Currency"]
    assert rows[1][-1] == "9.99"
    xlsx = finance.get(f"/api/v1/custom-reports/{saved['id']}/export", {"file_format": "xlsx"})
    assert xlsx.content[:2] == b"PK"
    pdf = finance.post(
        "/api/v1/reporting/builder/export",
        {"definition": DEFINITION, "file_format": "pdf", "name": "Ad hoc"},
        format="json",
    )
    assert pdf.content[:4] == b"%PDF"
    with tenant_context(org):
        assert ReportRun.objects.filter(report_key=f"custom:{saved['id']}").count() == 2
        assert ReportRun.objects.filter(report_key="custom").count() == 1
        assert AuditEntry.objects.filter(action="export").count() == 3
    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    lessons = {"dataset": "lessons", "measures": ["lessons"]}
    assert (
        coordinator.post(
            "/api/v1/reporting/builder/export",
            {"definition": lessons, "file_format": "csv"},
            format="json",
        ).status_code
        == 200
    )


def test_saving_validates_the_definition(org, finance):
    response = finance.post(
        "/api/v1/custom-reports",
        {"name": "Bad", "definition": {"dataset": "charges", "measures": ["nope"]}},
        format="json",
    )
    assert response.status_code == 422
    with tenant_context(org), pytest.raises(BusinessRuleViolation):
        from tutortrack.reporting import services

        services.save_custom_report(
            MembershipFactory(organisation=org, role="finance").user,
            name=" ",
            definition=DEFINITION,
        )


class TestCustomReportIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/custom-reports"

    def make_object(self, organisation):
        user = MembershipFactory(organisation=organisation, role="finance").user
        with tenant_context(organisation):
            return CustomReport.objects.create(
                name="Shared", dataset="charges", definition=DEFINITION, owner=user, shared=True
            )


def test_standard_reports_api_is_unchanged_for_the_ai_copilot(org, api):
    """E31 calls ``reports.run(key, user, data)``: it still returns (definition, params,
    result) for the standard reports."""
    from tutortrack.identity.tests.factories import UserFactory
    from tutortrack.reporting import reports

    with tenant_context(org):
        definition, params, result = reports.run(
            "revenue", UserFactory(is_superuser=True), {"period": "this_month"}
        )
    assert definition.key == "revenue"
    assert params.period.start <= params.period.end
    assert isinstance(result.rows, list)
