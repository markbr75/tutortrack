"""Reads for help, tours, the setup checklist, surveys and support chat (E30 Part 2)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import QuerySet

from tutortrack.core.permissions import permission_scope
from tutortrack.core.time import now

from . import help as help_content
from .models import (
    GuidanceState,
    SetupChecklist,
    SetupChecklistItem,
    SupportConversation,
    SurveyResponse,
)

SUPPORT = "success.support.chat"
NPS_FIRST_AFTER = timedelta(days=14)  # members are asked once they know the product
NPS_INTERVAL = timedelta(days=90)
STAFF_ROLES = {"owner", "admin", "branch_manager", "coordinator", "finance"}
STEP_LINKS: dict[str, str] = {
    SetupChecklistItem.Key.SERVICE: "/catalogue",
    SetupChecklistItem.Key.STUDENT: "/students",
    SetupChecklistItem.Key.LESSON: "/calendar",
    SetupChecklistItem.Key.PAYMENTS: "/settings/payments",
    SetupChecklistItem.Key.INVOICE: "/billing",
}


def support_conversations(user: Any) -> QuerySet[SupportConversation]:
    """The organisation's conversations for holders of the 'all' scope, otherwise the
    member's own (``branch`` scope counts as own: conversations aren't branch data)."""
    qs = SupportConversation.objects.select_related("opened_by", "assignee")
    scope = permission_scope(user, SUPPORT)
    if scope is None:
        return qs.none()
    if scope == "all":
        return qs
    return qs.filter(SupportConversation.own_scope_q(user))


def _state(user: Any) -> GuidanceState | None:
    return GuidanceState.objects.filter(user=user).first()


def nps_due(user: Any, membership: Any) -> bool:
    from tutortrack.tenancy.settings_service import get_setting

    if membership is None or membership.role not in STAFF_ROLES:
        return False
    if not get_setting("privacy.satisfaction_surveys"):
        return False
    joined = membership.joined_at or membership.created_at
    if joined and joined > now() - NPS_FIRST_AFTER:
        return False
    state = _state(user)
    if state and state.nps_snoozed_until and state.nps_snoozed_until > now():
        return False
    return not SurveyResponse.objects.filter(
        user=user, kind=SurveyResponse.Kind.NPS, created_at__gte=now() - NPS_INTERVAL
    ).exists()


def changelog_unread(user: Any, membership: Any) -> int:
    state = _state(user)
    seen = state.changelog_seen_at if state else None
    if seen is None and membership is not None:
        seen = membership.joined_at or membership.created_at
    if seen is None:
        return len(help_content.changelog())
    return sum(1 for e in help_content.changelog() if e.published_on > seen.date())


def guidance(user: Any, membership: Any, *, impersonating: bool) -> dict[str, Any]:
    state = _state(user)
    unread = 0
    if permission_scope(user, SUPPORT) is not None:
        unread = support_conversations(user).filter(customer_unread=True).count()
    return {
        "completed_tours": list(state.completed_tours) if state else [],
        "dismissed_tours": list(state.dismissed_tours) if state else [],
        "changelog_unread": changelog_unread(user, membership),
        "nps_due": not impersonating and nps_due(user, membership),
        "support_unread": unread,
        "analytics_allowed": analytics_allowed(membership, impersonating=impersonating),
    }


def analytics_allowed(membership: Any, *, impersonating: bool) -> bool:
    """Staff only (never families or students), never while support views as someone, and
    only if the organisation allows it. The person's own consent is checked separately."""
    from tutortrack.tenancy.settings_service import get_setting

    if impersonating or membership is None or membership.role not in STAFF_ROLES:
        return False
    return bool(get_setting("privacy.product_analytics"))


def checklist(state: SetupChecklist) -> dict[str, Any]:
    done = {i.key: i for i in SetupChecklistItem.objects.all()}
    steps = [
        {
            "key": key,
            "title": str(label),
            "link": STEP_LINKS[key],
            "done": key in done,
            "completed_at": done[key].completed_at if key in done else None,
        }
        for key, label in SetupChecklistItem.Key.choices
    ]
    return {
        "steps": steps,
        "done": sum(1 for s in steps if s["done"]),
        "total": len(steps),
        "completed_at": state.completed_at,
        "dismissed_at": state.dismissed_at,
    }
