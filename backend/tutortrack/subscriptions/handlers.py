"""Subscription reactions to domain events (idempotent) and the Temporal bridge (E04-TW1)."""

from __future__ import annotations

from django.conf import settings

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import (
    DunningInput,
    SubscriptionDunningWorkflow,
    TrialInput,
    TrialLifecycleWorkflow,
    dunning_workflow_id,
    trial_workflow_id,
)


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


@subscribe("organisation.created")
def start_trial(event: EventEnvelope) -> None:
    """Every new organisation starts on a trial (FR-04-3)."""
    from tutortrack.tenancy.models import Organisation

    from . import services

    organisation = Organisation.objects.filter(pk=event.subject["id"]).first()
    if organisation is not None and not organisation.is_closed:
        services.start_trial(organisation)


@subscribe("organisation.closed")
def cancel_on_closure(event: EventEnvelope) -> None:
    """Closing the account stops the subscription at the period end."""
    from . import services
    from .models import Subscription

    subscription = services.current()
    if subscription is None or subscription.cancel_at_period_end:
        return
    if subscription.status in (Subscription.Status.CANCELLED, Subscription.Status.SUSPENDED):
        return
    services.cancel("closing", "")


@subscribe(
    "tutor.created", "tutor.status_changed", "branch.created", "branch.archived",
    "lesson.completed",
)  # fmt: skip
def seats_may_have_changed(event: EventEnvelope) -> None:
    """Debounced: one seat sync a few minutes after a burst of changes (FR-04-4)."""
    from .tasks import schedule_seat_sync

    schedule_seat_sync(event.organisation_id)


bridge.on(
    "subscription.started",
    start=TrialLifecycleWorkflow,
    id=lambda e: trial_workflow_id(e.organisation_id),
    input=lambda e: TrialInput(
        organisation_id=str(e.organisation_id), trial_ends_at=e.data["trial_ends_at"]
    ),
    when=lambda e: e.data.get("status") == "trialing" and bool(e.data.get("trial_ends_at")),
)

bridge.on(
    "subscription.past_due",
    start=SubscriptionDunningWorkflow,
    id=lambda e: dunning_workflow_id(e.organisation_id, e.data["invoice_id"]),
    input=lambda e: DunningInput(
        organisation_id=str(e.organisation_id),
        invoice_id=e.data["invoice_id"],
        notice_days=list(settings.SUBSCRIPTIONS["DUNNING_NOTICE_DAYS"]),
        suspend_after_days=int(settings.SUBSCRIPTIONS["SUSPEND_AFTER_DAYS"]),
    ),
)

bridge.on(
    "subscription.changed",
    signal="paid",
    id=lambda e: dunning_workflow_id(e.organisation_id, e.data.get("invoice_id")),
    when=lambda e: (
        e.data.get("change") == "payment_recovered"
        and bool(e.data.get("invoice_id"))
        and _running(dunning_workflow_id(e.organisation_id, e.data.get("invoice_id")))
    ),
)
