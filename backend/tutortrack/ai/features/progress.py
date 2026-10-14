"""FR-31-2 Progress report comments (E21 FR-21-6 seam) and the "explain to parent"
rewrite with optional translation into the contact's preferred language."""

from __future__ import annotations

import json
from typing import Any

from tutortrack.core.context import get_request_context

from .. import engine, prompts
from ..redaction import Redactor
from . import quoted, scoped_get

# Snapshot keys that may be sent: the family-visible facts E21 stores on the report.
SNAPSHOT_KEYS = ("period", "attendance", "highlights", "topics", "goals", "assessments", "homework")
LANGUAGE_NAMES = {
    "en": "English",
    "en-gb": "UK English",
    "en-us": "US English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "nl": "Dutch",
    "pl": "Polish",
    "it": "Italian",
    "pt": "Portuguese",
    "ur": "Urdu",
    "pa": "Punjabi",
    "zh": "Chinese",
    "ar": "Arabic",
    "ro": "Romanian",
}


def _summary(report: Any, user: Any) -> engine.Result:
    snapshot = report.snapshot or {}
    redactor = Redactor()
    student = report.student
    redactor.person(
        student.full_name,
        kind="STUDENT",
        first_name=student.first_name,
        last_name=student.last_name,
    )
    for highlight in snapshot.get("highlights") or []:
        if highlight.get("tutor"):
            redactor.person(str(highlight["tutor"]), kind="TUTOR")
    facts = {key: snapshot.get(key) for key in SNAPSHOT_KEYS if snapshot.get(key) is not None}
    content = "\n".join(
        [
            f"Student: {student.full_name}",
            f"Report: {report.title} ({report.period_start} to {report.period_end})",
            "",
            "Facts (JSON):",
            json.dumps(facts, sort_keys=True, default=str),
        ]
    )
    return engine.run(prompts.PROGRESS_SUMMARY, user=user, content=content, redactor=redactor)


def draft(user: Any, report_id: Any) -> dict[str, Any]:
    from tutortrack.learning.models import ProgressReport

    report = scoped_get(
        user, ProgressReport, "learning.progress.write", report_id, related=("student",)
    )
    result = _summary(report, user)
    return {"request": str(result.log.pk), "summary": result.text}


def available() -> bool:
    from ..selectors import is_enabled

    return is_enabled("progress_report")


def drafter(report: Any) -> str:
    """Registered with ``learning.progress`` (E21 seam): the endpoint there has already
    checked the person may write the report."""
    from tutortrack.identity.models import User

    user_id = get_request_context().user_id
    user = User.objects.filter(pk=user_id).first() if user_id else None
    return _summary(report, user).text


def language_name(code: str) -> str:
    code = (code or "").strip().lower()
    return LANGUAGE_NAMES.get(code) or LANGUAGE_NAMES.get(code.split("-")[0], "") or code


def rewrite(
    user: Any,
    *,
    text: str,
    language: str = "",
    contact_id: Any = None,
    student_id: Any = None,
) -> dict[str, Any]:
    """Plain-language rewrite for a parent; ``contact_id`` uses that contact's preferred
    language when ``language`` isn't given; ``student_id`` pseudonymises the student."""
    from tutortrack.people.models import Contact, Student

    redactor = Redactor()
    if student_id:
        student = scoped_get(user, Student, "people.student.view", student_id)
        redactor.person(
            student.full_name,
            kind="STUDENT",
            first_name=student.first_name,
            last_name=student.last_name,
        )
    if contact_id:
        contact = scoped_get(user, Contact, "people.contact.view", contact_id)
        redactor.person(
            f"{contact.first_name} {contact.last_name}".strip(),
            kind="CONTACT",
            first_name=contact.first_name,
            last_name=contact.last_name,
        )
        language = language or contact.language
    target = language_name(language)
    content = "\n".join(
        [
            f"Target language: {target or 'the same language as the text'}",
            "",
            "Text:",
            quoted(text),
        ]
    )
    result = engine.run(prompts.PARENT_REWRITE, user=user, content=content, redactor=redactor)
    data = result.data or {}
    return {
        "request": str(result.log.pk),
        "text": str(data.get("text") or ""),
        "language": language or "",
    }
