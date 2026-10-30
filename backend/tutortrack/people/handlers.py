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


@subscribe("membership.renamed")
def rename_own_tutor_profile(event: EventEnvelope) -> None:
    """A member renamed themselves on their account: their own tutor record follows, so
    "My tutor profile" and lessons show the new name. Idempotent (no change, no write)."""
    from .models import TutorProfile
    from .services import update_tutor

    tutor = TutorProfile.objects.filter(membership_id=event.subject["id"]).first()
    if tutor is None:
        return
    names = {
        "first_name": event.data.get("first_name", tutor.first_name),
        "last_name": event.data.get("last_name", tutor.last_name),
    }
    changes = {k: v for k, v in names.items() if v and v != getattr(tutor, k)}
    if changes:
        update_tutor(tutor, **changes)


@subscribe("onboarding.step_completed")
def add_first_student_from_onboarding(event: EventEnvelope) -> None:
    """The wizard's "Your first student" step (FR-02-6) adds the family."""
    if event.data.get("step") != "students" or event.data.get("skipped"):
        return
    answers = event.data.get("answers", {})
    from .services import add_first_student

    add_first_student(
        student_first_name=answers["student_first_name"],
        student_last_name=answers.get("student_last_name", ""),
        contact_name=answers.get("contact_name", ""),
        contact_email=answers.get("contact_email", ""),
    )
