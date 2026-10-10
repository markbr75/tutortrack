"""The scheduled-report email (FR-26-4), registered with the comms notification registry so
organisations can edit its template like any other message."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms import defaults
from tutortrack.comms.catalogue import SAMPLE_BASE, organisation, tenant_link, user_recipient
from tutortrack.comms.registry import Delivery, NotificationType, register

KEY = "scheduled_report"


def _load(pk: str) -> Any:
    from .models import ReportRun

    return (
        ReportRun.objects.select_related("scheduled_report__saved_report", "file")
        .filter(pk=pk)
        .first()
    )


def _context(run: Any) -> dict[str, Any]:
    saved = run.scheduled_report.saved_report
    period = run.params.get("_period") or {}
    return {
        "name": saved.name,
        "period": f"{period.get('from', '')} \N{EN DASH} {period.get('to', '')}" if period else "",
        "rows": run.row_count,
        "format": run.format.upper(),
        "link": tenant_link("/analytics/saved"),
    }


def _resolve(run: Any) -> list[Delivery]:
    from tutortrack.core.permissions import has_perm

    from .reports.base import get

    report = get(run.report_key)
    base = {"organisation": organisation(), "report": _context(run)}
    out = []
    for user in run.scheduled_report.recipients.filter(is_active=True):
        # Recipients must still be allowed to see this kind of report.
        if report is None or not has_perm(user, report.codename):
            continue
        r = user_recipient(user)
        out.append(Delivery(r, {**base, "recipient": {"name": r.name, "first_name": r.first_name}}))
    return out


def _attachments(run: Any) -> list[tuple[str, bytes, str]]:
    from . import files

    if run.file is None:
        return []
    return [(run.file.filename, files.read(run.file), run.file.content_type)]


register(
    NotificationType(
        key=KEY,
        label=str(_("Scheduled report")),
        category="staff",
        audience="staff",
        channels=("email",),
        default_channels=("email",),
        resolve=_resolve,
        load=_load,
        related_type="reporting.reportrun",
        variables=(
            "recipient.first_name",
            "report.name",
            "report.period",
            "report.rows",
            "report.format",
            "report.link",
        ),
        sample={
            **SAMPLE_BASE,
            "report": {
                "name": "Monthly revenue",
                "period": "2026-09-01 \N{EN DASH} 2026-09-30",
                "rows": 12,
                "format": "CSV",
                "link": "https://example.com/analytics/saved",
            },
        },
        attachments=_attachments,
        link=lambda run: "/analytics/saved",
    )
)

defaults.DEFAULTS[(KEY, "email")] = (
    "{{ report.name }}",
    "Hello {{ recipient.first_name }},\n\nYour scheduled report {{ report.name }} "
    "({{ report.period }}) is attached as {{ report.format }} with {{ report.rows }} rows.\n\n"
    "Saved and scheduled reports: {{ report.link }}" + defaults.SIGN,
)
