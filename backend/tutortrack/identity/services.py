"""Membership writes. E03 adds invitations, roles and deactivation flows on top."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from django.db import transaction

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now

from .models import Invitation, Membership, MembershipBranch, User


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
    from .tasks import current_org
    from .tasks import send_verification_email as task

    org = current_org()
    transaction.on_commit(lambda: task.delay(user_id=str(user.pk), organisation_id=org))


def verify_email(token: str) -> User:
    from .tokens import user_from_email_token

    user = user_from_email_token(token)
    if user.email_verified_at is None:
        user.email_verified_at = now()
        user.save(update_fields=["email_verified_at"])
    return user


# --- invitations and memberships (FR-03-4) --------------------------------------------------------

INVITATION_TTL_DAYS = 7


def _token_hash(raw: str) -> str:
    import hashlib

    return hashlib.sha256(raw.encode()).hexdigest()


def _send_invitation(invitation: Invitation, raw_token: str) -> None:
    from tutortrack.tenancy.models import Organisation

    from .tasks import send_invitation

    org = Organisation.objects.get(pk=invitation.organisation_id)
    inviter = invitation.invited_by.get_full_name() if invitation.invited_by else org.name
    url = f"{org.base_url}/accept-invite?token={raw_token}"
    transaction.on_commit(
        lambda: send_invitation.delay(
            email=invitation.email,
            organisation_name=org.name,
            inviter=inviter,
            url=url,
            locale=org.locale,
            organisation_id=str(org.pk),
        )
    )


def _new_token() -> tuple[str, str]:
    import secrets

    raw = secrets.token_urlsafe(32)
    return raw, _token_hash(raw)


def _actor() -> User | None:
    from tutortrack.core.context import get_request_context

    user_id = get_request_context().user_id
    return User.objects.filter(pk=user_id).first() if user_id else None


def _check_tutor_capacity() -> None:
    """Inviting a tutor directly counts against the plan's ``max_tutors`` (E04): tutor
    profiles plus tutor invitations still pending."""
    from django.apps import apps

    from tutortrack.core import entitlements

    tutor_profile = apps.get_model("people", "TutorProfile")
    used = (
        tutor_profile.objects.filter(status__in=("onboarding", "active", "restricted")).count()
        + Invitation.objects.filter(
            role=Membership.Role.TUTOR, status=Invitation.Status.PENDING, target_type=""
        ).count()
    )
    entitlements.require_capacity("max_tutors", used=used)


@transaction.atomic
def invite(
    email: str,
    *,
    role: str,
    branch_scope: str = Membership.BranchScope.ALL,
    branches: Iterable[Any] = (),
    title: str = "",
    target_type: str = "",
    target_id: str = "",
    deliver: Callable[[Invitation, str], None] | None = None,
) -> Invitation:
    """Invite someone to the organisation in context; emails a 7-day link. ``deliver``
    replaces the platform email (``deliver(invitation, raw_token)``), e.g. a comms
    template for a guardian invited from the portal."""
    from datetime import timedelta

    from tutortrack.core.events import publish
    from tutortrack.core.permissions import has_perm

    from .events import UserInvited

    email = email.strip().lower()
    if role not in Membership.Role.values:
        raise BusinessRuleViolation(f"Unknown role {role!r}.")
    actor = _actor()
    if role == Membership.Role.OWNER and not (
        actor is not None and has_perm(actor, "membership.transfer_ownership")
    ):
        raise BusinessRuleViolation("Only an owner can invite another owner.")
    if Membership.objects.filter(user__email=email, status=Membership.Status.ACTIVE).exists():
        raise BusinessRuleViolation(
            "This person is already a member.", extra={"errors": {"email": ["Already a member."]}}
        )
    if Invitation.objects.filter(email=email, status=Invitation.Status.PENDING).exists():
        raise BusinessRuleViolation(
            "There is already a pending invitation for this email. Resend it instead.",
            extra={"errors": {"email": ["Invitation already pending."]}},
        )
    if role == Membership.Role.TUTOR and target_type != "people.tutor":
        _check_tutor_capacity()
    branch_ids = sorted({str(getattr(b, "pk", b)) for b in branches})
    if branch_scope == Membership.BranchScope.SELECTED and not branch_ids:
        raise BusinessRuleViolation("Select at least one branch.")
    raw, hashed = _new_token()
    invitation = Invitation.objects.create(
        email=email,
        role=role,
        branch_scope=branch_scope,
        branch_ids=branch_ids,
        title=title,
        token_hash=hashed,
        expires_at=now() + timedelta(days=INVITATION_TTL_DAYS),
        invited_by=actor,
        sent_count=1,
        last_sent_at=now(),
        target_type=target_type,
        target_id=target_id,
    )
    audit.record_create(invitation)
    publish(UserInvited(subject_id=invitation.pk, email=email, role=role))
    (deliver or _send_invitation)(invitation, raw)
    return invitation


@transaction.atomic
def resend_invitation(invitation: Invitation) -> Invitation:
    from datetime import timedelta

    if invitation.status != Invitation.Status.PENDING:
        raise BusinessRuleViolation("Only pending invitations can be resent.")
    raw, hashed = _new_token()
    with audit.track(invitation, action="resend"):
        invitation.token_hash = hashed
        invitation.expires_at = now() + timedelta(days=INVITATION_TTL_DAYS)
        invitation.sent_count += 1
        invitation.last_sent_at = now()
        invitation.save()
    _send_invitation(invitation, raw)
    return invitation


@transaction.atomic
def revoke_invitation(invitation: Invitation) -> Invitation:
    if invitation.status == Invitation.Status.PENDING:
        with audit.track(invitation, action="revoke"):
            invitation.status = Invitation.Status.REVOKED
            invitation.save(update_fields=["status", "updated_at"])
    return invitation


def invitation_for_token(token: str) -> Invitation:
    """The pending, unexpired invitation for ``token`` in the organisation in context."""
    from .tokens import InvalidToken

    invitation = Invitation.objects.filter(token_hash=_token_hash(token)).first()
    if (
        invitation is None
        or invitation.status != Invitation.Status.PENDING
        or invitation.expires_at <= now()
    ):
        raise InvalidToken
    return invitation


@transaction.atomic
def accept_invitation(token: str, user: User) -> Membership:
    """Join with an existing account (the signed-in user must own the invited email)."""
    from tutortrack.core.events import publish

    from .events import UserJoined
    from .tokens import InvalidToken

    invitation = invitation_for_token(token)
    if user.email != invitation.email:
        raise InvalidToken
    membership = Membership.objects.filter(user=user).first()
    if membership is None:
        membership = add_member(
            user,
            role=invitation.role,
            branch_scope=invitation.branch_scope,
            branches=invitation.branch_ids,
            title=invitation.title,
        )
    else:  # a former member coming back
        with audit.track(membership, action="rejoin"):
            membership.status = Membership.Status.ACTIVE
            membership.role = invitation.role
            membership.title = invitation.title or membership.title
            membership.joined_at = now()
            membership.save()
        set_branch_scope(membership, invitation.branch_scope, invitation.branch_ids)
    with audit.track(invitation, action="accept"):
        invitation.status = Invitation.Status.ACCEPTED
        invitation.accepted_at = now()
        invitation.accepted_by = user
        invitation.save()
    if user.email_verified_at is None:  # they followed a link sent to that address
        user.email_verified_at = now()
        user.save(update_fields=["email_verified_at"])
    publish(UserJoined(subject_id=membership.pk, user_id=str(user.pk), role=membership.role))
    return membership


@transaction.atomic
def accept_invitation_with_new_account(
    token: str, *, password: str, first_name: str, last_name: str = ""
) -> tuple[User, Membership]:
    from .tokens import InvalidToken

    invitation = invitation_for_token(token)
    if User.objects.filter(email=invitation.email).exists():
        raise InvalidToken  # must sign in and accept with the existing account
    user = create_user(
        email=invitation.email, password=password, first_name=first_name, last_name=last_name
    )
    return user, accept_invitation(token, user)


def _active_owner_count() -> int:
    return Membership.objects.filter(
        role=Membership.Role.OWNER, status=Membership.Status.ACTIVE
    ).count()


@transaction.atomic
def update_membership(
    membership: Membership,
    *,
    role: str | None = None,
    branch_scope: str | None = None,
    branches: Iterable[Any] | None = None,
    title: str | None = None,
    status: str | None = None,
) -> Membership:
    from tutortrack.core.events import publish
    from tutortrack.core.permissions import has_perm

    from .events import MembershipDeactivated, MembershipRoleChanged

    actor = _actor()
    is_last_owner = (
        membership.role == Membership.Role.OWNER
        and membership.status == Membership.Status.ACTIVE
        and _active_owner_count() <= 1
    )
    old_role, old_status = membership.role, membership.status
    if role is not None and role != old_role:
        if role not in Membership.Role.values:
            raise BusinessRuleViolation(f"Unknown role {role!r}.")
        if actor is not None and actor.pk == membership.user_id:
            raise BusinessRuleViolation("You can't change your own role.")
        if Membership.Role.OWNER in (role, old_role) and not (
            actor is not None and has_perm(actor, "membership.transfer_ownership")
        ):
            raise BusinessRuleViolation("Only an owner can grant or remove the owner role.")
        if is_last_owner:
            raise BusinessRuleViolation("An organisation needs at least one owner.")
    if status is not None and status != old_status:
        if status not in {
            Membership.Status.ACTIVE,
            Membership.Status.SUSPENDED,
            Membership.Status.REMOVED,
        }:
            raise BusinessRuleViolation(f"Unknown status {status!r}.")
        if is_last_owner:
            raise BusinessRuleViolation("An organisation needs at least one owner.")
        if actor is not None and actor.pk == membership.user_id:
            raise BusinessRuleViolation("You can't suspend or remove yourself.")
    with audit.track(membership):
        if role is not None:
            membership.role = role
        if title is not None:
            membership.title = title
        if status is not None:
            membership.status = status
        membership.save()
    if branch_scope is not None:
        set_branch_scope(membership, branch_scope, branches or ())
    if membership.role != old_role:
        publish(
            MembershipRoleChanged(
                subject_id=membership.pk,
                user_id=str(membership.user_id),
                old_role=old_role,
                new_role=membership.role,
            )
        )
    if membership.status != old_status and membership.status != Membership.Status.ACTIVE:
        publish(
            MembershipDeactivated(
                subject_id=membership.pk, user_id=str(membership.user_id), status=membership.status
            )
        )
    return membership


def remove_member(membership: Membership) -> Membership:
    """Removing a member ends their access to this organisation (FR-03-4)."""
    return update_membership(membership, status=Membership.Status.REMOVED)


PROFILE_FIELDS = frozenset(
    {"first_name", "last_name", "preferred_name", "pronouns", "phone", "timezone", "locale"}
)


@transaction.atomic
def update_profile(user: User, **changes: Any) -> User:
    unknown = set(changes) - PROFILE_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Cannot change: {', '.join(sorted(unknown))}")
    if "phone" in changes and changes["phone"] != user.phone:
        changes["phone_verified_at"] = None
    for field, value in changes.items():
        setattr(user, field, value)
    user.save(update_fields=[*changes])
    return user


# --- custom roles (E03-T11) ----------------------------------------------------------------------


def builtin_matrix(key: str) -> dict[str, str]:
    """``{codename: scope}`` a built-in role grants (patterns expanded, denies applied)."""
    from tutortrack.core.permission_registry import all_permissions, matches

    from .roles import ROLES, SCOPE_RANK

    role = ROLES[key]
    out: dict[str, str] = {}
    for codename in all_permissions():
        if any(matches(d, codename) for d in role.denies):
            continue
        for grant in role.grants:
            if matches(grant.pattern, codename) and (
                codename not in out or SCOPE_RANK[grant.scope] > SCOPE_RANK[out[codename]]
            ):
                out[codename] = grant.scope
    return out


def role_matrix(role: Any) -> dict[str, str]:
    from .roles import Grant

    return {g.pattern: g.scope for g in (Grant.parse(raw) for raw in role.grants or [])}


def _clean_matrix(matrix: dict[str, Any]) -> list[str]:
    from tutortrack.core.permission_registry import all_permissions

    from .roles import OWNER_ONLY, SCOPES

    known = all_permissions()
    grants = []
    for codename, scope in sorted(matrix.items()):
        if scope in (None, "", "none"):
            continue
        if codename not in known:
            raise BusinessRuleViolation(
                f"Unknown permission {codename!r}.", extra={"errors": {"grants": [codename]}}
            )
        if scope not in SCOPES:
            raise BusinessRuleViolation(
                f"Unknown scope {scope!r}.", extra={"errors": {"grants": [codename]}}
            )
        if codename in OWNER_ONLY:
            raise BusinessRuleViolation(
                f"{codename} is only for owners.", extra={"errors": {"grants": [codename]}}
            )
        grants.append(f"{codename}:{scope}")
    return grants


@transaction.atomic
def create_custom_role(
    *,
    name: str,
    description: str = "",
    clone_from: str = "",
    grants: dict[str, Any] | None = None,
) -> Any:
    """A new custom role, cloned from a built-in staff role (key) or another custom role
    (id), then optionally edited with ``grants`` (``{codename: scope or None}``)."""
    from tutortrack.core.events import publish

    from .events import CustomRoleChanged
    from .models import Role

    base, matrix = "coordinator", {}
    if clone_from in Role.STAFF_BASES:
        base, matrix = clone_from, builtin_matrix(clone_from)
    elif clone_from:
        source = Role.objects.filter(pk=clone_from).first()
        if source is None:
            raise BusinessRuleViolation(
                "Clone a staff role.", extra={"errors": {"clone_from": ["Unknown role."]}}
            )
        base, matrix = source.base_role, role_matrix(source)
    matrix.update(grants or {})
    name = name.strip()
    if Role.objects.filter(name__iexact=name).exists():
        raise BusinessRuleViolation(
            "There is already a role with that name.", extra={"errors": {"name": ["Taken."]}}
        )
    role = Role.objects.create(
        name=name[:100],
        description=description[:300],
        base_role=base,
        grants=_clean_matrix(matrix),
    )
    audit.record_create(role)
    publish(CustomRoleChanged(subject_id=role.pk, action="created"))
    return role


@transaction.atomic
def update_custom_role(
    role: Any,
    *,
    name: str | None = None,
    description: str | None = None,
    grants: dict[str, Any] | None = None,
) -> Any:
    """Rename or edit the matrix; ``grants`` changes only the codenames it lists."""
    from tutortrack.core.events import publish

    from .events import CustomRoleChanged
    from .models import Role

    if role.archived_at is not None:
        raise BusinessRuleViolation("This role is archived.")
    with audit.track(role):
        if name is not None:
            name = name.strip()
            if Role.objects.filter(name__iexact=name).exclude(pk=role.pk).exists():
                raise BusinessRuleViolation(
                    "There is already a role with that name.",
                    extra={"errors": {"name": ["Taken."]}},
                )
            role.name = name[:100]
        if description is not None:
            role.description = description[:300]
        if grants is not None:
            matrix = role_matrix(role)
            matrix.update(grants)
            role.grants = _clean_matrix(matrix)
        role.save()
    publish(CustomRoleChanged(subject_id=role.pk, action="updated"))
    return role


@transaction.atomic
def archive_custom_role(role: Any) -> Any:
    """Archive a role; members who had it go back to their built-in role."""
    from tutortrack.core.events import publish

    from .events import CustomRoleChanged

    with audit.track(role, action="archive"):
        role.archived_at = now()
        role.save()
    role.membership_links.all().delete()
    publish(CustomRoleChanged(subject_id=role.pk, action="archived"))
    return role


@transaction.atomic
def set_custom_roles(membership: Membership, roles: Iterable[Any]) -> Membership:
    """Give a staff member custom roles (union of permissions); an empty list goes back to
    the built-in role. Owners keep everything; portal users can't have staff roles."""
    from tutortrack.core.events import publish

    from .events import MembershipRoleChanged
    from .models import MembershipRole
    from .roles import ROLES

    roles = list(roles)
    actor = _actor()
    if actor is not None and actor.pk == membership.user_id:
        raise BusinessRuleViolation("You can't change your own role.")
    if roles and membership.role == Membership.Role.OWNER:
        raise BusinessRuleViolation("Owners always have every permission.")
    if roles and not ROLES[membership.role].is_staff:
        raise BusinessRuleViolation("Custom roles are for staff and tutors.")
    if any(r.archived_at is not None for r in roles):
        raise BusinessRuleViolation("This role is archived.")
    before = sorted(str(i) for i in membership.custom_role_links.values_list("role_id", flat=True))
    membership.custom_role_links.exclude(role__in=roles).delete()
    for role in roles:
        MembershipRole.objects.get_or_create(membership=membership, role=role)
    after = sorted(str(r.pk) for r in roles)
    if before != after:
        audit.record(membership, "update", {"custom_roles": [before, after]})
        publish(
            MembershipRoleChanged(
                subject_id=membership.pk,
                user_id=str(membership.user_id),
                old_role=membership.role,
                new_role=membership.role,
                custom_roles=after,
            )
        )
    return membership
