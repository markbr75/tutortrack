"""Growth reactions to domain events (idempotent) and the Temporal bridge (E25-TW1)."""

from __future__ import annotations

from decimal import Decimal

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import (
    ReferralInput,
    ReferralRewardWorkflow,
    ReviewRequestInput,
    ReviewRequestWorkflow,
    referral_workflow_id,
    review_workflow_id,
)


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


def _check_referrals(organisation_id: object, client_ids: set[str]) -> None:
    """Tell running referral workflows of these referees to re-check their milestone."""
    from tutortrack.core.workflows import signal_now

    from .models import Referral

    pending = Referral.objects.filter(referee_id__in=client_ids, status=Referral.Status.PENDING)
    for referral in pending:
        wid = referral_workflow_id(organisation_id, referral.pk)
        if _running(wid):
            signal_now(wid, "milestone")


# --- reviews (T01) ------------------------------------------------------------------------------


@subscribe("lesson.completed")
def lessons_completed(event: EventEnvelope) -> None:
    """Review requests after N lessons; referral and tutor-referral lesson milestones."""
    from . import services

    attendees = list(event.data.get("attendees") or [])
    tutors = list(event.data.get("tutors") or [])
    services.lesson_completed(attendees, tutors)
    _check_referrals(event.organisation_id, {str(a["client_id"]) for a in attendees})
    services.tutor_lessons_completed([str(t["tutor_id"]) for t in tutors])


@subscribe("trial_lesson.completed")
def trial_completed(event: EventEnvelope) -> None:
    from . import services

    services.trial_completed(event.subject["id"])


# --- attribution (T03, T04, T06) ----------------------------------------------------------------


@subscribe("enquiry.received")
def attribute_enquiry(event: EventEnvelope) -> None:
    from . import services

    services.attribute_enquiry(event.subject["id"])


@subscribe("application.submitted")
def attribute_application(event: EventEnvelope) -> None:
    from . import services

    services.attribute_application(event.subject["id"])


@subscribe("application.approved")
def referred_tutor_approved(event: EventEnvelope) -> None:
    from . import services

    services.application_approved(event.subject["id"], event.data.get("tutor_id"))


# --- money (T03, T05, T06) ----------------------------------------------------------------------


@subscribe("payment.succeeded")
def payment_succeeded(event: EventEnvelope) -> None:
    from . import services

    services.record_payment_commission(event.subject["id"])
    client_id = str(event.data.get("client_id") or "")
    if client_id:
        _check_referrals(event.organisation_id, {client_id})
        services.client_paid(client_id)


@subscribe("payment.refunded")
def payment_refunded(event: EventEnvelope) -> None:
    from tutortrack.core.money import Money

    from . import services

    amount = event.data.get("amount") or {}
    if not amount.get("currency"):
        return
    services.record_refund_clawback(
        event.subject["id"],
        event.data.get("refund_id"),
        Money(Decimal(str(amount["amount"])), str(amount["currency"])),
    )


# --- affiliate logins and schedules (T04, T05) --------------------------------------------------


@subscribe("user.joined")
def link_affiliate_login(event: EventEnvelope) -> None:
    """An invited affiliate accepted: attach their login to the affiliate record."""
    from tutortrack.identity.models import Invitation, Membership

    from . import services

    membership = Membership.objects.select_related("user").filter(pk=event.subject["id"]).first()
    if membership is None or membership.role != Membership.Role.AFFILIATE:
        return
    invitation = (
        Invitation.objects.filter(
            accepted_by=membership.user,
            status=Invitation.Status.ACCEPTED,
            target_type="growth.affiliate",
        )
        .order_by("-accepted_at")
        .first()
    )
    if invitation is not None:
        services.link_affiliate_user(invitation.target_id, membership.user)


@subscribe("organisation.settings_updated")
def follow_statement_schedule(event: EventEnvelope) -> None:
    keys = set(event.data.get("keys") or [])
    if event.data.get("area") == "growth" and "growth.statement_schedule" in keys:
        from .schedules import sync_statement_schedule

        sync_statement_schedule()


# --- Temporal bridge (E25-TW1) ------------------------------------------------------------------


bridge.on(
    "review.requested",
    start=ReviewRequestWorkflow,
    id=lambda e: review_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: ReviewRequestInput(
        organisation_id=str(e.organisation_id), request_id=e.subject["id"]
    ),
    subject=lambda e: ("review_request", e.subject["id"]),
)
bridge.on(
    "review.submitted",
    signal="submitted",
    id=lambda e: review_workflow_id(e.organisation_id, e.data.get("request_id")),
    when=lambda e: (
        bool(e.data.get("request_id"))
        and _running(review_workflow_id(e.organisation_id, e.data.get("request_id")))
    ),
)
bridge.on(
    "referral.created",
    start=ReferralRewardWorkflow,
    id=lambda e: referral_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: ReferralInput(
        organisation_id=str(e.organisation_id), referral_id=e.subject["id"]
    ),
    subject=lambda e: ("referral", e.subject["id"]),
)
