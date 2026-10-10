"""Writes for reporting (E26): dashboards, saved and scheduled reports, exports, scheduled
runs, fact rebuilds and FX refreshes. Every mutation is audited; events go through the
outbox."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import time
from typing import Any

from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.permissions import has_perm, permission_scope
from tutortrack.core.security_alerts import check_mass_export
from tutortrack.core.time import now

from . import exports, facts, fx, reports, widgets
from .events import (
    ReportExported,
    ReportRunDelivered,
    ReportRunFailed,
    SavedReportCreated,
    SavedReportDeleted,
    ScheduledReportDeleted,
    ScheduledReportSaved,
)
from .models import DashboardLayout, ReportRun, SavedReport, ScheduledReport
from .reports.base import invalid, parse_params

FORMATS = ("csv", "xlsx", "pdf")
MAX_WIDGETS = 30
SCHEDULE_PROCESS = "scheduled-report"


# --- dashboards (T03) ---------------------------------------------------------------------------


@transaction.atomic
def save_layout(user: Any, items: Iterable[dict[str, Any]]) -> DashboardLayout:
    allowed = {w.key for w in widgets.available(user)}
    cleaned: list[dict[str, str]] = []
    for item in items:
        key = str(item.get("widget") or "")
        size = str(item.get("size") or "s")
        if key not in allowed:
            raise invalid("widgets", _("Unknown widget: %(key)s") % {"key": key})
        if size not in widgets.SIZES:
            raise invalid("widgets", _("Choose small, medium or large."))
        if any(c["widget"] == key for c in cleaned):
            raise invalid("widgets", _("Each widget can appear once."))
        cleaned.append({"widget": key, "size": size})
    if len(cleaned) > MAX_WIDGETS:
        raise invalid("widgets", _("A dashboard has at most %(n)s widgets.") % {"n": MAX_WIDGETS})
    layout = DashboardLayout.objects.filter(user=user).first()
    if layout is None:
        layout = DashboardLayout.objects.create(user=user, widgets=cleaned)
        audit.record_create(layout)
        return layout
    with audit.track(layout):
        layout.widgets = cleaned
        layout.save(update_fields=["widgets", "updated_at"])
    return layout


@transaction.atomic
def reset_layout(user: Any) -> None:
    for layout in DashboardLayout.objects.filter(user=user):
        audit.record(layout, "delete")
        layout.delete()


# --- saved reports (T07) ------------------------------------------------------------------------


def _clean_params(user: Any, report_key: str, params: dict[str, Any]) -> dict[str, Any]:
    report = reports.find(report_key, user)
    return parse_params(report, params).as_query()


@transaction.atomic
def create_saved_report(
    user: Any, *, name: str, report_key: str, params: dict[str, Any], shared: bool = False
) -> SavedReport:
    if not name.strip():
        raise invalid("name", _("Give the view a name."))
    saved = SavedReport.objects.create(
        name=name.strip()[:120],
        report_key=report_key,
        params=_clean_params(user, report_key, params),
        owner=user,
        shared=shared,
    )
    audit.record_create(saved)
    publish(SavedReportCreated(subject_id=saved.pk, report_key=report_key, shared=shared))
    return saved


def _check_owner(user: Any, saved: SavedReport) -> None:
    if saved.owner_id != user.pk:
        raise PermissionDenied(_("Only the person who saved this view can change it."))


@transaction.atomic
def update_saved_report(user: Any, saved: SavedReport, **fields: Any) -> SavedReport:
    _check_owner(user, saved)
    with audit.track(saved):
        if "name" in fields:
            if not str(fields["name"]).strip():
                raise invalid("name", _("Give the view a name."))
            saved.name = str(fields["name"]).strip()[:120]
        if "params" in fields:
            saved.params = _clean_params(user, saved.report_key, fields["params"])
        if "shared" in fields:
            saved.shared = bool(fields["shared"])
        saved.save()
    return saved


@transaction.atomic
def delete_saved_report(user: Any, saved: SavedReport) -> None:
    _check_owner(user, saved)
    for scheduled in saved.schedules.all():
        delete_scheduled_report(user, scheduled)
    audit.record(saved, "delete")
    publish(SavedReportDeleted(subject_id=saved.pk, report_key=saved.report_key))
    saved.delete()


# --- scheduled reports (T07) --------------------------------------------------------------------


def _recipients(saved: SavedReport, user_ids: Iterable[Any]) -> list[Any]:
    from django.contrib.auth import get_user_model

    from tutortrack.identity.models import Membership

    report = reports.base.get(saved.report_key)
    staff = ("owner", "admin", "branch_manager", "coordinator", "finance")
    ids = {str(u) for u in user_ids}
    if not ids:
        raise invalid("recipients", _("Choose at least one person to send it to."))
    members = {
        str(u)
        for u in Membership.objects.filter(
            user_id__in=ids, status=Membership.Status.ACTIVE, role__in=staff
        ).values_list("user_id", flat=True)
    }
    users = list(get_user_model().objects.filter(pk__in=members, is_active=True))
    allowed = [u for u in users if report is not None and has_perm(u, report.codename)]
    if len(allowed) != len(ids):
        raise invalid(
            "recipients", _("Reports can only go to staff who are allowed to see this report.")
        )
    return allowed


def _schedule_fields(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "frequency" in fields:
        if fields["frequency"] not in ScheduledReport.Frequency.values:
            raise invalid("frequency", _("Choose daily, weekly or monthly."))
        out["frequency"] = fields["frequency"]
    if "weekday" in fields:
        if not 0 <= int(fields["weekday"]) <= 6:
            raise invalid("weekday", _("Choose a day of the week."))
        out["weekday"] = int(fields["weekday"])
    if "day_of_month" in fields:
        if not 1 <= int(fields["day_of_month"]) <= 28:
            raise invalid("day_of_month", _("Choose a day from 1 to 28."))
        out["day_of_month"] = int(fields["day_of_month"])
    if "time" in fields:
        if not isinstance(fields["time"], time):
            raise invalid("time", _("Give the time as HH:MM."))
        out["time"] = fields["time"]
    if "format" in fields:
        if fields["format"] not in FORMATS:
            raise invalid("format", _("Choose CSV, Excel or PDF."))
        out["format"] = fields["format"]
    if "enabled" in fields:
        out["enabled"] = bool(fields["enabled"])
    return out


def _check_schedule_access(user: Any, saved: SavedReport) -> None:
    scope = permission_scope(user, "reporting.schedule.manage")
    if scope is None or not has_perm(user, "reporting.export"):
        raise PermissionDenied(_("You can't schedule reports."))
    if scope != "all" and saved.owner_id != user.pk:
        raise PermissionDenied(_("You can only schedule your own saved reports."))


@transaction.atomic
def create_scheduled_report(
    user: Any, saved: SavedReport, *, recipients: Iterable[Any], **fields: Any
) -> ScheduledReport:
    _check_schedule_access(user, saved)
    values = _schedule_fields(fields)
    for name in ("frequency", "time"):
        if name not in values:
            raise invalid(name, _("This field is required."))
    scheduled = ScheduledReport.objects.create(saved_report=saved, **values)
    scheduled.recipients.set(_recipients(saved, recipients))
    audit.record_create(scheduled)
    publish(
        ScheduledReportSaved(
            subject_id=scheduled.pk, frequency=scheduled.frequency, enabled=scheduled.enabled
        )
    )
    return scheduled


@transaction.atomic
def update_scheduled_report(
    user: Any,
    scheduled: ScheduledReport,
    *,
    recipients: Iterable[Any] | None = None,
    **fields: Any,
) -> ScheduledReport:
    _check_schedule_access(user, scheduled.saved_report)
    with audit.track(scheduled):
        for name, value in _schedule_fields(fields).items():
            setattr(scheduled, name, value)
        scheduled.save()
    if recipients is not None:
        before = sorted(str(u) for u in scheduled.recipients.values_list("pk", flat=True))
        chosen = _recipients(scheduled.saved_report, recipients)
        scheduled.recipients.set(chosen)
        after = sorted(str(u.pk) for u in chosen)
        if before != after:
            audit.record(scheduled, "update", {"recipients": [before, after]})
    publish(
        ScheduledReportSaved(
            subject_id=scheduled.pk, frequency=scheduled.frequency, enabled=scheduled.enabled
        )
    )
    return scheduled


@transaction.atomic
def delete_scheduled_report(user: Any, scheduled: ScheduledReport) -> None:
    _check_schedule_access(user, scheduled.saved_report)
    audit.record(scheduled, "delete")
    publish(ScheduledReportDeleted(subject_id=scheduled.pk))
    scheduled.delete()


def cron_for(scheduled: ScheduledReport) -> list[str]:
    """Cron in the organisation's timezone. Our weekday is Monday = 0; cron's Sunday = 0."""
    at = f"{scheduled.time.minute} {scheduled.time.hour}"
    if scheduled.frequency == ScheduledReport.Frequency.DAILY:
        return [f"{at} * * *"]
    if scheduled.frequency == ScheduledReport.Frequency.WEEKLY:
        return [f"{at} * * {(scheduled.weekday + 1) % 7}"]
    return [f"{at} {scheduled.day_of_month} * *"]


def sync_schedule(scheduled_id: Any) -> str | None:
    """Create, update or remove the scheduled report's Temporal Schedule."""
    from tutortrack.core.context import require_organisation_id
    from tutortrack.core.workflows.schedules import delete_schedule, ensure_schedule, schedule_id

    from .periods import org_timezone
    from .processes import ScheduledReportInput, ScheduledReportWorkflow

    org_id = require_organisation_id()
    sid = schedule_id(SCHEDULE_PROCESS, org_id, scheduled_id)
    scheduled = ScheduledReport.objects.filter(pk=scheduled_id).first()
    if scheduled is None or not scheduled.enabled:
        delete_schedule(org_id, sid)
        if scheduled is not None and scheduled.schedule_id:
            ScheduledReport.objects.filter(pk=scheduled.pk).update(schedule_id="")
        return None
    sid = ensure_schedule(
        process=SCHEDULE_PROCESS,
        workflow=ScheduledReportWorkflow,
        input=ScheduledReportInput(organisation_id=str(org_id), scheduled_id=str(scheduled.pk)),
        cron=cron_for(scheduled),
        timezone=org_timezone(),
        parts=(scheduled.pk,),
    )
    ScheduledReport.objects.filter(pk=scheduled.pk).update(schedule_id=sid)
    return sid


