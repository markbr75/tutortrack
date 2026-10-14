"""Logins in DSARs and erasure (E29 Part 2, ADR 0028).

A ``User`` is a global login that may belong to other organisations, so an organisation's
erasure ends the person's membership here (``revoke``) and removes pending invitations;
deleting the login itself is the person's own account deletion (platform, E30)."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils.translation import gettext as _

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    Section,
    register,
)

from .models import Invitation, LoginEvent, Membership, MFADevice, SocialAccount, User, UserSession


def expand(person: Person) -> None:
    for user in User.objects.filter(pk__in=person.of("identity.user")):
        person.add_terms(names=[user.get_full_name()], emails=[user.email], phones=[user.phone])


def export(person: Person) -> list[Section]:
    users = person.of("identity.user")
    if not users:
        return []
    profile = [
        {
            "id": str(u.pk),
            "email": u.email,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "preferred_name": u.preferred_name,
            "pronouns": u.pronouns,
            "phone": u.phone,
            "timezone": u.timezone,
            "locale": u.locale,
            "date_joined": u.date_joined,
            "last_login": u.last_login,
        }
        for u in User.objects.filter(pk__in=users)
    ]
    memberships = [
        {
            "id": str(m.pk),
            "role": m.role,
            "status": m.status,
            "title": m.title,
            "joined_at": m.joined_at,
            "last_active_at": m.last_active_at,
        }
        for m in Membership.objects.filter(user_id__in=users)
    ]
    logins = [
        {
            "id": str(e.pk),
            "at": e.created_at,
            "method": e.method,
            "success": e.success,
            "ip": e.ip,
            "user_agent": e.user_agent,
            "country": e.country,
        }
        for e in LoginEvent.objects.filter(user_id__in=users).order_by("-created_at")[:200]
    ]
    sessions = [
        {"id": str(s.pk), "ip": s.ip, "user_agent": s.user_agent, "last_seen_at": s.last_seen_at}
        for s in UserSession.objects.filter(user_id__in=users, revoked_at__isnull=True)
    ]
    security = [
        {"id": str(d.pk), "kind": d.kind, "name": d.name, "confirmed_at": d.confirmed_at}
        for d in MFADevice.objects.filter(user_id__in=users)
    ] + [
        {"id": str(a.pk), "provider": a.provider, "email": a.email}
        for a in SocialAccount.objects.filter(user_id__in=users)
    ]
    from tutortrack.privacy.models import TermsAcceptance

    terms = [  # G6: the platform terms this login accepted
        {"version": a.version, "context": a.context, "at": a.accepted_at, "ip": a.ip}
        for a in TermsAcceptance.objects.filter(user_id__in=users)
    ]
    return [
        Section("identity.profile", _("Login and profile"), profile),
        Section("identity.terms", _("TutorTrack terms accepted"), terms),
        Section("identity.memberships", _("Access to this organisation"), memberships),
        Section("identity.logins", _("Sign-in history"), logins),
        Section("identity.sessions", _("Signed-in devices"), sessions),
        Section("identity.security", _("Two-factor and connected accounts"), security),
    ]


def _invitations(person: Person) -> Any:
    q = Q(
        target_type__in=["people.contact", "people.student"],
        target_id__in=[*person.of("people.contact"), *person.of("people.student")],
    )
    if person.emails:
        q |= Q(email__in=sorted(person.emails))
    return Invitation.objects.filter(q).exclude(status=Invitation.Status.ACCEPTED)


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    out.deleted += _invitations(person).delete()[0]
    out.anonymised += (
        Membership.objects.filter(user_id__in=person.of("identity.user"))
        .exclude(title="")
        .update(title="")
    )
    if person.of("identity.user"):
        out.retained += len(person.of("identity.user"))
        out.notes.append("global logins kept for other organisations; membership here ended")
    return out


def revoke(person: Person) -> int:
    from .services import update_membership

    count = 0
    for membership in Membership.objects.filter(
        user_id__in=person.of("identity.user"), status=Membership.Status.ACTIVE
    ):
        if membership.role == Membership.Role.OWNER:
            continue  # an owner's access ends by transferring ownership, not erasure
        update_membership(membership, status=Membership.Status.REMOVED)
        count += 1
    return count


register(
    Provider(
        key="identity",
        label="Logins",
        expand=expand,
        export=export,
        erase=erase,
        revoke=revoke,
        order=900,
    )
)
