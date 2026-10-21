"""Scheduled progress-report drafts (gap G5c, FR-21-6).

``learning.progress_schedule`` turns on a per-organisation **Temporal Schedule** running
``ProgressReportRunWorkflow`` (kept in sync with the setting by ``sync_schedule``):

* ``monthly``: at 06:00 on the 1st (organisation time) it drafts last month's reports.
* ``termly``: at 06:00 every day it looks for terms (E20 ``courses.Term``) that ended in
  the last week and drafts reports for those terms, for students in the term's branch.

Each run drafts a report for every student with lessons in the period who hasn't got one
for that period yet (existing reports, drafts included, are left alone, so reruns and the
week of look-back never overwrite a tutor's work). The draft's author is the student's
main tutor in the period (most lessons). Each author is told how many drafts wait for
their comments, staff with ``learning.progress.approve`` get one summary, and
``progress_report.batch_drafted`` is published once per period.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.db.models import Count
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.people.models import Student, TutorProfile
from tutortrack.tenancy.settings_service import get_setting

from . import events, selectors
from .models import ProgressReport

MONTHLY_CRON = ["0 6 1 * *"]
DAILY_CRON = ["0 6 * * *"]
TERM_LOOKBACK_DAYS = 7


def org_today() -> date:
    from tutortrack.core.time import now, to_tz
    from tutortrack.tenancy.models import Organisation

    tz = Organisation.objects.get(pk=require_organisation_id()).timezone
    return to_tz(now(), str(tz)).date()


def last_month(today: date) -> tuple[date, date]:
    end = today.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def periods(today: date) -> list[dict[str, Any]]:
    """The periods to draft for on ``today``: ``{"period", "start", "end", "branches"}``
    (``branches`` empty = every branch)."""
    mode = get_setting("learning.progress_schedule")
    if mode == "monthly":
        start, end = last_month(today)
        return [{"period": "monthly", "start": start, "end": end, "branches": []}]
    if mode != "termly":
        return []
    from tutortrack.courses.models import Term

    ended = Term.objects.filter(
        end_date__lt=today, end_date__gte=today - timedelta(days=TERM_LOOKBACK_DAYS)
    ).values_list("start_date", "end_date", "branch_id")
    grouped: dict[tuple[date, date], set[str]] = defaultdict(set)
    for start, end, branch in ended:
        grouped[(start, end)].add(str(branch))
    return [
        {"period": "termly", "start": start, "end": end, "branches": sorted(branches)}
        for (start, end), branches in sorted(grouped.items())
    ]


def due_students(start: date, end: date, branches: list[str]) -> list[str]:
    """Students with lessons in the period (in those branches) and no report for it."""
    from .services import students_with_lessons

    have = set(
        ProgressReport.objects.filter(period_start=start, period_end=end).values_list(
            "student_id", flat=True
        )
    )
    return [
        str(s.pk)
        for s in students_with_lessons(start, end)
        if s.pk not in have and (not branches or str(s.branch_id) in branches)
    ]


def plan(today: date | None = None) -> list[dict[str, Any]]:
    """What a run does: each period (ISO dates) with the students to draft for."""
    today = today or org_today()
    out = []
    for p in periods(today):
        out.append(
            {
                "period": p["period"],
                "start": p["start"].isoformat(),
                "end": p["end"].isoformat(),
                "students": due_students(p["start"], p["end"], p["branches"]),
            }
        )
    return out


def main_tutors(student_ids: list[str], start: date, end: date) -> dict[str, str]:
    """Each student's main tutor in the period: the one who taught most of their lessons."""
    from tutortrack.scheduling.models import Lesson, LessonTutor

    since, until = selectors.period_bounds(start, end)
    rows = (
        LessonTutor.objects.filter(
            lesson__attendees__student_id__in=student_ids,
            lesson__start__gte=since,
            lesson__start__lt=until,
        )
        .exclude(lesson__status=Lesson.Status.CANCELLED)
        .values("lesson__attendees__student_id", "tutor_id")
        .annotate(n=Count("lesson", distinct=True))
        .order_by("lesson__attendees__student_id", "-n", "tutor_id")
    )
    out: dict[str, str] = {}
    for row in rows:
        out.setdefault(str(row["lesson__attendees__student_id"]), str(row["tutor_id"]))
    return out