# --- exports (T07) ------------------------------------------------------------------------------


@transaction.atomic
def export(user: Any, report_key: str, data: Any, fmt: str) -> tuple[str, str, bytes]:
    """Run a report and render it; recorded as a run, an ``export`` audit entry and an event."""
    if fmt not in FORMATS:
        raise invalid("format", _("Choose CSV, Excel or PDF."))
    if not has_perm(user, "reporting.export"):
        raise PermissionDenied(_("You can't export reports."))
    report, params, result = reports.run(report_key, user, data)
    content = exports.render(fmt, report, params, result)
    run = ReportRun.objects.create(
        report_key=report.key,
        params={**params.as_query(), "_period": params.period.as_dict()},
        format=fmt,
        status=ReportRun.Status.COMPLETED,
        requested_by=user,
        row_count=len(result.rows),
        completed_at=now(),
    )
    audit.record(run, "export", {"report": report.key, "format": fmt, "rows": len(result.rows)})
    check_mass_export(user, run.organisation_id)
    publish(
        ReportExported(subject_id=run.pk, report_key=report.key, format=fmt, rows=len(result.rows))
    )
    return exports.filename(report, params, fmt), exports.CONTENT_TYPES[fmt], content


# --- scheduled runs (TW1) -----------------------------------------------------------------------


