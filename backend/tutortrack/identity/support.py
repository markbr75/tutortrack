"""TutorTrack support access (E30 FR-30-2).

Platform staff view an organisation as one of its users only with a reason (and ticket),
read-only unless the organisation granted write access. Organisations can require a grant
before support may look at all (``security.support_access_requires_grant``). Every session
is recorded (``SupportSession``), audited and announced to the organisation's owners.

The console runs on the platform host, so it hands the browser a single-use link to the
tenant's host (``/api/v1/support/enter?token=``), which signs the staff member in there and
starts the impersonation (``identity.impersonation``).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.http import HttpRequest
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from tutortrack.core.time import now

from .impersonation import SESSION_KEY
from .models import Membership, SupportAccessGrant, SupportSession, User

TOKEN_TTL = timedelta(minutes=5)
MAX_GRANT_DAYS = 30


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def active_grant() -> SupportAccessGrant | None:
    return (
        SupportAccessGrant.objects.filter(revoked_at__isnull=True, expires_at__gt=now())
        .order_by("-allow_write", "-expires_at")
        .first()
    )


@transaction.atomic
def grant_access(*, days: int, allow_write: bool, note: str, user: Any) -> SupportAccessGrant:
    if not 1 <= days <= MAX_GRANT_DAYS:
        raise BusinessRuleViolation(_("Grant access for 1 to 30 days."))
    grant = SupportAccessGrant.objects.create(
        granted_by=user, expires_at=now() + timedelta(days=days), allow_write=allow_write,
        note=note[:255],
    )  # fmt: skip
    audit.record_create(grant)
    return grant


@transaction.atomic
def revoke_grant(grant: SupportAccessGrant) -> SupportAccessGrant:
    if grant.revoked_at is None:
        with audit.track(grant, action="revoke"):
            grant.revoked_at = now()
            grant.save(update_fields=["revoked_at", "updated_at"])
    return grant


@transaction.atomic
def start_session(
    *, staff: User, membership: Membership, reason: str, ticket: str = "", write: bool = False
) -> tuple[SupportSession, str]:
    """Called by the platform console inside the organisation's tenant context. Returns the
    session and the raw single-use token for the hand-off link."""
    from tutortrack.tenancy.settings_service import get_setting

    if not staff.is_platform_staff:
        raise PermissionDenied()
    if len(reason.strip()) < 5:
        raise BusinessRuleViolation(
            _("Give a reason (and ticket) for accessing this account."),
            extra={"errors": {"reason": [_("Required.")]}},
        )
    if membership.status != Membership.Status.ACTIVE:
        raise BusinessRuleViolation(_("That member isn't active."))
    grant = active_grant()
    if get_setting("security.support_access_requires_grant") and grant is None:
        raise PermissionDenied(_("This organisation requires a support access grant."))
    if write and not (grant and grant.allow_write):
        raise PermissionDenied(_("Write access needs a grant from the organisation."))
    raw = secrets.token_urlsafe(32)
    session = SupportSession.objects.create(
        staff_user=staff,
        staff_name=staff.get_full_name() or staff.email,
        target_membership=membership,
        reason=reason.strip()[:500],
        ticket=ticket.strip()[:100],
        write=write,
        grant=grant,
        token_hash=_hash(raw),
        token_expires_at=now() + TOKEN_TTL,
    )
    audit.record(
        session, "support_access",
        {"reason": [None, session.reason], "write": [None, write],
         "membership": [None, str(membership.pk)]},
    )  # fmt: skip
    _announce(session)
    return session, raw


def _announce(session: SupportSession) -> None:
    from tutortrack.comms import services as comms

    title = _("TutorTrack support accessed your account")
    body = _("%(name)s viewed the account as %(member)s. Reason: %(reason)s") % {
        "name": session.staff_name,
        "member": session.target_membership.user.email,
        "reason": session.reason,
    }
    comms.notify("staff_support_access", (title, body, "/settings"), key=f"support:{session.pk}")


@transaction.atomic
def enter(request: HttpRequest, raw_token: str) -> SupportSession:
    """Exchange the hand-off token on the tenant's host: sign the staff member in and start
    viewing as the target member."""
    from .auth import complete_login

    session = (
        SupportSession.objects.select_for_update()
        .select_related("staff_user", "target_membership")
        .filter(token_hash=_hash(raw_token))
        .first()
    )
    if session is None or session.entered_at or session.token_expires_at <= now():
        raise NotFound(_("This support link has expired."))
    staff = session.staff_user
    if not (staff.is_active and staff.is_platform_staff):
        raise PermissionDenied()
    complete_login(request, staff, method="support", mfa_verified=True)
    target = session.target_membership
    request.session[SESSION_KEY] = {
        "impersonator_id": str(staff.pk),
        "target_user_id": str(target.user_id),
        "membership_id": str(target.pk),
        "organisation_id": str(target.organisation_id),
        "write": session.write,
        "started_at": now().isoformat(),
        "support_session_id": str(session.pk),
    }
    session.entered_at = now()
    session.save(update_fields=["entered_at", "updated_at"])
    return session


def end(session_id: str) -> None:
    SupportSession.objects.filter(pk=session_id, ended_at__isnull=True).update(ended_at=now())