def draft(period: str, start: date, end: date, student_ids: list[str]) -> int:
    """Draft the missing reports (idempotent: students with a report are skipped)."""
    from .services import generate_progress_report

    authors = main_tutors(student_ids, start, end)
    tutors = {str(t.pk): t for t in TutorProfile.objects.filter(pk__in=set(authors.values()))}
    have = set(
        ProgressReport.objects.filter(
            period_start=start, period_end=end, student_id__in=student_ids
        ).values_list("student_id", flat=True)
    )
    created = 0
    for student in Student.objects.filter(pk__in=student_ids).exclude(pk__in=have):
        generate_progress_report(
            student,
            period_start=start,
            period_end=end,
            period=period,
            author=tutors.get(authors.get(str(student.pk), "")),
        )
        created += 1
    return created


def announce(period: str, start: date, end: date) -> int:
    """Tell each author how many drafts wait for them, staff once, and publish the batch
    event. Notices and the event are keyed on the period, so a rerun doesn't repeat them."""
    from tutortrack.comms.services import notify

    drafts = ProgressReport.objects.filter(
        period_start=start, period_end=end, status=ProgressReport.Status.DRAFT
    )
    total = drafts.count()
    if not total:
        return 0
    label = _period_label(period, start, end)
    per_author = drafts.filter(author__isnull=False).values("author_id").annotate(n=Count("id"))
    for row in per_author:
        tutor = TutorProfile.objects.filter(pk=row["author_id"]).first()
        if tutor is not None:
            notify(
                "progress_reports_drafted",
                (tutor, row["n"], label),
                key=f"progress-drafts:{tutor.pk}:{start}:{end}",
            )
    title = ngettext(
        "%(count)s progress report drafted for %(period)s",
        "%(count)s progress reports drafted for %(period)s",
        total,
    ) % {"count": total, "period": label}
    notify(
        "staff_progress_reports_drafted",
        (title, _("Tutors have been asked to add their comments."), "/learning"),
        key=f"progress-drafts:{start}:{end}",
    )
    with transaction.atomic():
        publish(
            events.ProgressReportsDrafted(
                subject_id=require_organisation_id(),
                period=period,
                period_start=start.isoformat(),
                period_end=end.isoformat(),
                created=total,
            ),
            dedupe_key=f"progress-drafted:{require_organisation_id()}:{start}:{end}",
        )
    return total


def _period_label(period: str, start: date, end: date) -> str:
    if period == ProgressReport.Period.MONTHLY:
        return start.strftime("%Y-%m")
    return f"{start.isoformat()} \N{EN DASH} {end.isoformat()}"


# --- the Temporal Schedule ----------------------------------------------------------------------


def sync_schedule() -> str:
    """Create, update or delete the organisation's progress-report schedule."""
    from tutortrack.core.workflows.schedules import delete_schedule, ensure_schedule, schedule_id
    from tutortrack.tenancy.models import Organisation

    from .processes import PROGRESS_RUN_PROCESS, ProgressReportRunWorkflow, ProgressRunInput

    org_id = require_organisation_id()
    mode = get_setting("learning.progress_schedule")
    if mode not in ("monthly", "termly"):
        delete_schedule(org_id, schedule_id(PROGRESS_RUN_PROCESS, org_id))
        return ""
    org = Organisation.objects.get(pk=org_id)
    return ensure_schedule(
        process=PROGRESS_RUN_PROCESS,
        workflow=ProgressReportRunWorkflow,
        input=ProgressRunInput(organisation_id=str(org_id)),
        cron=MONTHLY_CRON if mode == "monthly" else DAILY_CRON,
        timezone=str(org.timezone or "UTC"),
    )
