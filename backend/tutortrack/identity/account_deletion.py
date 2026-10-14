"""Global account deletion (G6, FR-03-9 and FR-29-4): a person deletes their whole
TutorTrack login, across every organisation they belong to.

Safeguards: the person confirms with their password (or, without one, by typing their email
address); someone who is the last active owner of an organisation that is still open must
transfer ownership or close it first; platform staff accounts can't be deleted this way.

In each organisation (inside that tenant's context) the E29 erasure engine handles the
person's records there, following ``privacy.account_deletion``:

* ``erase`` (default): the erasure runs at once, as for an approved erasure request
  (financial records are kept, anonymised). When a legal hold applies, an erasure request
  is logged for the organisation's staff instead.
* ``review``: an erasure request (DSAR) is logged so the organisation decides.

Either way the membership ends. Then the login itself (TutorTrack's own data) is anonymised
rather than deleted, so foreign keys from organisations' records stay valid: name, email,
phone and profile are cleared, sign-in is disabled and every session, MFA device, passkey,
recovery code, linked SSO account, sign-in link and the login history are deleted. An
``AccountDeletion`` row (email kept only as a hash) is the evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import (
    request_context,
    reset_organisation,
    set_organisation,
    tenant_context,
)
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now

from .models import (
    AccountDeletion,
    LoginEvent,
    LoginToken,
    Membership,
    MFADevice,
    RecoveryCode,
    SocialAccount,
    User,
    UserSession,
    WebAuthnCredential,
)

OPEN_STATUSES = (Membership.Status.ACTIVE, Membership.Status.SUSPENDED, Membership.Status.INVITED)


class AccountDeletionBlocked(BusinessRuleViolation):
    problem_type = "account-deletion-blocked"
    title = "The account can't be deleted yet"


@dataclass(frozen=True)
class Blocker:
    organisation_id: str
    organisation_name: str
    reason: str  # last_owner | platform_staff


def email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def memberships(user: User) -> list[Membership]:
    """Every membership the person still has (any organisation)."""
    with request_context(user_id=user.pk):
        return list(
            Membership.all_tenants.filter(user_id=user.pk, status__in=OPEN_STATUSES)
            .select_related("organisation")
            .order_by("organisation__name")
        )


def _last_owner(membership: Membership) -> bool:
    if membership.role != Membership.Role.OWNER or membership.status != Membership.Status.ACTIVE:
        return False
    if membership.organisation.closed_at is not None:
        return False  # a closed organisation needs no owner
    with tenant_context(membership.organisation):
        owners = Membership.objects.filter(
            role=Membership.Role.OWNER, status=Membership.Status.ACTIVE
        ).count()
    return owners <= 1


def blockers(user: User) -> list[Blocker]:
    out = []
    if user.is_platform_staff or user.is_staff:
        out.append(Blocker("", "TutorTrack", "platform_staff"))
    for membership in memberships(user):
        if _last_owner(membership):
            org = membership.organisation
            out.append(Blocker(str(org.pk), org.name, "last_owner"))
    return out


def preview(user: User) -> dict[str, Any]:
    """What deleting the account will do (shown before the person confirms)."""
    from tutortrack.tenancy.settings_service import get_setting

    rows = []
    for membership in memberships(user):
        with tenant_context(membership.organisation):
            mode = str(get_setting("privacy.account_deletion") or "erase")
        rows.append(
            {
                "organisation_id": str(membership.organisation_id),
                "name": membership.organisation.name,
                "role": membership.role,
                "outcome": "erased" if mode == "erase" else "request_logged",
            }
        )
    return {
        "organisations": rows,
        "blockers": [b.__dict__ for b in blockers(user)],
        "needs_password": user.has_usable_password(),
    }


def _check_confirmation(user: User, *, password: str, confirm_email: str) -> None:
    if user.has_usable_password():
        if not password or not user.check_password(password):
            message = _("Your password is not correct.")
            raise BusinessRuleViolation(message, extra={"errors": {"password": [message]}})
    elif confirm_email.strip().lower() != user.email:
        message = _("Type your email address to confirm.")
        raise BusinessRuleViolation(message, extra={"errors": {"confirm_email": [message]}})


def _in_organisation(user: User, membership: Membership, reason: str) -> dict[str, Any]:
    """E29 erasure (or an erasure request) and the end of the membership, in one tenant."""
    from tutortrack.privacy import dsar
    from tutortrack.privacy.erasure import ErasureBlocked, erase_now
    from tutortrack.privacy.models import DataSubjectRequest
    from tutortrack.tenancy.settings_service import get_setting

    org = membership.organisation
    row: dict[str, Any] = {"organisation_id": str(org.pk), "name": org.name, "reference": ""}
    with tenant_context(org), transaction.atomic():
        # First, so the erasure's own login revocation (which refuses to remove the acting
        # person, and skips owners) finds nothing left to do.
        _end_membership(membership)
        mode = str(get_setting("privacy.account_deletion") or "erase")
        outcome = "request_logged"
        if mode == "erase":
            try:
                with transaction.atomic():
                    erase_now("identity.user", str(user.pk), reason="account")
                outcome = "erased"
            except ErasureBlocked:
                outcome = "request_logged"  # a legal hold: the organisation decides
        if outcome == "request_logged":
            request = dsar.log_request(
                kind=DataSubjectRequest.Kind.ERASURE,
                subject_type="identity.user",
                subject_id=str(user.pk),
                requester_name=user.get_full_name(),
                requester_email=user.email,
                channel=DataSubjectRequest.Channel.PORTAL,
                details=_("The person deleted their TutorTrack account. %(reason)s")
                % {"reason": reason},
                requester_user=user,
            )
            row["reference"] = request.reference
    row["outcome"] = outcome
    return row


def _end_membership(membership: Membership) -> None:
    from .events import MembershipDeactivated

    membership = Membership.objects.get(pk=membership.pk)
    if membership.status == Membership.Status.REMOVED:
        return
    with audit.track(membership, action="account_deleted"):
        membership.status = Membership.Status.REMOVED
        membership.title = ""
        membership.save(update_fields=["status", "title", "updated_at"])
    publish(
        MembershipDeactivated(
            subject_id=membership.pk, user_id=str(membership.user_id), status=membership.status
        )
    )


@transaction.atomic
def _anonymise_login(user: User) -> None:
    from .events import UserAccountDeleted

    UserSession.objects.filter(user=user).delete()
    for model in (MFADevice, RecoveryCode, WebAuthnCredential, SocialAccount, LoginToken):
        model.objects.filter(user=user).delete()
    LoginEvent.objects.filter(user=user).delete()
    LoginEvent.objects.filter(email=user.email).delete()
    user.email = f"deleted-{user.pk.hex}@deleted.invalid"
    user.first_name = ""
    user.last_name = ""
    user.preferred_name = ""
    user.pronouns = ""
    user.phone = ""
    user.phone_verified_at = None
    user.email_verified_at = None
    user.is_active = False
    user.set_unusable_password()
    user.save()
    token = set_organisation(None)  # a platform event, whatever host the request came to
    try:
        publish(UserAccountDeleted(subject_id=user.pk))
    finally:
        reset_organisation(token)


def delete_account(
    user: User, *, password: str = "", confirm_email: str = "", reason: str = ""
) -> AccountDeletion:
    """Delete ``user``'s whole account. Raises ``AccountDeletionBlocked`` (nothing changed)
    while a safeguard applies. Each organisation is handled in its own transaction, so a
    failure part-way can simply be retried: finished organisations are skipped."""
    _check_confirmation(user, password=password, confirm_email=confirm_email)
    found = blockers(user)
    if found:
        raise AccountDeletionBlocked(
            _("Transfer ownership or close these organisations first: %(names)s")
            % {"names": ", ".join(b.organisation_name for b in found)},
            extra={"blockers": [b.__dict__ for b in found]},
        )
    record = AccountDeletion.objects.create(
        user=user, email_hash=email_hash(user.email), reason=reason[:500]
    )
    done = []
    for membership in memberships(user):
        done.append(_in_organisation(user, membership, reason))
        AccountDeletion.objects.filter(pk=record.pk).update(organisations=done)
    _anonymise_login(user)
    record.organisations = done
    record.completed_at = now()
    record.save(update_fields=["organisations", "completed_at"])
    return record
