"""Printable timetables (FR-08-7 "print/export view: PDF weekly timetable per tutor or
student", gap G3): the visible lessons in a range, grouped by local day, as a PDF.

Times are shown in the timezone asked for (the viewer's), falling back to the
organisation's; a lesson in another timezone also shows its own local time. No prices:
the timetable is for people's diaries, so it is safe to hand to a tutor or a family.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext as _

from . import selectors

MAX_DAYS = 31


def zone_for(name: str, fallback: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or fallback)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(fallback)


def rows(
    user: Any, start: datetime, end: datetime, filters: dict[str, Any], zone: ZoneInfo
) -> list[dict[str, Any]]:
    days: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for lesson in selectors.lessons_in_range(user, start, end, filters):
        local = lesson.start.astimezone(zone)
        own = lesson.start.astimezone(ZoneInfo(lesson.timezone))
        days[local.date()].append(
            {
                # Naive local times: the template formats them (TIME_FORMAT) without moving them.
                "start": local.replace(tzinfo=None),
                "end": lesson.end.astimezone(zone).replace(tzinfo=None),
                "own_time": own.replace(tzinfo=None)
                if own.utcoffset() != local.utcoffset()
                else None,
                "own_zone": lesson.timezone,
                "title": lesson.title,
                "status_note": "" if lesson.status == "planned" else lesson.get_status_display(),
                "tutors": ", ".join(t.tutor.full_name for t in lesson.tutors.all()),
                "students": ", ".join(a.student.full_name for a in lesson.attendees.all()),
                "place": (
                    _("Online")
                    if lesson.online
                    else (lesson.room.name + " · " if lesson.room else "")
                    + (lesson.location.name if lesson.location else "")
                ),
            }
        )
    return [{"day": day, "lessons": items} for day, items in sorted(days.items())]


def pdf(
    user: Any,
    start: datetime,
    end: datetime,
    filters: dict[str, Any],
    *,
    timezone: str = "",
    subject: str = "",
) -> bytes:
    from weasyprint import HTML

    from tutortrack.core import branding
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    zone = zone_for(timezone, org.timezone)
    with translation.override(str(org.locale or "en-GB")):
        html = render_to_string(
            "scheduling/timetable.html",
            {
                "org": org,
                "subject": subject,
                "zone": str(zone),
                "start": start.astimezone(zone).replace(tzinfo=None),
                "end": end.astimezone(zone).replace(tzinfo=None),
                "days": rows(user, start, end, filters, zone),
                "brand": branding.for_documents(org.pk),
            },
        )
    return bytes(HTML(string=html).write_pdf())
