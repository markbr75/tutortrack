"""FR-31-1 Lesson report drafting: a tutor's rough notes (typed or a voice note) become
answers for the report's template fields (E09), with suggested curriculum topics (E21)
and homework, in the organisation's tone and spelling. The tutor edits and submits through
the normal report endpoints; applying the draft marks the report AI-assisted."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

from .. import engine, prompts
from ..prompts import STR, STRS, obj
from ..redaction import Redactor
from . import quoted, scoped_get

TEXT_TYPES = {"rich_text", "text", "homework", "next_steps"}
CHOICE_LIST = {"multi_select", "checklist"}
MAX_TOPICS = 60


def field_schema(field: dict[str, Any], topic_ids: list[str]) -> dict[str, Any] | None:
    kind = field["type"]
    options = [str(o) for o in field.get("options", [])]
    if kind in TEXT_TYPES:
        return STR
    if kind == "rating":
        return {"type": "integer", "enum": [0, 1, 2, 3, 4, 5]}  # 0: not rated
    if kind == "select":
        return {"type": "string", "enum": [*options, ""]}
    if kind in CHOICE_LIST:
        return {"type": "array", "items": {"type": "string", "enum": options}}
    if kind == "topics":
        if topic_ids:
            return {"type": "array", "items": {"type": "string", "enum": topic_ids}}
        return STRS
    return None  # attachments are never drafted


def output_schema(fields: list[dict[str, Any]], topic_ids: list[str]) -> dict[str, Any]:
    answers = {}
    for field in fields:
        schema = field_schema(field, topic_ids)
        if schema is not None:
            answers[field["key"]] = schema
    topics = (
        {"type": "array", "items": {"type": "string", "enum": topic_ids}} if topic_ids else STRS
    )
    return obj({"answers": obj(answers), "suggested_topic_ids": topics, "homework": STR})


def clean(fields: list[dict[str, Any]], raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only answers the template accepts (a bad one is dropped, not fatal)."""
    from tutortrack.delivery import templates

    out: dict[str, Any] = {}
    for field in fields:
        value = raw.get(field["key"])
        if value in (None, "", [], 0):
            continue
        try:
            out.update(templates.clean_answers([field], {field["key"]: value}))
        except BusinessRuleViolation:
            continue
    return out


def draft(user: Any, report_id: Any, *, notes: str, audio: Any = None) -> dict[str, Any]:
    from tutortrack.delivery.models import LessonReport
    from tutortrack.learning.selectors import topic_suggestions

    from .. import transcription
    from ..selectors import style_for

    report = scoped_get(
        user,
        LessonReport,
        "delivery.report.write",
        report_id,
        related=("lesson__service__subject", "lesson__service__level", "template_version"),
    )
    if report.status in (LessonReport.Status.APPROVED,):
        raise BusinessRuleViolation(_("This report is already approved."))
    transcript = ""
    if audio is not None:
        transcript = transcription.transcribe(
            audio, language=style_for("lesson_report")["language"]
        )
    if not (notes or "").strip() and not transcript:
        raise BusinessRuleViolation(
            _("Add some notes or a voice note first."),
            extra={"errors": {"notes": [_("Add some notes.")]}},
        )
    lesson = report.lesson
    fields = [f for f in report.template_version.fields if f.get("type") != "attachment"]
    topics = topic_suggestions(lesson=lesson, limit=MAX_TOPICS)
    topic_names = {str(t.pk): f"{t.parent.name} > {t.name}" if t.parent else t.name for t in topics}
    redactor = Redactor()
    names = []
    for attendee in lesson.attendees.select_related("student"):
        student = attendee.student
        names.append(
            redactor.person(
                student.full_name,
                kind="STUDENT",
                first_name=student.first_name,
                last_name=student.last_name,
            )
        )
    redactor.person(report.tutor.full_name, kind="TUTOR")
    service = lesson.service
    local = lesson.start.astimezone(ZoneInfo(lesson.timezone))
    lines = [
        f"Lesson: {lesson.title}",
        f"Subject: {getattr(service.subject, 'name', '') or '-'}"
        f" {getattr(service.level, 'name', '') or ''}".rstrip(),
        f"Date: {local:%A %d %B %Y}, {int((lesson.end - lesson.start).total_seconds() // 60)}"
        " minutes",
        f"Students: {', '.join(names) or '-'}",
        "",
        "Report template fields (key, type, audience, options):",
    ]
    for field in fields:
        extra = f"; options: {', '.join(field['options'])}" if field.get("options") else ""
        required = "; required" if field.get("required") else ""
        lines.append(
            f"- {field['key']}: {field['label']} ({field['type']}, audience "
            f"{field.get('visibility', 'client')}{required}{extra})"
        )
    lines += ["", "Candidate curriculum topics (id: unit > topic):"]
    lines += [f"- {pk}: {name}" for pk, name in topic_names.items()] or ["- none"]
    lines += ["", "Tutor's notes:", quoted(notes)]
    if transcript:
        lines += ["", "Voice note transcript:", quoted(transcript)]
    result = engine.run(
        prompts.LESSON_REPORT,
        user=user,
        content="\n".join(lines),
        redactor=redactor,
        schema=output_schema(fields, list(topic_names)),
    )
    data = result.data or {}
    suggested = [t for t in data.get("suggested_topic_ids") or [] if t in topic_names]
    return {
        "request": str(result.log.pk),
        "answers": clean(fields, data.get("answers") or {}),
        "suggested_topics": [{"id": t, "name": topic_names[t]} for t in suggested],
        "homework": str(data.get("homework") or ""),
        "transcript": transcript,
    }
