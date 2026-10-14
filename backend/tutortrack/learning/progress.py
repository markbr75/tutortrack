"""Progress report contents (FR-21-6): the snapshot a report is generated from, the PDF,
and the AI-draft seam for E31.

The snapshot gathers, for one student and period: attendance (E08/E09 attendance
outcomes), highlights from lesson reports (client-visible answers), topics covered and
mastery, goals, assessment results and homework completion. It is stored on the report so
what the family receives never changes after approval.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import FeatureDisabled

from . import selectors
from .models import (
    AssessmentResult,
    Goal,
    HomeworkAssignment,
    LessonTopic,
    ProgressReport,
    TopicMastery,
)

MAX_HIGHLIGHTS = 8
HIGHLIGHT_CHARS = 400
_TAGS = re.compile(r"<[^>]+>")


def _text(value: Any) -> str:
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return re.sub(r"\s+", " ", _TAGS.sub(" ", str(value or ""))).strip()


def attendance(student: Any, start: Any, end: Any) -> dict[str, Any]:
    from tutortrack.delivery.selectors import ATTENDED
    from tutortrack.scheduling.models import LessonAttendee

    excluded = {"cancelled_tutor", "cancelled_admin"}
    outcomes = list(
        LessonAttendee.objects.filter(
            student=student, lesson__start__gte=start, lesson__start__lt=end
        )
        .exclude(outcome="")
        .exclude(outcome__in=excluded)
        .values_list("outcome", flat=True)
    )
    by_outcome: dict[str, int] = {}
    for outcome in outcomes:
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
    attended = sum(1 for o in outcomes if o in ATTENDED)
    rate = f"{attended * 100 / len(outcomes):.1f}" if outcomes else None
    return {"lessons": len(outcomes), "attended": attended, "rate": rate, "by_outcome": by_outcome}


def highlights(student: Any, start: Any, end: Any) -> list[dict[str, Any]]:
    """What the family could already read: client-visible answers of written reports."""
    from tutortrack.delivery import templates
    from tutortrack.delivery.models import LessonReport

    reports = (
        LessonReport.objects.filter(
            lesson__attendees__student=student,
            lesson__start__gte=start,
            lesson__start__lt=end,
            status__in=[LessonReport.Status.SUBMITTED, LessonReport.Status.APPROVED],
        )
        .select_related("lesson", "tutor", "template_version")
        .order_by("lesson__start")
        .distinct()
    )
    out = []
    for report in reports:
        fields = report.template_version.fields
        visible = templates.visible_answers(fields, report.answers or {}, "client")
        parts = [
            _text(visible[f["key"]])
            for f in fields
            if f["key"] in visible and f["type"] in {"rich_text", "text", "next_steps"}
        ]
        text = " ".join(p for p in parts if p)
        if text:
            out.append(
                {
                    "date": report.lesson.start.date().isoformat(),
                    "lesson": report.lesson.title,
                    "tutor": report.tutor.full_name,
                    "text": text[:HIGHLIGHT_CHARS],
                }
            )
    return out[-MAX_HIGHLIGHTS:]


def topics(student: Any, start: Any, end: Any) -> dict[str, Any]:
    from tutortrack.scheduling.models import LessonAttendee

    lessons = LessonAttendee.objects.filter(
        student=student, lesson__start__gte=start, lesson__start__lt=end
    ).values("lesson_id")
    rows = (
        LessonTopic.objects.filter(lesson_id__in=lessons)
        .select_related("node__curriculum", "node__parent")
        .order_by("node__curriculum__name", "node__parent__position", "node__position")
    )
    levels = dict(TopicMastery.objects.filter(student=student).values_list("node_id", "level"))
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = seen.setdefault(
            str(row.node_id),
            {
                "name": row.node.name,
                "unit": row.node.parent.name if row.node.parent else "",
                "curriculum": row.node.curriculum.name,
                "level": levels.get(row.node_id, "not_started"),
                "lessons": 0,
            },
        )
        entry["lessons"] += 1
    summary = dict.fromkeys(TopicMastery.RANK, 0)
    for level in levels.values():
        summary[level] += 1
    return {"covered": list(seen.values()), "mastery": summary}


def goals(student: Any) -> list[dict[str, Any]]:
    return [
        {
            "title": g.title,
            "kind": g.kind,
            "status": g.status,
            "progress_percent": g.progress_percent,
            "target_grade": g.target_grade,
            "current_grade": g.current_grade,
            "due_date": (g.exam_date or g.due_date).isoformat()
            if (g.exam_date or g.due_date)
            else None,
            "milestones": [
                {"title": m.title, "done": m.done_at is not None} for m in g.milestones.all()
            ],
        }
        for g in Goal.objects.filter(student=student, visible_to_family=True)
        .exclude(status=Goal.Status.ABANDONED)
        .prefetch_related("milestones")
    ]


def assessments(student: Any, first: date, last: date) -> list[dict[str, Any]]:
    return [
        {
            "date": r.taken_on.isoformat(),
            "name": r.assessment.name,
            "kind": r.assessment.kind,
            "score": str(r.score) if r.score is not None else None,
            "max_score": str(r.max_score) if r.max_score is not None else None,
            "percent": str(r.percent) if r.percent is not None else None,
            "grade": r.grade,
        }
        for r in AssessmentResult.objects.filter(
            student=student, taken_on__gte=first, taken_on__lte=last, visible_to_family=True
        )
        .select_related("assessment")
        .order_by("taken_on")
    ]


def build_snapshot(student: Any, first: date, last: date) -> dict[str, Any]:
    start, end = selectors.period_bounds(first, last)
    homework = HomeworkAssignment.objects.filter(student=student, due_at__gte=start, due_at__lt=end)
    return {
        "student": {"id": str(student.pk), "name": student.full_name},
        "period": {"start": first.isoformat(), "end": last.isoformat()},
        "attendance": attendance(student, start, end),
        "highlights": highlights(student, start, end),
        "topics": topics(student, start, end),
        "goals": goals(student),
        "assessments": assessments(student, first, last),
        "homework": selectors.homework_stats(homework),
    }


# --- PDF ----------------------------------------------------------------------------------------

LEVEL_LABELS = {
    "not_started": _("Not started"),
    "learning": _("Learning"),
    "secure": _("Secure"),
    "mastered": _("Mastered"),
}


def pdf(report: ProgressReport) -> bytes:
    from django.template.loader import render_to_string
    from django.utils import translation
    from weasyprint import HTML

    from tutortrack.core import branding
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=report.organisation_id)
    locale = str(getattr(org, "locale", "en-GB") or "en-GB")
    snapshot = report.snapshot or {}
    with translation.override(locale):
        html = render_to_string(
            "learning/progress_report.html",
            {
                "org": org,
                "brand": branding.for_documents(org.pk, report.branch_id),
                "report": report,
                "snap": snapshot,
                "levels": {k: str(v) for k, v in LEVEL_LABELS.items()},
                "topics": [
                    {**t, "level_label": str(LEVEL_LABELS.get(t["level"], t["level"]))}
                    for t in (snapshot.get("topics") or {}).get("covered", [])
                ],
            },
        )
    return bytes(HTML(string=html).write_pdf())


# --- AI draft seam (E31) ------------------------------------------------------------------------

Drafter = Callable[[ProgressReport], str]
_drafter: Drafter | None = None
_available: Callable[[], bool] | None = None


def register_drafter(drafter: Drafter | None, available: Callable[[], bool] | None = None) -> None:
    """E31 registers its summary writer here (and whether the organisation has it turned
    on); until then drafting is unavailable."""
    global _drafter, _available
    _drafter = drafter
    _available = available


def can_draft() -> bool:
    return _drafter is not None and (_available is None or _available())


def draft_summary(report: ProgressReport) -> str:
    if _drafter is None:
        raise FeatureDisabled("ai_assistant")
    return _drafter(report)
