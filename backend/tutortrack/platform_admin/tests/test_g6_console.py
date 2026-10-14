"""G6 console work: notify customers (FR-29-9), MRR filters and integration status on the
tenant pages, support reply notifications (FR-30-1/5), revenue-share MRR and
reconciliation (FR-30-7) and the failed/stuck workflow console (FR-32-10)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core import mail
from hypothesis import given
from hypothesis import strategies as st

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, WorkflowLink
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.platform_admin import insights, metrics, revenue_share, workflow_console
from tutortrack.platform_admin.models import CustomerNotice, SubscriptionSnapshot
from tutortrack.platform_admin.tests.test_platform import platform_client
from tutortrack.subscriptions.models import MeterReport
from tutortrack.subscriptions.tests.test_subscriptions import subscribe
from tutortrack.success import services as success
from tutortrack.success.tests.factories import SupportConversationFactory

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "platform"])


@pytest.fixture
def staff() -> Any:
    return UserFactory(is_platform_staff=True, first_name="Pat", last_name="Support")


@pytest.fixture
def console(staff: Any) -> Any:
    return platform_client(staff)


@pytest.fixture(autouse=True)
def plans(db: None) -> None:
    from tutortrack.subscriptions.catalogue import sync_addon_prices, sync_plans

    sync_plans()
    sync_addon_prices()


# --- notify customers -----------------------------------------------------------------------------


def test_breach_notice_reaches_owners_and_admins_and_is_audited(org, other_org, console, staff):
    with tenant_context(org):
        owner = MembershipFactory(organisation=org, role="owner", user__email="o@example.com")
        MembershipFactory(organisation=org, role="admin", user__email="a@example.com")
        MembershipFactory(organisation=org, role="tutor", user__email="t@example.com")
    templates = {
        t["key"]: t for t in console.get("/api/v1/platform/customer-notices/templates").json()
    }
    assert "summary" in templates["breach"]["variables"]
    created = console.post(
        "/api/v1/platform/customer-notices",
        {"template": "breach", "organisation_ids": [str(org.pk)],
         "variables": {"summary": "A laptop was stolen.", "when": "14 October",
                       "data_affected": "Names", "actions_taken": "Wiped",
                       "your_actions": "None", "contact": "security@tutortrack.app"}},
        format="json",
    )  # fmt: skip
    assert created.status_code == 201, created.content
    notice_id = created.json()["id"]
    preview = console.get(f"/api/v1/platform/customer-notices/{notice_id}/preview").json()
    assert org.name in preview["subject"]
    assert "A laptop was stolen." in preview["body"]
    assert preview["organisations"] == 1
    no_reason = console.post(
        f"/api/v1/platform/customer-notices/{notice_id}/send", {"reason": " "}, format="json"
    )
    assert no_reason.status_code in (400, 422)
    sent = console.post(
        f"/api/v1/platform/customer-notices/{notice_id}/send",
        {"reason": "INC-42"},
        format="json",
    )
    assert sent.status_code == 200, sent.content
    notice = CustomerNotice.objects.get(pk=notice_id)
    assert (notice.status, notice.organisations_count, notice.recipients_count) == ("sent", 1, 2)
    recipients = sorted(m.to[0] for m in mail.outbox)
    assert recipients == ["a@example.com", "o@example.com"]
    assert "A laptop was stolen." in mail.outbox[0].body
    with tenant_context(org):
        entry = AuditEntry.objects.get(action="customer_notice")
        assert entry.actor_id == staff.pk
        assert Message.objects.filter(type_key="platform_customer_notice").count() >= 2
    with tenant_context(other_org):
        assert not AuditEntry.objects.filter(action="customer_notice").exists()
    again = console.post(
        f"/api/v1/platform/customer-notices/{notice_id}/send", {"reason": "x"}, format="json"
    )
    assert again.status_code == 409
    assert owner.user.email == "o@example.com"


def test_customer_notices_are_for_platform_staff_only(org):
    customer = platform_client(UserFactory())
    assert customer.get("/api/v1/platform/customer-notices").status_code == 403


# --- tenant list MRR filter and integration status ------------------------------------------------


def snapshot(org: Any, mrr: str, currency: str = "GBP") -> None:
    with tenant_context(org):
        SubscriptionSnapshot.objects.update_or_create(
            date=now().date(),
            defaults={"status": "active", "mrr": Decimal(mrr), "currency": currency},
        )


def test_tenant_list_filters_and_sorts_by_mrr(org, other_org, console):
    snapshot(org, "120.00")
    snapshot(other_org, "20.00")
    rows = console.get("/api/v1/platform/tenants", {"mrr_min": "50"}).json()["results"]
    assert [r["id"] for r in rows] == [str(org.pk)]
    assert rows[0]["snapshot_mrr"] == {"amount": "120.00", "currency": "GBP"}
    cheap = console.get("/api/v1/platform/tenants", {"mrr_max": "50", "currency": "gbp"}).json()
    assert str(other_org.pk) in {r["id"] for r in cheap["results"]}
    assert str(org.pk) not in {r["id"] for r in cheap["results"]}
    ordered = console.get("/api/v1/platform/tenants", {"ordering": "-latest_mrr"}).json()
    ids = [r["id"] for r in ordered["results"]]
    assert ids.index(str(org.pk)) < ids.index(str(other_org.pk))


def test_tenant_detail_shows_integration_status(org, console):
    with tenant_context(org):
        IntegrationConnection.objects.create(
            provider="xero", level="organisation", status="error", secret="s3cret"
        )
    body = console.get(f"/api/v1/platform/tenants/{org.pk}").json()
    rows = {r["provider"]: r for r in body["integrations"]}
    assert rows["xero"]["status"] == "error"
    assert "s3cret" not in str(body)


# --- support reply notifications ------------------------------------------------------------------


def test_a_support_reply_emails_and_notifies_the_person(org, console, staff):
    opener = UserFactory(email="asker@example.com")
    with tenant_context(org):
        MembershipFactory(organisation=org, user=opener, role="admin")
        conversation = SupportConversationFactory(organisation=org, opened_by=opener)
    reply = console.post(
        f"/api/v1/platform/support/{conversation.pk}/reply",
        {"body": "Open Billing, then Invoice runs."},
        format="json",
    )
    assert reply.status_code == 201, reply.content
    with tenant_context(org):
        messages = Message.objects.filter(type_key="support_reply")
        assert {m.channel for m in messages} >= {"email", "in_app"}
        assert all(m.recipient_id == str(opener.pk) for m in messages)
    assert any("Invoice runs" in m.body for m in mail.outbox)
    # A customer's own message notifies nobody.
    with tenant_context(org):
        success.post_message(conversation, opener, body="Thanks!")
        assert Message.objects.filter(type_key="support_reply").count() == messages.count()


# --- revenue share --------------------------------------------------------------------------------


@given(
    processed=st.decimals(min_value=0, max_value=10_000_000, places=2),
    percent=st.decimals(min_value=0, max_value=10, places=2),
)
def test_revenue_share_mrr_rounds_half_up_to_pence(processed: Decimal, percent: Decimal) -> None:
    value = metrics.revenue_share_mrr(processed, percent, "GBP")
    assert value >= 0
    assert value == value.quantize(Decimal("0.01"))
    assert abs(value - processed * percent / 100) <= Decimal("0.005")


def test_revenue_share_counts_in_mrr_and_reconciles(org, console, monkeypatch):
    subscribe(org, "agency_payg")
    yesterday = now().date() - timedelta(days=1)
    with tenant_context(org):
        MeterReport.objects.create(
            meter="tutortrack_revenue", period_date=yesterday, quantity=100000,
            identifier=f"rev:{org.pk}:{yesterday}", reported_at=now(),
        )  # fmt: skip
        value = insights.subscription_value()
        assert value["revenue_share_mrr"] == Decimal("15.00")  # 1.5% of £1,000
        assert value["mrr"] >= Decimal("15.00")
    processed = {"GBP": Decimal("1000.00")}
    monkeypatch.setattr(
        "tutortrack.payments.selectors.processed_totals",
        lambda start, end: processed if start.date() == yesterday else {},
    )
    month = yesterday.replace(day=1)
    report = console.get("/api/v1/platform/revenue-share", {"month": month.isoformat()[:7]})
    assert report.status_code == 200, report.content
    row = next(r for r in report.json()["rows"] if r["organisation_id"] == str(org.pk))
    assert row["ok"] is True
    assert row["expected_fee"] == "15.00"
    # A late payment on the same day, and an earlier day nobody reported.
    processed["GBP"] = Decimal("1200.00")
    day_before = yesterday - timedelta(days=1)
    if day_before.month == yesterday.month:
        monkeypatch.setattr(
            "tutortrack.payments.selectors.processed_totals",
            lambda start, end: (
                {"GBP": Decimal("1200.00")} if start.date() in (yesterday, day_before) else {}
            ),
        )
    with tenant_context(org):
        row = revenue_share.reconcile_organisation(month)
    assert row is not None
    assert row["ok"] is False
    assert yesterday.isoformat() in row["changed_days"]
    if day_before.month == yesterday.month:
        assert row["unreported_days"] == [day_before.isoformat()]
        fixed = console.post(
            "/api/v1/platform/revenue-share/report-missing",
            {"organisation_id": str(org.pk), "month": month.isoformat()[:7]},
            format="json",
        )
        assert fixed.json() == {"count": 1}


# --- failed and stuck workflows -------------------------------------------------------------------


def link(org: Any, workflow_id: str, status: str, **extra: Any) -> WorkflowLink:
    with tenant_context(org):
        return WorkflowLink.objects.create(
            workflow_id=workflow_id,
            workflow_type="DemoReminderWorkflow",
            process="demo-reminder",
            status=status,
            started_at=now(),
            **extra,
        )


def test_failed_and_stuck_workflows_across_organisations(org, other_org, console):
    link(org, "demo:1", "failed", last_error="boom")
    link(other_org, "demo:2", "running", last_error="activity retrying")
    link(org, "demo:3", "running")  # healthy
    link(org, "demo:4", "completed")
    rows = console.get("/api/v1/platform/workflows").json()["results"]
    ids = {r["workflow_id"] for r in rows}
    assert ids == {"demo:1", "demo:2"}
    failed = console.get("/api/v1/platform/workflows", {"state": "failed"}).json()["results"]
    assert [r["workflow_id"] for r in failed] == ["demo:1"]
    assert failed[0]["organisation_name"] == org.name
    assert failed[0]["temporal_url"].endswith("/workflows/demo%3A1")


def test_workflow_actions_are_audited_with_a_reason(org, console, staff, monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "tutortrack.core.workflows.ops.terminate_now",
        lambda wid, reason: calls.append(("terminate", wid)),
    )
    monkeypatch.setattr(
        workflow_console, "reset_now", lambda wid, reason: calls.append(("reset", wid)) or "run-2"
    )
    monkeypatch.setattr(
        workflow_console, "_restart", lambda link: calls.append(("retry", link.workflow_id))
    )
    link(org, "demo:9", "running", last_error="stuck")
    url = f"/api/v1/platform/workflows/{org.pk}/demo:9"
    assert (
        console.post(url, {"action": "terminate", "reason": ""}, format="json").status_code == 400
    )
    done = console.post(url, {"action": "terminate", "reason": "INC-7"}, format="json")
    assert done.status_code == 200, done.content
    assert done.json()["status"] == "terminated"
    reset = console.post(url, {"action": "reset", "reason": "fixed in 1.2"}, format="json")
    assert reset.json()["status"] == "running"
    assert reset.json()["run_id"] == "run-2"
    link(org, "demo:10", "failed")
    retry = console.post(
        f"/api/v1/platform/workflows/{org.pk}/demo:10",
        {"action": "retry", "reason": "provider back"},
        format="json",
    )
    assert retry.status_code == 200, retry.content
    assert calls == [("terminate", "demo:9"), ("reset", "demo:9"), ("retry", "demo:10")]
    with tenant_context(org):
        actions = set(AuditEntry.objects.filter(object_type="core.workflowlink").values_list(
            "action", flat=True
        ))  # fmt: skip
        assert actions >= {"terminate", "reset", "restart"}
        assert AuditEntry.objects.filter(actor_id=staff.pk, action="terminate").exists()


def test_workflow_console_is_for_platform_staff_only(org):
    assert platform_client(UserFactory()).get("/api/v1/platform/workflows").status_code == 403
