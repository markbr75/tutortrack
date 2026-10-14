"""E23-T10 (Phase 3): Sage Business Cloud Accounting and FreeAgent ledgers, and Xero Payroll
timesheets for employed tutors."""

from __future__ import annotations

import json
import urllib.parse
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from tutortrack.accounting import payroll_sync
from tutortrack.accounting.documents import InvoiceDoc, Line, PaymentDoc
from tutortrack.accounting.models import PayrollEmployeeLink, PayrollTimesheetSync
from tutortrack.accounting.providers import freeagent, sage
from tutortrack.accounting.providers.xero_payroll import Employee, FakeXeroPayroll
from tutortrack.core.context import tenant_context
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin
from tutortrack.core.time import now
from tutortrack.integrations.providers import Credentials, http
from tutortrack.payroll import services as payroll
from tutortrack.payroll.models import PayItem
from tutortrack.people.tests.factories import TutorProfileFactory

from .test_accounting import (
    test_connecting_fetches_the_chart_and_needs_complete_mappings as connecting_flow,
)
from .test_accounting import (
    test_invoice_payment_refund_and_payout_keep_the_ledger_balance_in_step as ledger_flow,
)

pytestmark = pytest.mark.django_db


# --- Sage and FreeAgent (same engine, same fake ledger shape) -----------------------------------


@pytest.mark.parametrize("provider", ["sage", "freeagent"])
def test_new_ledgers_connect_and_need_complete_mappings(org, world, provider):
    connecting_flow(org, world, provider)


@pytest.mark.parametrize("provider", ["sage", "freeagent"])
def test_new_ledgers_keep_the_invoice_balance_in_step(org, world, provider):
    """FR-23-3 AC on Sage and FreeAgent: invoice, part payment with fee, refund, payout."""
    ledger_flow(org, world, provider)


class Recorder:
    def __init__(self, replies: dict[tuple[str, str], Any]):
        self.replies = replies
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> http.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        for (m, fragment), reply in self.replies.items():
            if m == method and fragment in url:
                return http.Response(200, None, json.dumps(reply).encode())  # type: ignore[arg-type]
        return http.Response(200, None, b"{}")  # type: ignore[arg-type]


CREDS = Credentials(access_token="t", account_id="biz-1")
INVOICE = InvoiceDoc(
    kind="invoice",
    ref="ours",
    date="2026-10-01",
    currency="GBP",
    number="INV-000042",
    contact="c-1",
    due_date="2026-10-15",
    total=Decimal("120.00"),
    lines=(
        Line(
            description="Tuition",
            account="acc-200",
            account_code="200",
            net=Decimal("100.00"),
            tax=Decimal("20.00"),
            tax_code="GB_STANDARD",
        ),
    ),
)


def test_sage_invoice_and_payment_requests(monkeypatch):
    recorder = Recorder(
        {
            ("POST", "/sales_invoices"): {"id": "s-inv", "invoice_number": "SI-1"},
            ("POST", "/contact_payments"): {"id": "s-pay"},
        }
    )
    monkeypatch.setattr(http, "request", recorder)
    client = sage.SageClient()
    pushed = client.push(CREDS, INVOICE, idempotency_key="tt-1")
    assert pushed.external_id == "s-inv"
    call = recorder.calls[0]
    assert call["headers"]["X-Business"] == "biz-1"
    assert call["user_url"] is True  # through core.net.safe_urlopen
    body = call["json_body"]["sales_invoice"]
    assert (body["reference"], body["invoice_lines"][0]["net_amount"]) == ("INV-000042", "100.00")
    assert body["invoice_lines"][0]["tax_rate_id"] == "GB_STANDARD"
    payment = PaymentDoc(
        kind="payment",
        ref="p",
        date="2026-10-02",
        currency="GBP",
        contact="c-1",
        account="bank-1",
        amount=Decimal("60.00"),
        reference="INV-000042",
        allocations=(("s-inv", Decimal("60.00")),),
    )
    assert client.push(CREDS, payment, idempotency_key="tt-2").external_id == "s-pay"
    paid = recorder.calls[-1]["json_body"]["contact_payment"]
    assert paid["transaction_type_id"] == "CUSTOMER_RECEIPT"
    assert paid["allocated_artefacts"] == [{"artefact_id": "s-inv", "amount": "60.00"}]


