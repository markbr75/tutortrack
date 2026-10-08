from __future__ import annotations

import uuid
from typing import Any

from tutortrack.core.context import request_context

from .models import Membership


def memberships_for_user(user: Any) -> list[Membership]:
    """``user``'s active memberships in every organisation (org switcher, tenant resolution).

    Not filtered by tenant: the RLS policy on identity_membership lets the app role see rows
    whose ``user_id`` equals ``app.current_user`` in any organisation, and nothing else of
    other tenants. Only call this for the authenticated user (it evaluates as that user).
    """
    with request_context(user_id=user.pk):
        return list(
            Membership.all_tenants.filter(user_id=user.pk, status=Membership.Status.ACTIVE)
            .select_related("organisation")
            .order_by("-last_active_at", "organisation__name")
        )


def membership_for(user: Any, organisation_id: uuid.UUID) -> Membership | None:
    if not getattr(user, "is_authenticated", False):
        return None
    with request_context(user_id=user.pk):
        return (
            Membership.all_tenants.filter(
                user_id=user.pk,
                organisation_id=organisation_id,
                status=Membership.Status.ACTIVE,
            )
            .select_related("organisation")
            .first()
        )


def branch_ids_for(membership: Membership) -> frozenset[uuid.UUID] | None:
    """Branches the member may see; ``None`` means all branches."""
    if membership.branch_scope == Membership.BranchScope.ALL:
        return None
    from .models import MembershipBranch

    with request_context(user_id=membership.user_id):
        return frozenset(
            MembershipBranch.all_tenants.filter(
                membership_id=membership.pk, organisation_id=membership.organisation_id
            ).values_list("branch_id", flat=True)
        )
