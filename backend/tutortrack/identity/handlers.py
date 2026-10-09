"""Subscribers to other apps' events (idempotent: keyed by the outbox)."""

from __future__ import annotations

import structlog

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.exceptions import BusinessRuleViolation

from .models import Invitation, Membership

logger = structlog.get_logger(__name__)


@subscribe("onboarding.step_completed")
def invite_tutors_from_onboarding(event: EventEnvelope) -> None:
    """The wizard's "Invite your tutors" step (FR-02-6) sends real invitations."""
    if event.data.get("step") != "tutors" or event.data.get("skipped"):
        return
    from .services import invite

    for email in event.data.get("answers", {}).get("emails", []):
        if Invitation.objects.filter(email=email.lower()).exists():
            continue  # already invited (idempotent on retries)
        try:
            invite(email, role=Membership.Role.TUTOR)
        except BusinessRuleViolation as exc:
            logger.info("onboarding.invite_skipped", reason=exc.detail)


@subscribe("security.alert")
def email_owners_about_security_alerts(event: EventEnvelope) -> None:
    """FR-29-2: owners hear about suspicious activity (mass exports, ...)."""
    from .tasks import send_security_alert

    owners = list(
        Membership.objects.filter(
            role=Membership.Role.OWNER, status=Membership.Status.ACTIVE
        ).values_list("user__email", flat=True)
    )
    actor = str(event.subject.get("id") or "")
    from .models import User

    who = User.objects.filter(pk=actor).values_list("email", flat=True).first() or "someone"
    for email in owners:
        send_security_alert.delay(
            email=email,
            kind=str(event.data.get("kind", "")),
            detail=str(event.data.get("detail", "")),
            who=who,
        )