def test_freeagent_invoice_is_created_then_marked_as_sent(monkeypatch):
    url = "https://api.freeagent.com/v2/invoices/9"
    recorder = Recorder({("POST", "/invoices"): {"invoice": {"url": url}}})
    monkeypatch.setattr(http, "request", recorder)
    pushed = freeagent.FreeAgentClient().push(CREDS, INVOICE, idempotency_key="tt-1")
    assert pushed.external_id == url
    assert recorder.calls[0]["json_body"]["invoice"]["reference"] == "INV-000042"
    assert recorder.calls[1]["url"] == f"{url}/transitions/mark_as_sent"
    assert all(c["user_url"] for c in recorder.calls)


# --- Xero Payroll ---------------------------------------------------------------------------------


@pytest.fixture
def employed(org, world) -> dict[str, Any]:
    with tenant_context(org):
        tutor = TutorProfileFactory(
            organisation=org, status="active", employment_type="employee", email="sam@example.com"
        )
        stranger = TutorProfileFactory(
            organisation=org, status="active", employment_type="employee"
        )
        for person in (tutor, stranger):
            payroll.update_profile(person, method="external_payroll")
            for day in (2, 3):
                item = payroll.create_manual_item(
                    tutor=person,
                    kind="salary",
                    description="Lessons",
                    amount=Money("50.00", "GBP"),
                    day=now().date() - timedelta(days=day),
                )
                PayItem.objects.filter(pk=item.pk).update(unit="hour", quantity=Decimal("2.5"))
        payroll.create_manual_item(
            tutor=tutor,
            kind="bonus",
            description="Bonus",
            amount=Money("20.00", "GBP"),
            day=now().date(),
        )
        run, _ = payroll.create_pay_run(
            period_start=now().date() - timedelta(days=30),
            period_end=now().date(),
            start_workflow=False,
        )
        payroll.assemble(run.pk)
        run = payroll.approve(run, user=world["finance"])
    FakeXeroPayroll.reset([Employee("emp-1", "sam@example.com", "Sam", "Lee", "cal-1")])
    return {"tutor": tutor, "stranger": stranger, "run": run}


def connect_payroll(org, world) -> str:
    api = world["api"]
    started = api.post(
        "/api/v1/integrations/oauth/start",
        {"provider": "xero_payroll", "level": "organisation", "next": "/settings/accounting"},
        format="json",
    )
    assert started.status_code == 200, started.json()
    query = urllib.parse.parse_qs(urllib.parse.urlparse(started.json()["authorize_url"]).query)
    done = api.post(
        "/api/v1/integrations/oauth/complete",
        {"code": query["code"][0], "state": query["state"][0]},
        format="json",
    )
    assert done.status_code == 201, done.json()
    return str(done.json()["id"])


def test_xero_payroll_sends_employed_tutors_hours_as_timesheets(org, world, employed):
    """FR-12-8: sync employed tutors' approved hours to Xero Payroll (UK)."""
    with tenant_context(org):
        assert not payroll_sync.should_sync(employed["run"].pk)  # not connected
    connect_payroll(org, world)
    with tenant_context(org):
        assert payroll_sync.should_sync(employed["run"].pk)
        assert payroll_sync.sync_pay_run(employed["run"].pk) == "partial"
        sync = PayrollTimesheetSync.objects.get()
        link = PayrollEmployeeLink.objects.get()
    assert (link.tutor_id, link.employee_id, link.matched_by) == (
        employed["tutor"].pk,
        "emp-1",
        "email",
    )
    by_tutor = {r["tutor"]: r for r in sync.results}
    mine = by_tutor[str(employed["tutor"].pk)]
    assert (mine["timesheet"], mine["hours"], mine["other"]) == ("ts-1", "5.00", "20.00")
    assert by_tutor[str(employed["stranger"].pk)]["problem"] == "no_employee"
    [sheet] = FakeXeroPayroll.timesheets.values()
    assert (sheet["employee"], sheet["rate"], len(sheet["lines"])) == ("emp-1", "rate-ordinary", 2)
    # A retry (activity retry or "sync again") never sends the same timesheet twice.
    with tenant_context(org):
        payroll_sync.sync_pay_run(employed["run"].pk)
    assert len(FakeXeroPayroll.timesheets) == 1


