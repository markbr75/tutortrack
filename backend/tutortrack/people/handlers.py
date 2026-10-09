from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe


@subscribe("user.joined")
def link_tutor_profile(event: EventEnvelope) -> None:
    """An invited tutor accepted: attach their membership to the waiting tutor profile."""
    from tutortrack.identity.models import Membership

    from .models import TutorProfile
    from .services import link_membership

    membership = Membership.objects.select_related("user").filter(pk=event.subject["id"]).first()
    if membership is None or membership.role != Membership.Role.TUTOR:
        return
    tutor = TutorProfile.objects.filter(email=membership.user.email).first()
    if tutor is not None:
        link_membership(tutor, membership)


@subscribe("user.joined")
def link_portal_user(event: EventEnvelope) -> None:
    """An invited parent or student accepted: attach their login to the contact/student the
    invitation was for (E15)."""
    from tutortrack.identity.models import Invitation, Membership

    from .services import link_portal_user as link

    membership = Membership.objects.select_related("user").filter(pk=event.subject["id"]).first()
    if membership is None or membership.role not in {
        Membership.Role.CLIENT,
        Membership.Role.STUDENT,
    }:
        return
    invitation = (
        Invitation.objects.filter(accepted_by=membership.user, status=Invitation.Status.ACCEPTED)
        .exclude(target_type="")
        .order_by("-accepted_at")
        .first()
    )
    if invitation is not None:
        link(invitation.target_type, invitation.target_id, membership.user)
