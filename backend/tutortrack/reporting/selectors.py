"""Reads for reporting: dashboards, widget context, saved/scheduled reports and runs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from django.db.models import Q, QuerySet

from tutortrack.core.context import branch_scope, require_organisation_id
from tutortrack.core.permissions import permission_scope
from tutortrack.tenancy.settings_service import get_setting

from . import periods, reports, widgets
from .models import DashboardLayout, ReportRun, SavedReport, ScheduledReport
from .reports.base import id_list, invalid


def membership_of(user: Any) -> Any:
    from tutortrack.identity.selectors import membership_for

    return membership_for(user, require_organisation_id())


@contextmanager
def acting_as(user: Any) -> Iterator[None]:
    """Run reads with ``user``'s branch restriction (outside a request: scheduled runs)."""
    from tutortrack.identity.selectors import branch_ids_for

    membership = membership_of(user)
    ids = branch_ids_for(membership) if membership is not None else None
    with branch_scope(ids):
        yield


# --- dashboards ---------------------------------------------------------------------------------


def default_preset(user: Any) -> str:
    from tutortrack.people.models import TutorProfile

    membership = membership_of(user)
    role = membership.role if membership is not None else ("owner" if user.is_superuser else "")
    setting = str(get_setting("reporting.dashboard_preset"))
    active = TutorProfile.objects.filter(status="active").count() if setting == "auto" else 0
    return widgets.preset_for(role, setting, active)


def dashboard(user: Any) -> dict[str, Any]:
    """The user's layout (own if customised, else their role's preset), keeping only the
    widgets they may still see."""
    allowed = {w.key for w in widgets.available(user)}
    layout = DashboardLayout.objects.filter(user=user).first()
    if layout is not None:
        items = [
            {"widget": w["widget"], "size": w.get("size") or "s"}
            for w in layout.widgets
            if isinstance(w, dict) and w.get("widget") in allowed
        ]
        return {"preset": "custom", "customised": True, "widgets": items}
    preset = default_preset(user)
    return {"preset": preset, "customised": False, "widgets": widgets.preset_layout(preset, user)}


def widget_context(user: Any, data: Mapping[str, Any]) -> widgets.Context:
    preset = str(data.get("period") or "this_month")
    from datetime import date

    try:
        start = date.fromisoformat(str(data["from"])) if data.get("from") else None
        end = date.fromisoformat(str(data["to"])) if data.get("to") else None
        period = periods.resolve(preset, start=start, end=end)
    except (ValueError, KeyError) as exc:
        raise invalid("period", "Choose a valid period.") from exc
    compare = str(data.get("compare") or "previous_period")
    if compare not in periods.COMPARISONS:
        raise invalid("compare", "Unknown comparison.")
    return widgets.Context(
        user=user,
        period=period,
        previous=periods.comparison(period, compare),
        branch=id_list(data, "branch"),
        today=periods.org_today(),
        preset=preset,
    )


# --- saved and scheduled reports ----------------------------------------------------------------


def saved_reports(user: Any) -> QuerySet[SavedReport]:
    """The user's own views and shared ones, for reports they may run."""
    keys = [r.key for r in reports.available(user)]
    return SavedReport.objects.filter(Q(owner=user) | Q(shared=True), report_key__in=keys)


def _manages_all(user: Any) -> bool:
    return permission_scope(user, "reporting.schedule.manage") == "all"


def scheduled_reports(user: Any) -> QuerySet[ScheduledReport]:
    if permission_scope(user, "reporting.schedule.manage") is None:
        return ScheduledReport.objects.none()
    qs = ScheduledReport.objects.select_related("saved_report").prefetch_related("recipients")
    return qs if _manages_all(user) else qs.filter(saved_report__owner=user)


def report_runs(user: Any) -> QuerySet[ReportRun]:
    qs = ReportRun.objects.select_related("scheduled_report__saved_report", "file")
    if _manages_all(user):
        return qs
    return qs.filter(Q(requested_by=user) | Q(scheduled_report__saved_report__owner=user))