def generate_scheduled_run(scheduled_id: Any, run_key: str) -> str:
    """Run the saved report as its owner and store the file. Idempotent per ``run_key``
    (the workflow id). Returns the run id, or "" when the schedule is gone or paused."""
    from . import files
    from .selectors import acting_as

    existing = ReportRun.objects.filter(run_key=run_key).first()
    if existing is not None and existing.status != ReportRun.Status.FAILED:
        return str(existing.pk)
    scheduled = (
        ScheduledReport.objects.select_related("saved_report__owner")
        .filter(pk=scheduled_id)
        .first()
    )
    if scheduled is None or not scheduled.enabled:
        return ""
    saved = scheduled.saved_report
    owner = saved.owner
    with acting_as(owner):
        report, params, result = reports.run(saved.report_key, owner, saved.params)
        content = exports.render(scheduled.format, report, params, result)
    with transaction.atomic():
        run, _created = ReportRun.objects.update_or_create(
            run_key=run_key,
            defaults={
                "report_key": report.key,
                "params": {**params.as_query(), "_period": params.period.as_dict()},
                "format": scheduled.format,
                "status": ReportRun.Status.COMPLETED,
                "scheduled_report": scheduled,
                "requested_by": owner,
                "row_count": len(result.rows),
                "error": "",
                "completed_at": now(),
            },
        )
        stored = files.save(
            run,
            exports.filename(report, params, scheduled.format),
            exports.CONTENT_TYPES[scheduled.format],
            content,
        )
        run.file = stored
        run.save(update_fields=["file", "updated_at"])
        ScheduledReport.objects.filter(pk=scheduled.pk).update(last_run_at=now())
    return str(run.pk)


