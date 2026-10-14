"""E30-TW1 (Part 2): the nightly platform insights run on Temporal.

``PlatformInsightsWorkflow`` runs from a platform Temporal Schedule (daily 03:30 UTC,
``schedules.ensure_insights_schedule``) or from "Run now" in the console:

1. list the organisations to score (platform activity, BYPASSRLS);
2. for each batch of organisations: snapshot the subscription (MRR) and score health,
   each inside its own tenant context (idempotent per organisation and day);
3. email platform staff about organisations that became at risk (once per day each).

No ``next_*_at`` columns or sweepers: the schedule is the timer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from tutortrack.core.workflows import platform_activity, register_workflow

INSIGHTS_PROCESS = "platform-insights"
BATCH = 25
TIMEOUT = timedelta(minutes=5)
LONG = timedelta(minutes=30)
RETRY = RetryPolicy(maximum_attempts=5, maximum_interval=timedelta(minutes=10))


@dataclass(frozen=True, kw_only=True)
class InsightsInput:
    day: str = ""  # ISO date; empty = the run's date (UTC)


@dataclass(frozen=True, kw_only=True)
class InsightsBatch:
    day: str
    organisation_ids: list[str] = field(default_factory=list)


@platform_activity
def insights_targets(input: InsightsInput) -> list[str]:
    from . import insights

    return insights.targets()


@platform_activity
def insights_score_batch(batch: InsightsBatch) -> dict[str, Any]:
    """Score each organisation in its own tenant context. One organisation failing (e.g.
    closed mid-run) is logged and skipped so it can't hold up the others."""
    import sentry_sdk
    import structlog

    from tutortrack.core.context import tenant_context

    from . import insights

    logger = structlog.get_logger(__name__)
    day = date.fromisoformat(batch.day)
    scored, at_risk, failed = 0, [], 0
    for organisation_id in batch.organisation_ids:
        try:
            with tenant_context(organisation_id):
                result = insights.record_day(day)
        except Exception as exc:
            failed += 1
            sentry_sdk.capture_exception(exc)
            logger.warning("platform.insights_failed", organisation_id=organisation_id)
            continue
        scored += 1
        if result["newly_at_risk"]:
            at_risk.append(organisation_id)
    return {"scored": scored, "newly_at_risk": at_risk, "failed": failed}


@platform_activity
def insights_alert(batch: InsightsBatch) -> int:
    from . import insights

    return insights.send_churn_alerts(date.fromisoformat(batch.day), batch.organisation_ids)


@register_workflow(process=INSIGHTS_PROCESS, task_queue="default")
@workflow.defn
class PlatformInsightsWorkflow:
    def __init__(self) -> None:
        self.step = "starting"

    @workflow.query
    def state(self) -> dict[str, str]:
        return {"step": self.step}

    @workflow.run
    async def run(self, input: InsightsInput) -> dict[str, Any]:
        day = input.day or workflow.now().date().isoformat()
        self.step = "listing"
        ids: list[str] = await workflow.execute_activity(
            insights_targets, input, start_to_close_timeout=TIMEOUT, retry_policy=RETRY
        )
        scored, failed, at_risk = 0, 0, []
        for start in range(0, len(ids), BATCH):
            self.step = f"scoring {start}/{len(ids)}"
            result = await workflow.execute_activity(
                insights_score_batch,
                InsightsBatch(day=day, organisation_ids=ids[start : start + BATCH]),
                start_to_close_timeout=LONG,
                retry_policy=RETRY,
            )
            scored += result["scored"]
            failed += result["failed"]
            at_risk += result["newly_at_risk"]
        alerted = 0
        if at_risk:
            self.step = "alerting"
            alerted = await workflow.execute_activity(
                insights_alert,
                InsightsBatch(day=day, organisation_ids=at_risk),
                start_to_close_timeout=TIMEOUT,
                retry_policy=RETRY,
            )
        self.step = "done"
        return {
            "day": day,
            "scored": scored,
            "failed": failed,
            "at_risk": len(at_risk),
            "alerted": alerted,
        }
