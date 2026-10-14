"""E30 Part 2 console: nightly insights (snapshots and health), SaaS metrics, NPS, product
usage and the support inbox; the insights workflow on Temporal (E30-TW1 Part 2)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.core import mail

from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import UserFactory
from tutortrack.platform_admin import insights
from tutortrack.platform_admin.models import SubscriptionSnapshot, TenantHealthScore
from tutortrack.platform_admin.processes import InsightsInput, PlatformInsightsWorkflow
from tutortrack.platform_admin.tests.test_platform import platform_client
from tutortrack.subscriptions import services as subscriptions
from tutortrack.subscriptions.models import Subscription
from tutortrack.success.models import SupportConversation
from tutortrack.success.tests.factories import (
    ProductEventFactory,
    SupportMessageFactory,
    SurveyResponseFactory,
)

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "platform"])
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


@pytest.fixture
def staff() -> Any:
    return UserFactory(is_platform_staff=True, first_name="Pat", last_name="Support")


@pytest.fixture
def console(staff: Any) -> Any:
    return platform_client(staff)


def snap(org: Any, day: date, status: str, mrr: str, currency: str = "GBP", **extra: Any) -> None:
    with tenant_context(org):
        SubscriptionSnapshot.objects.update_or_create(
            date=day,
            defaults={
                "status": status,
                "mrr": Decimal(mrr),
                "currency": currency,
                "signed_up_on": extra.get("signed_up_on", day),
                "plan_key": "team",
            },
        )


# --- nightly insights ---------------------------------------------------------------------------


def test_record_day_snapshots_the_subscription_and_scores_health(org):
    subscriptions.start_trial(org)
    with tenant_context(org):
        Subscription.objects.update(plan=subscriptions.get_plan("team"), status="active", seats=5)
        today = now().date()
        result = insights.record_day(today)
        again = insights.record_day(today)  # idempotent: same row replaced
        snapshot = SubscriptionSnapshot.objects.get()
        score = TenantHealthScore.objects.get()
    assert snapshot.status == "active"
    assert snapshot.plan_key == "team"
    assert snapshot.mrr > 0
    assert snapshot.signed_up_on == org.created_at.date()
    assert 0 <= score.score <= 100
    assert score.risk == result["risk"] == again["risk"]
    assert set(score.components) == {"usage", "tutors", "payments", "reliability", "support", "nps"}
    assert result["newly_at_risk"] is False  # no earlier score to fall from


def test_churn_alert_goes_to_platform_staff_once(org, staff):
    with tenant_context(org):
        TenantHealthScore.objects.create(
            date=now().date() - timedelta(days=1), score=80, risk="healthy", components={}
        )
        result = insights.record_day(now().date())  # an idle organisation scores low
    assert result["risk"] == "at_risk"
    assert result["newly_at_risk"] is True
    assert insights.send_churn_alerts(now().date(), [str(org.pk)]) == 1
    assert insights.send_churn_alerts(now().date(), [str(org.pk)]) == 0
    assert len(mail.outbox) == 1
    assert staff.email in mail.outbox[0].to
    assert org.name in mail.outbox[0].body


def test_insights_workflow_scores_every_organisation(org, other_org, staff, temporal_env):
    with tenant_context(org):
        TenantHealthScore.objects.create(
            date=date(2026, 10, 12), score=90, risk="healthy", components={}
        )
    wid = "platform-insights:platform:test-run"
    temporal_env.run(
        temporal_env.client.start_workflow(
            PlatformInsightsWorkflow.run,
            InsightsInput(day="2026-10-13"),
            id=wid,
            task_queue="default",
        )
    )
    result = temporal_env.result(wid)
    assert result["scored"] >= 2
    assert result["failed"] == 0
    assert result["at_risk"] >= 1
    assert result["alerted"] == result["at_risk"]
    for tenant in (org, other_org):
        with tenant_context(tenant):
            assert TenantHealthScore.objects.filter(date=date(2026, 10, 13)).exists()
            assert SubscriptionSnapshot.objects.filter(date=date(2026, 10, 13)).exists()
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        name = "PlatformInsightsWorkflow-scored.json"
        (HISTORIES / name).write_text(temporal_env.history_json(wid))


def test_insights_history_replays():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("PlatformInsightsWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[PlatformInsightsWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )


def test_the_nightly_schedule_is_a_platform_schedule(temporal_local_env):
    from tutortrack.platform_admin.schedules import ensure_insights_schedule

    sid = ensure_insights_schedule()
    assert sid == "schedule:platform-insights:platform"
    assert ensure_insights_schedule() == sid  # idempotent update

    async def describe() -> Any:
        return await temporal_local_env.client.get_schedule_handle(sid).describe()

    described = temporal_local_env.run(describe())
    action = described.schedule.action
    assert action.workflow == "PlatformInsightsWorkflow"
    assert action.task_queue == "default"
    assert action.id == "platform-insights:platform"

    async def delete() -> None:
        await temporal_local_env.client.get_schedule_handle(sid).delete()

    temporal_local_env.run(delete())


# --- console: health ----------------------------------------------------------------------------


def test_health_worklist_lowest_first_with_history(org, other_org, console):
    for tenant, value, risk in ((org, 30, "at_risk"), (other_org, 85, "healthy")):
        with tenant_context(tenant):
            TenantHealthScore.objects.create(
                date=now().date(),
                score=value,
                risk=risk,
                components={
                    "usage": value,
                    "tutors": None,
                    "payments": None,
                    "reliability": 100,
                    "support": 100,
                    "nps": None,
                },
            )
    rows = console.get("/api/v1/platform/health").json()["results"]
    assert [r["id"] for r in rows[:2]] == [str(org.pk), str(other_org.pk)]
    assert rows[0]["components"]["usage"] == 30
    at_risk = console.get("/api/v1/platform/health", {"risk": "at_risk"}).json()["results"]
    assert [r["id"] for r in at_risk] == [str(org.pk)]
    counts = console.get("/api/v1/platform/health/risk-counts").json()
    assert counts["at_risk"] == 1
    assert counts["healthy"] == 1
    history = console.get(f"/api/v1/platform/tenants/{org.pk}/health").json()
    assert history[0]["score"] == 30


def test_console_needs_platform_staff(org):
    tenant_admin = platform_client(UserFactory())
    for url in [
        "/api/v1/platform/health",
        "/api/v1/platform/saas-metrics",
        "/api/v1/platform/nps",
        "/api/v1/platform/usage",
        "/api/v1/platform/support",
    ]:
        assert tenant_admin.get(url).status_code == 403


# --- console: SaaS metrics ----------------------------------------------------------------------


def test_saas_metrics_from_snapshots(org, other_org, console):
    today = now().date()
    last_month_end = today.replace(day=1) - timedelta(days=1)
    signed = last_month_end.replace(day=1)
    snap(org, last_month_end, "active", "100.00", signed_up_on=signed)
    snap(org, today, "active", "150.00", signed_up_on=signed)
    snap(other_org, last_month_end, "trialing", "0", signed_up_on=signed)
    snap(other_org, today, "active", "50.00", signed_up_on=signed)
    snap(other_org, today - timedelta(days=400), "active", "1.00", currency="USD")
    body = console.get("/api/v1/platform/saas-metrics", {"months": 2}).json()
    assert body["currency"] == "GBP"
    assert body["currencies"] == ["GBP", "USD"]
    current = body["months"][-1]
    assert current["mrr"] == {"amount": "200.00", "currency": "GBP"}
    assert current["arr"]["amount"] == "2400.00"
    assert current["customers"] == 2
    assert current["arpa"]["amount"] == "100.00"
    assert current["new_mrr"]["amount"] == "50.00"
    assert current["expansion_mrr"]["amount"] == "50.00"
    assert current["churned_customers"] == 0
    assert current["net_revenue_retention"] == "1.5000"
    trials = body["trial_conversion"]
    assert trials[-1]["trials"] == 1
    assert trials[-1]["conversion_rate"] == "1.0000"
    cohort = next(c for c in body["cohorts"] if c["size"] == 1 and c["month"] == str(signed))
    assert cohort["logo_retention"][:2] == ["1.0000", "1.0000"]
    usd = console.get("/api/v1/platform/saas-metrics", {"currency": "usd"}).json()
    assert usd["currency"] == "USD"
    assert usd["months"][-1]["mrr"]["amount"] == "0.00"


# --- console: NPS and usage ---------------------------------------------------------------------


def test_nps_summary_across_organisations(org, other_org, console):
    SurveyResponseFactory(organisation=org, score=10, comment="Love the calendar")
    SurveyResponseFactory(organisation=org, score=9)
    SurveyResponseFactory(organisation=other_org, score=3, comment="Too slow")
    SurveyResponseFactory(organisation=other_org, score=None)
    SurveyResponseFactory(organisation=other_org, kind="csat", score=4)
    body = console.get("/api/v1/platform/nps").json()
    assert (body["answers"], body["promoters"], body["detractors"]) == (3, 2, 1)
    assert body["nps"] == 33
    assert body["dismissed"] == 1
    assert body["csat_answers"] == 1
    assert body["csat_average"] == "4.00"
    assert {c["organisation"] for c in body["comments"]} == {org.name, other_org.name}
    assert "user" not in json.dumps(body["comments"])  # no respondent identity


def test_usage_and_onboarding_funnel(org, other_org, console):
    ProductEventFactory(organisation=org, actor="a" * 32)
    ProductEventFactory(organisation=org, actor="b" * 32, route="/calendar")
    ProductEventFactory(organisation=other_org, name="tour.completed", route="")
    with tenant_context(org):
        from tutortrack.success import services as success

        success.complete_item("service")
        success.complete_item("student")
    with tenant_context(other_org):
        success.complete_item("student")  # skipped the first step: not in the funnel past it
    body = console.get("/api/v1/platform/usage").json()
    assert body["events"] == 3
    assert body["people"] >= 3
    assert body["organisations"] == 2
    top = {e["name"]: e for e in body["top_events"]}
    assert top["page.viewed"]["count"] == 2
    assert top["page.viewed"]["people"] == 2
    funnel = {f["step"]: f["organisations"] for f in body["funnel"]}
    assert funnel["signed_up"] >= 2
    assert funnel["service"] == 1
    assert funnel["student"] == 1
    assert funnel["lesson"] == 0


# --- console: support inbox ---------------------------------------------------------------------


def test_support_inbox_spans_organisations_and_replies_in_tenant_context(
    org, other_org, console, staff
):
    mine = SupportMessageFactory(organisation=org).conversation
    theirs = SupportMessageFactory(organisation=other_org).conversation
    rows = console.get("/api/v1/platform/support").json()["results"]
    assert {r["id"] for r in rows} >= {str(mine.pk), str(theirs.pk)}
    unread = console.get("/api/v1/platform/support", {"status": "unread"}).json()["results"]
    assert str(mine.pk) in {r["id"] for r in unread}
    detail = console.get(f"/api/v1/platform/support/{mine.pk}").json()
    assert detail["organisation_name"] == org.name
    assert len(detail["messages"]) == 1
    reply = console.post(
        f"/api/v1/platform/support/{mine.pk}/reply",
        {"body": "Billing → Invoice run."},
        format="json",
    )
    assert reply.status_code == 201, reply.content
    body = reply.json()
    assert body["status"] == "answered"
    assert body["messages"][-1]["from_support"] is True
    assert body["assignee_name"] == "Pat Support"
    with tenant_context(org):
        conversation = SupportConversation.objects.get(pk=mine.pk)
        assert conversation.customer_unread is True
        entry = AuditEntry.objects.filter(object_type__endswith="supportmessage").latest(
            "created_at"
        )
        assert entry.actor_id == staff.pk  # the organisation's log shows who answered
    closed = console.post(f"/api/v1/platform/support/{mine.pk}/close").json()
    assert closed["status"] == "closed"
    assert console.get(f"/api/v1/platform/support/{uuid.uuid4()}").status_code == 404


def test_insights_run_now_starts_the_workflow(console, monkeypatch):
    started: list[str] = []
    monkeypatch.setattr(
        "tutortrack.platform_admin.schedules.run_now",
        lambda day=None: started.append("run") or "platform-insights:platform:manual",
    )
    response = console.post("/api/v1/platform/insights/run")
    assert response.status_code == 202
    assert started == ["run"]
