"""Reads for the AI assistant: feature switches and style, usage, logs, proposals,
assists (the AI-assisted flag) and inbox insights."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import Count, QuerySet, Sum

from tutortrack.core import entitlements
from tutortrack.core.exceptions import FeatureDisabled
from tutortrack.core.permissions import has_perm, scope_queryset

from .models import (
    AIAssist,
    AIFeatureSetting,
    AIProposal,
    AIRequestLog,
    AIUsage,
    Feature,
    ThreadInsight,
)

ENTITLEMENT = "ai_assistant"


def _rows() -> dict[str, AIFeatureSetting]:
    return {row.feature: row for row in AIFeatureSetting.objects.all()}


def is_enabled(feature: str) -> bool:
    if not entitlements.has(ENTITLEMENT):
        return False
    row = AIFeatureSetting.objects.filter(feature=feature).first()
    return bool(row and row.enabled)


def require_enabled(feature: str) -> None:
    """The plan must include the AI assistant (``UpgradeRequired``) and the organisation
    must have opted into this feature (``FeatureDisabled``)."""
    entitlements.require(ENTITLEMENT)
    if not is_enabled(feature):
        raise FeatureDisabled(f"ai.{feature}")


def style_for(feature: str) -> dict[str, str]:
    from tutortrack.tenancy.settings_service import get_setting

    row = AIFeatureSetting.objects.filter(feature=feature).first()
    tone = (row.tone if row else "") or str(get_setting("ai.tone") or "friendly")
    language = (row.language if row else "") or str(get_setting("ai.spelling") or "en-GB")
    return {"tone": tone, "language": language}


def feature_settings() -> list[dict[str, Any]]:
    rows = _rows()
    out = []
    for feature in Feature:
        row = rows.get(feature.value)
        out.append(
            {
                "feature": feature.value,
                "title": str(feature.label),
                "enabled": bool(row and row.enabled),
                "tone": row.tone if row else "",
                "language": row.language if row else "",
            }
        )
    return out


def status(user: Any) -> dict[str, Any]:
    """What the UI needs to show or hide AI controls."""
    from . import metering
    from .providers import provider_name

    available = entitlements.has(ENTITLEMENT)
    rows = _rows()
    summary = metering.credit_summary() if available else None
    exhausted = False
    if summary is not None:
        cap = summary["monthly_cap"]
        exhausted = bool(cap and summary["used_this_month"] >= cap) or (
            summary["metered"] and (summary["balance"] or 0) <= 0
        )
    return {
        "available": available,
        "provider": provider_name(),
        "features": {
            f.value: bool(available and rows.get(f.value) and rows[f.value].enabled)
            for f in Feature
        },
        "credits_exhausted": exhausted,
        "credits": summary if has_perm(user, "ai.usage.view") else None,
    }


def request_logs(user: Any) -> QuerySet[AIRequestLog]:
    return scope_queryset(user, AIRequestLog.objects.select_related("user"), "ai.usage.view")


def usage(period: date) -> dict[str, Any]:
    rows = AIUsage.objects.filter(period=period)
    by_feature = list(
        rows.values("feature")
        .annotate(requests=Sum("requests"), credits=Sum("credits"))
        .order_by("feature")
    )
    by_user = list(
        rows.values("user_id", "user__first_name", "user__last_name", "user__email")
        .annotate(requests=Sum("requests"), credits=Sum("credits"))
        .order_by("-credits")[:50]
    )
    totals = rows.aggregate(
        requests=Sum("requests"),
        credits=Sum("credits"),
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
        cache_read_tokens=Sum("cache_read_tokens"),
        cache_write_tokens=Sum("cache_write_tokens"),
    )
    ratings = (
        AIRequestLog.objects.filter(created_at__date__gte=period, feedback__isnull=False)
        .values("feedback__rating")
        .annotate(n=Count("id"))
    )
    return {
        "period": period,
        "totals": {k: int(v or 0) for k, v in totals.items()},
        "by_feature": [
            {
                "feature": r["feature"],
                "requests": int(r["requests"] or 0),
                "credits": int(r["credits"] or 0),
            }
            for r in by_feature
        ],
        "by_user": [
            {
                "user": str(r["user_id"]) if r["user_id"] else None,
                "name": " ".join(
                    p for p in (r["user__first_name"], r["user__last_name"]) if p
                ).strip()
                or (r["user__email"] or ""),
                "requests": int(r["requests"] or 0),
                "credits": int(r["credits"] or 0),
            }
            for r in by_user
        ],
        "feedback": {r["feedback__rating"] or "none": r["n"] for r in ratings},
    }


def proposals(user: Any) -> QuerySet[AIProposal]:
    """People only ever see (and confirm) their own proposals."""
    return AIProposal.objects.filter(user_id=getattr(user, "pk", None))


def assists(subject_type: str = "", subject_ids: list[str] | None = None) -> QuerySet[AIAssist]:
    qs = AIAssist.objects.select_related("user")
    if subject_type:
        qs = qs.filter(subject_type=subject_type)
    if subject_ids:
        qs = qs.filter(subject_id__in=subject_ids)
    return qs


def thread_insights(user: Any, thread_ids: list[str] | None = None) -> QuerySet[ThreadInsight]:
    from tutortrack.comms.selectors import threads

    qs = ThreadInsight.objects.filter(thread__in=threads(user))
    if thread_ids:
        qs = qs.filter(thread_id__in=thread_ids)
    return qs
