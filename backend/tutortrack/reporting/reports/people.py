"""People and compliance reports (E26-T06): active students by subject or level, tutor
compliance status and the recruitment funnel."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _

from .. import dims, periods
from ..models import FactLesson
from .base import (
    GROUP_LABELS,
    Column,
    Params,
    ReportDef,
    Result,
    filter_facts,
    in_period,
    percent,
    register,
    scoped,
    scoped_by,
)

CODENAME = "reporting.people.view"


def active_students(user: Any, params: Params) -> Result:
    """Distinct students with a lesson (not cancelled) in the period."""
    from tutortrack.scheduling.models import LessonAttendee

    lessons = scoped(user, FactLesson.objects.exclude(status="cancelled"), CODENAME)
    lessons = filter_facts(
        in_period(lessons, params),
        params,
        {
            "branch": "branch_id",
            "tutor": "tutor_id",
            "service": "service_id",
            "subject": "subject_id",
        },
    )
    qs = LessonAttendee.objects.filter(lesson_id__in=lessons.values("lesson_id")).exclude(
        outcome__startswith="cancelled"
    )
    field = {
        "subject": "lesson__service__subject_id",
        "level": "lesson__service__level_id",
        "service": "lesson__service_id",
        "branch": "lesson__branch_id",
    }[params.group_by]
    data = qs.values(field).annotate(students=Count("student_id", distinct=True)).order_by(field)
    names = dims.labels(params.group_by, (r[field] for r in data))
    total = qs.values("student_id").distinct().count()
    rows = [
        {
            "group": names.get(str(r[field]), str(_("(none)"))),
            "group_id": str(r[field] or ""),
            "students": r["students"],
            "share": percent(r["students"], total),
        }
        for r in data
    ]
    return Result(
        columns=[
            Column("group", GROUP_LABELS[params.group_by]),
            Column("students", _("Students"), "count"),
            Column("share", _("% of students"), "percent"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["students"]},
        totals=[{"students": total}],
    )


register(
    ReportDef(
        key="active_students",
        title=_("Active students by subject"),
        category="people",
        codename=CODENAME,
        description=_("Students having lessons in the period, by subject, level or service."),
        run=active_students,
        filters=("branch", "tutor", "service", "subject"),
        group_by=("subject", "level", "service", "branch"),
        ordering="-students",
    )
)


def tutor_compliance(user: Any, params: Params) -> Result:
    from tutortrack.people.models import TutorProfile
    from tutortrack.recruitment.models import ComplianceRecord, TutorComplianceState

    tutors = scoped_by(
        user,
        TutorProfile.objects.filter(status__in=("onboarding", "active", "restricted")),
        CODENAME,
        branch="branches",
        own=Q(membership__user=user),
    ).distinct()
    if params.tutor:
        tutors = tutors.filter(pk__in=params.tutor)
    if params.branch:
        tutors = tutors.filter(branches__in=params.branch)
    today = periods.org_today()
    soon = today + timedelta(days=30)
    records = (
        ComplianceRecord.objects.filter(tutor__in=tutors)
        .values("tutor_id")
        .annotate(
            verified=Count("pk", filter=Q(status="verified")),
            waiting=Count("pk", filter=Q(status="submitted")),
            missing=Count("pk", filter=Q(status__in=("missing", "rejected"))),
            expired=Count(
                "pk", filter=Q(status="expired") | Q(status="verified", expiry_date__lte=today)
            ),
            expiring=Count(
                "pk", filter=Q(status="verified", expiry_date__gt=today, expiry_date__lte=soon)
            ),
        )
    )
    by = {str(r["tutor_id"]): r for r in records}
    problems = {
        str(s.tutor_id): len(s.problems or [])
        for s in TutorComplianceState.objects.filter(tutor__in=tutors)
    }
    statuses = dict(TutorProfile.Status.choices)
    rows = []
    for tutor in tutors.order_by("last_name", "first_name"):
        r = by.get(str(tutor.pk), {})
        rows.append(
            {
                "group": tutor.full_name,
                "group_id": str(tutor.pk),
                "status": str(statuses.get(tutor.status, tutor.status)),
                "verified": r.get("verified", 0),
                "waiting": r.get("waiting", 0),
                "missing": r.get("missing", 0),
                "expired": r.get("expired", 0),
                "expiring": r.get("expiring", 0),
                "problems": problems.get(str(tutor.pk), 0),
            }
        )
    return Result(
        columns=[
            Column("group", _("Tutor")),
            Column("status", _("Status")),
            Column("verified", _("Verified"), "count"),
            Column("waiting", _("Waiting for checks"), "count"),
            Column("missing", _("Missing or rejected"), "count"),
            Column("expired", _("Expired"), "count"),
            Column("expiring", _("Expiring in 30 days"), "count"),
            Column("problems", _("Blocking problems"), "count"),
        ],
        rows=rows,
    )


register(
    ReportDef(
        key="tutor_compliance",
        title=_("Tutor compliance"),
        category="people",
        codename=CODENAME,
        description=_("Each working tutor's checks: verified, missing, expired and expiring."),
        run=tutor_compliance,
        filters=("branch", "tutor"),
        period=False,
        ordering="-problems",
    )
)


def recruitment_funnel(user: Any, params: Params) -> Result:
    from tutortrack.recruitment.models import ApplicationStage, TutorApplication

    start, end = params.period.utc_bounds(periods.org_timezone())
    qs = scoped_by(
        user,
        TutorApplication.objects.filter(created_at__gte=start, created_at__lt=end),
        CODENAME,
        branch="opening__branch_id",
    )
    if params.branch:
        qs = qs.filter(opening__branch_id__in=params.branch)
    total = qs.count()
    if params.group_by == "status":
        statuses = dict(TutorApplication.Status.choices)
        data = qs.values("status").annotate(n=Count("pk")).order_by("-n")
        rows = [
            {
                "group": str(statuses.get(r["status"], r["status"])),
                "group_id": r["status"],
                "applications": r["n"],
                "share": percent(r["n"], total),
            }
            for r in data
        ]
    else:
        current = dict(qs.values("stage_id").annotate(n=Count("pk")).values_list("stage_id", "n"))
        rows = [
            {
                "group": stage.name,
                "group_id": str(stage.pk),
                "applications": current.get(stage.pk, 0),
                "share": percent(current.get(stage.pk, 0), total),
            }
            for stage in ApplicationStage.objects.order_by("order")
        ]
    hired = qs.filter(status="hired").count()
    return Result(
        columns=[
            Column("group", GROUP_LABELS[params.group_by]),
            Column("applications", _("Applications"), "count"),
            Column("share", _("Share %"), "percent"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["applications"]},
        totals=[{"applications": total, "share": percent(hired, total)}],
        notes=[
            str(_("%(hired)s of %(total)s applications were hired."))
            % {"hired": hired, "total": total}
        ],
    )


register(
    ReportDef(
        key="recruitment_funnel",
        title=_("Recruitment funnel"),
        category="people",
        codename=CODENAME,
        description=_("Tutor applications received in the period by stage or outcome."),
        run=recruitment_funnel,
        filters=("branch",),
        group_by=("stage", "status"),
        default_period="last_90_days",
    )
)
