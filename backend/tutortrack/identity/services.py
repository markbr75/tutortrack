"""Membership writes. E03 adds invitations, roles and deactivation flows on top."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db import transaction

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now

from .models import Membership, MembershipBranch, User


@transaction.atomic
def add_member(
    user: User,
    *,
    role: str,
    branch_scope: str = Membership.BranchScope.ALL,
    branches: Iterable[Any] = (),
    title: str = "",
) -> Membership:
    """Add ``user`` to the organisation in context (active immediately)."""
    require_organisation_id()
    membership = Membership.objects.create(
        user=user,
        role=role,
        branch_scope=branch_scope,
        title=title,
        joined_at=now(),
        last_active_at=now(),
    )
    set_branch_scope(membership, branch_scope, branches)
    audit.record_create(membership)
    return membership


@transaction.atomic
def set_branch_scope(membership: Membership, scope: str, branches: Iterable[Any] = ()) -> None:
    branch_ids = {getattr(b, "pk", b) for b in branches}
    if scope == Membership.BranchScope.SELECTED and not branch_ids:
        raise BusinessRuleViolation("Select at least one branch.")
    with audit.track(membership):
        membership.branch_scope = scope
        membership.save(update_fields=["branch_scope", "updated_at"])
    MembershipBranch.objects.filter(membership=membership).delete()
    if scope == Membership.BranchScope.SELECTED:
        MembershipBranch.objects.bulk_create(
            [
                MembershipBranch(
                    membership=membership, branch_id=b, organisation_id=membership.organisation_id
                )
                for b in sorted(branch_ids, key=str)
            ]
        )


def touch_last_active(membership: Membership, *, min_interval_seconds: int = 300) -> None:
    """Remember when the member last used this organisation (org switcher ordering)."""
    current = now()
    last = membership.last_active_at
    if last is not None and (current - last).total_seconds() < min_interval_seconds:
        return
    Membership.objects.filter(pk=membership.pk).update(last_active_at=current)
    membership.last_active_at = current


# --- users and email verification (E02-T06; E03 adds login, reset, MFA) ---------------------------


def create_user(
    *, email: str, password: str, first_name: str = "", last_name: str = "", **extra: Any
) -> User:
    """Create a login. Raises ``django.core.exceptions.ValidationError`` for weak passwords."""
    from django.contrib.auth.password_validation import validate_password

    candidate = User(email=email.strip().lower(), first_name=first_name, last_name=last_name)
    validate_password(password, user=candidate)
    return User.objects.create_user(
        candidate.email, password, first_name=first_name, last_name=last_name, **extra
    )


def send_verification_email(user: User) -> None:
    """Queue the verification email after the current transaction commits."""
    from .tasks import send_verification_email as task

    transaction.on_commit(lambda: task.delay(user_id=str(user.pk)))


def verify_email(token: str) -> User:
    from .tokens import user_from_email_token

    user = user_from_email_token(token)
    if user.email_verified_at is None:
        user.email_verified_at = now()
        user.save(update_fields=["email_verified_at"])
    return user