def test_xero_payroll_api_links_rates_and_retry(org, world, employed):
    api = world["api"]
    assert api.get("/api/v1/accounting/xero-payroll").json()["connected"] is False
    connect_payroll(org, world)
    employees = api.get("/api/v1/accounting/xero-payroll/employees").json()
    assert employees[0]["id"] == "emp-1"
    rates = api.get("/api/v1/accounting/xero-payroll/earnings-rate").json()
    assert {r["id"] for r in rates} == {"rate-ordinary", "rate-overtime"}
    chosen = api.put(
        "/api/v1/accounting/xero-payroll/earnings-rate",
        {"id": "rate-overtime", "name": "Overtime Hours"},
        format="json",
    )
    assert chosen.json()["earnings_rate"]["id"] == "rate-overtime"
    linked = api.put(
        "/api/v1/accounting/xero-payroll/links",
        {"tutor": str(employed["stranger"].pk), "employee_id": "emp-1"},
        format="json",
    )
    assert linked.status_code == 200
    assert linked.json()["links"][0]["matched_by"] == "manual"
    bad = api.put(
        "/api/v1/accounting/xero-payroll/links",
        {"tutor": str(employed["stranger"].pk), "employee_id": "nope"},
        format="json",
    )
    assert bad.status_code == 422
    started = api.post(
        "/api/v1/accounting/xero-payroll/sync", {"pay_run": str(employed["run"].pk)}, format="json"
    )
    assert started.status_code == 202


class TestTimesheetSyncIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/accounting/xero-payroll/syncs"

    def make_object(self, organisation: Any) -> PayrollTimesheetSync:
        with tenant_context(organisation):
            run, _ = payroll.create_pay_run(
                period_start=now().date() - timedelta(days=7),
                period_end=now().date(),
                start_workflow=False,
            )
            return PayrollTimesheetSync.objects.create(pay_run=run)


def test_xero_payroll_client_requests(monkeypatch):
    from tutortrack.accounting.providers.xero_payroll import XeroPayrollClient

    recorder = Recorder(
        {
            ("POST", "/Timesheets"): {"timesheet": {"timesheetID": "x-ts"}},
            ("GET", "/Employees"): {
                "employees": [
                    {"employeeID": "e1", "email": "SAM@example.com", "payrollCalendarID": "cal"}
                ]
            },
        }
    )
    monkeypatch.setattr(http, "request", recorder)
    client = XeroPayrollClient()
    [employee] = client.employees(CREDS)
    assert (employee.email, employee.calendar_id) == ("sam@example.com", "cal")
    sheet = client.push_timesheet(
        CREDS,
        employee=employee,
        start="2026-10-01",
        end="2026-10-31",
        lines=[("2026-10-02", Decimal("2.5"))],
        earnings_rate="r1",
        idempotency_key="tt-x",
    )
    assert sheet == "x-ts"
    call = recorder.calls[-1]
    assert call["headers"] == {"Xero-tenant-id": "biz-1", "Idempotency-Key": "tt-x"}
    assert call["json_body"]["timesheetLines"] == [
        {"date": "2026-10-02", "earningsRateID": "r1", "numberOfUnits": "2.5"}
    ]