def deliver_run(run_id: Any, *, dedupe_key: str = "") -> int:
    """Email the run's file to the recipients (once per recipient); returns how many."""
    from tutortrack.comms import services as comms

    from .notifications import KEY

    run = ReportRun.objects.select_related("scheduled_report").get(pk=run_id)
    if run.status == ReportRun.Status.DELIVERED:
        return len(run.recipients)
    with transaction.atomic():
        messages = comms.notify(KEY, run, key=str(run.pk), immediate=True)
        sent = [m.to for m in messages if m.status != "failed"]
        run.status = ReportRun.Status.DELIVERED
        run.recipients = sorted(set(run.recipients) | set(sent))
        run.save(update_fields=["status", "recipients", "updated_at"])
        publish(
            ReportRunDelivered(
                subject_id=run.pk,
                scheduled_report_id=str(run.scheduled_report_id or ""),
                recipients=len(run.recipients),
                rows=run.row_count,
            ),
            dedupe_key=dedupe_key or None,
        )
    return len(run.recipients)


@transaction.atomic
def fail_run(scheduled_id: Any, run_key: str, error: str, *, dedupe_key: str = "") -> str:
    scheduled = (
        ScheduledReport.objects.filter(pk=scheduled_id).select_related("saved_report").first()
    )
    try:
        with transaction.atomic():
            run, _created = ReportRun.objects.get_or_create(
                run_key=run_key,
                defaults={
                    "report_key": scheduled.saved_report.report_key if scheduled else "",
                    "format": scheduled.format if scheduled else "csv",
                    "scheduled_report": scheduled,
                    "requested_by": scheduled.saved_report.owner if scheduled else None,
                },
            )
    except IntegrityError:  # pragma: no cover - concurrent retry
        run = ReportRun.objects.get(run_key=run_key)
    run.status = ReportRun.Status.FAILED
    run.error = error[:500]
    run.save(update_fields=["status", "error", "updated_at"])
    publish(
        ReportRunFailed(subject_id=run.pk, scheduled_report_id=str(scheduled_id), error=run.error),
        dedupe_key=dedupe_key or None,
    )
    return str(run.pk)


# --- maintenance --------------------------------------------------------------------------------


def rebuild_facts(user: Any | None = None) -> dict[str, int]:
    """Recompute every fact for the organisation in context (``reporting.manage``)."""
    if user is not None and not has_perm(user, "reporting.manage"):
        raise PermissionDenied(_("You can't rebuild reporting data."))
    counts = facts.rebuild()
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    with transaction.atomic():
        audit.record(
            Organisation.objects.get(pk=require_organisation_id()), "reporting_rebuild", counts
        )
    return counts


def refresh_fx_rates() -> int:
    return fx.fetch_latest()
