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
