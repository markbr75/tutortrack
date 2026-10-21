"""Whitelisted, permission-checked tools for the command bar (FR-31-5) and the business
copilot (FR-31-7).

Every tool maps to a selector or service of the owning app and runs as the requesting
person: reads go through ``scope_queryset`` / the reporting engine's own permission and
data-scope checks, and write tools only *propose* (``services.propose``) for the person
to confirm. Inputs are validated here (strict schemas are a guarantee from the API, not a
reason to trust them); failures come back as ``is_error`` results the model can act on.
Names in results are registered with the request's ``Redactor`` so they reach the model
as placeholders.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils.translation import gettext as _

from tutortrack.core.exceptions import DomainError
from tutortrack.core.permissions import has_perm, scope_queryset
from tutortrack.core.time import now

from .prompts import STR, obj
from .redaction import Redactor

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
LOOKAHEAD_DAYS = 90
MAX_ROWS = 25


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    run: Callable[..., Any]

    def definition(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


class BaseToolBox:
    """Runs tools for one request; subclasses list them in ``tools()``."""

    def __init__(self, user: Any, redactor: Redactor) -> None:
        self.user = user
        self.redactor = redactor
        self._tools = {tool.name: tool for tool in self.tools()}

    def tools(self) -> list[Tool]:
        raise NotImplementedError

    def definitions(self) -> list[dict[str, Any]]:
        return [self._tools[name].definition() for name in sorted(self._tools)]

    def call(self, name: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool {name}."}, True
        try:
            return tool.run(**arguments), False
        except DomainError as exc:
            return {"error": str(exc.detail)}, True
        except (TypeError, ValueError) as exc:
            return {"error": f"Invalid input: {exc}"}, True


def _zone() -> ZoneInfo:
    from tutortrack.reporting.periods import org_timezone

    return ZoneInfo(org_timezone())


def prime_names(user: Any, text: str, redactor: Redactor) -> None:
    """Register students and tutors (that the person may see) whose names appear in
    free text, so an instruction like "move Sam's lesson" is pseudonymised before the
    first request, not only after a lookup."""
    from tutortrack.people.models import Student, TutorProfile

    text = (text or "").replace(chr(0x2019), "'")  # curly apostrophes
    words = {w.removesuffix("'s").lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]+", text)}
    words = {w for w in words if len(w) >= 2}
    if not words:
        return
    match = Q()
    for word in list(words)[:40]:
        match |= Q(first_name__iexact=word) | Q(last_name__iexact=word)
    for model, codename, kind in (
        (Student, "people.student.view", "STUDENT"),
        (TutorProfile, "people.tutor.view", "TUTOR"),
    ):
        for person in scope_queryset(user, model.objects.all(), codename).filter(match)[:30]:
            redactor.person(
                person.full_name,
                kind=kind,
                first_name=person.first_name,
                last_name=person.last_name,
            )


def today_line() -> str:
    """Per-request context for the user message (never the cached system prompt)."""
    zone = _zone()
    local = now().astimezone(zone)
    return f"Today is {local:%A %d %B %Y}, {local:%H:%M} in {zone.key}."


# --- command bar ------------------------------------------------------------------------------


class CommandToolBox(BaseToolBox):
    feature = "command_bar"

    def __init__(self, user: Any, redactor: Redactor) -> None:
        self.proposals: list[Any] = []
        self.searches: list[dict[str, Any]] = []
        super().__init__(user, redactor)

    def tools(self) -> list[Tool]:
        return [
            Tool(
                "find_students",
                "Look up students the user can see by name. Call this first whenever the "
                "instruction mentions a student, to get their id.",
                obj({"name": {**STR, "description": "First name, surname or both."}}),
                self.find_students,
            ),
            Tool(
                "find_lessons",
                "List upcoming planned lessons the user can see (next 90 days), optionally "
                "for one student, on one weekday or in one subject. Call this before "
                "proposing a change to a lesson.",
                obj(
                    {
                        "student_id": {**STR, "description": 'From find_students, or "".'},
                        "weekday": {"type": "string", "enum": ["", *WEEKDAYS]},
                        "subject": {**STR, "description": 'Subject name, or "".'},
                        "from_date": {**STR, "description": 'YYYY-MM-DD, or "" for today.'},
                    }
                ),
                self.find_lessons,
            ),
            Tool(
                "propose_reschedule",
                "Propose moving a lesson to a new start (the user confirms it later). Use "
                'scope "following" when the user says from a date onwards or every week.',
                obj(
                    {
                        "lesson_id": STR,
                        "new_start": {
                            **STR,
                            "description": "Local date and time, YYYY-MM-DDTHH:MM.",
                        },
                        "scope": {"type": "string", "enum": ["this", "following"]},
                    }
                ),
                self.propose_reschedule,
            ),
            Tool(
                "propose_task",
                "Propose a to-do task for the user (a reminder, a call to make).",
                obj(
                    {
                        "title": STR,
                        "due_date": {**STR, "description": 'YYYY-MM-DD, or "".'},
                        "notes": STR,
                    }
                ),
                self.propose_task,
            ),
            Tool(
                "search_tutors",
                "Open a tutor search with filters (subject, level, online or in person, "
                "postcode, day and time window). Use for requests to find a tutor.",
                obj(
                    {
                        "subject": STR,
                        "level": STR,
                        "mode": {"type": "string", "enum": ["online", "in_person", "either"]},
                        "postcode": STR,
                        "weekday": {"type": "string", "enum": ["", *WEEKDAYS]},
                        "after_time": {**STR, "description": 'HH:MM, or "".'},
                        "before_time": {**STR, "description": 'HH:MM, or "".'},
                    }
                ),
                self.search_tutors,
            ),
        ]

    # reads

    def find_students(self, name: str) -> dict[str, Any]:
        from tutortrack.people.models import Student

        terms = [t for t in str(name).split() if t][:3]
        if not terms:
            return {"students": []}
        qs = scope_queryset(self.user, Student.objects.all(), "people.student.view")
        for term in terms:
            qs = qs.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term))
        out = []
        for student in qs.select_related("client")[:8]:
            self.redactor.person(
                student.full_name,
                kind="STUDENT",
                first_name=student.first_name,
                last_name=student.last_name,
            )
            out.append({"id": str(student.pk), "name": student.full_name})
        return {"students": out}

    def find_lessons(
        self, student_id: str = "", weekday: str = "", subject: str = "", from_date: str = ""
    ) -> dict[str, Any]:
        from tutortrack.scheduling.models import Lesson

        zone = _zone()
        start = now()
        if from_date:
            day = date.fromisoformat(from_date)
            start = max(start, datetime(day.year, day.month, day.day, tzinfo=zone))
        qs = scope_queryset(self.user, Lesson.objects.all(), "scheduling.lesson.view").filter(
            status=Lesson.Status.PLANNED,
            start__gte=start,
            start__lt=start + timedelta(days=LOOKAHEAD_DAYS),
        )
        if student_id:
            qs = qs.filter(attendees__student_id=student_id)
        if subject:
            qs = qs.filter(
                Q(service__subject__name__icontains=subject) | Q(title__icontains=subject)
            )
        rows = []
        for lesson in qs.select_related("service").order_by("start").distinct()[:200]:
            local = lesson.start.astimezone(ZoneInfo(lesson.timezone))
            if weekday and WEEKDAYS[local.weekday()] != weekday:
                continue
            rows.append(
                {
                    "id": str(lesson.pk),
                    "title": lesson.title,
                    "start": local.strftime("%Y-%m-%dT%H:%M"),
                    "weekday": WEEKDAYS[local.weekday()],
                    "minutes": int((lesson.end - lesson.start).total_seconds() // 60),
                    "in_series": lesson.series_id is not None,
                }
            )
            if len(rows) >= 10:
                break
        return {"lessons": rows}

    # proposals

    def _propose(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        from . import services

        proposal = services.propose(self.user, action=action, params=params, feature=self.feature)
        self.proposals.append(proposal)
        return {
            "proposal": len(self.proposals),
            "summary": proposal.summary,
            "status": "waiting for the user to confirm",
        }

    def propose_reschedule(self, lesson_id: str, new_start: str, scope: str) -> dict[str, Any]:
        datetime.fromisoformat(new_start)  # ValueError -> is_error result
        return self._propose(
            "reschedule_lesson", {"lesson_id": lesson_id, "new_start": new_start, "scope": scope}
        )

    def propose_task(self, title: str, due_date: str = "", notes: str = "") -> dict[str, Any]:
        return self._propose("create_task", {"title": title, "due_date": due_date, "notes": notes})

    # filters

    def search_tutors(
        self,
        subject: str,
        level: str = "",
        mode: str = "either",
        postcode: str = "",
        weekday: str = "",
        after_time: str = "",
        before_time: str = "",
    ) -> dict[str, Any]:
        from tutortrack.catalogue.models import Level, Subject

        if not has_perm(self.user, "matching.search"):
            return {"error": _("You can't search for tutors.")}
        subject_row = Subject.objects.filter(name__icontains=subject).first() if subject else None
        level_row = Level.objects.filter(name__icontains=level).first() if level else None
        criteria: dict[str, Any] = {
            "subject": str(subject_row.pk) if subject_row else None,
            "subject_name": subject_row.name if subject_row else subject,
            "level": str(level_row.pk) if level_row else None,
            "level_name": level_row.name if level_row else level,
            "mode": mode if mode in ("online", "in_person", "either") else "either",
            "postcode": postcode.strip().upper()[:10],
            "weekday": weekday,
            "after_time": after_time,
            "before_time": before_time,
        }
        self.searches.append(criteria)
        return {"search": len(self.searches), "status": "the user can open this search"}


# --- copilot ----------------------------------------------------------------------------------

NAME_COLUMNS = {"client": "CLIENT", "tutor": "TUTOR", "student": "STUDENT", "owner": "STAFF"}
NAME_GROUPS = {
    "client": "CLIENT",
    "tutor": "TUTOR",
    "student": "STUDENT",
    "owner": "STAFF",
    "referrer": "CLIENT",  # G5 referral report
    "affiliate": "PERSON",  # G5 affiliate report
}


def report_link(key: str, query: dict[str, Any]) -> str:
    return f"/analytics/{key}?{urlencode(query)}"


class CopilotToolBox(BaseToolBox):
    feature = "copilot"

    def __init__(self, user: Any, redactor: Redactor) -> None:
        self.citations: list[dict[str, Any]] = []
        super().__init__(user, redactor)

    def tools(self) -> list[Tool]:
        from tutortrack.reporting.periods import PRESETS

        return [
            Tool(
                "list_reports",
                "List the standard reports this user may run, with their groupings and "
                "whether a date range applies. Call this first.",
                obj({}),
                self.list_reports,
            ),
            Tool(
                "run_report",
                "Run one standard report and get its columns, rows (first 25) and totals. "
                'Use period presets where possible; "custom" needs from and to dates.',
                obj(
                    {
                        "report": STR,
                        "period": {"type": "string", "enum": [*PRESETS, "custom"]},
                        "from_date": {**STR, "description": 'YYYY-MM-DD for custom, else "".'},
                        "to_date": {**STR, "description": 'YYYY-MM-DD for custom, else "".'},
                        "group_by": {
                            **STR,
                            "description": 'One of the report\'s groupings, or "".',
                        },
                        "ordering": {
                            **STR,
                            "description": 'Column key, "-key" for descending, or "".',
                        },
                    }
                ),
                self.run_report,
            ),
        ]

    def list_reports(self) -> dict[str, Any]:
        from tutortrack.reporting import reports

        return {"reports": [r.describe() for r in reports.available(self.user)]}

    def _register_names(self, result: Any, group_by: str) -> None:
        group_kind = NAME_GROUPS.get(group_by)
        for row in result.rows:
            for key, kind in NAME_COLUMNS.items():
                if isinstance(row.get(key), str):
                    self.redactor.person(row[key], kind=kind)
            if group_kind and isinstance(row.get("group"), str):
                self.redactor.person(row["group"], kind=group_kind)

    def run_report(
        self,
        report: str,
        period: str = "this_month",
        from_date: str = "",
        to_date: str = "",
        group_by: str = "",
        ordering: str = "",
    ) -> dict[str, Any]:
        from tutortrack.reporting import reports

        data: dict[str, Any] = {"period": period}
        if from_date:
            data["from"] = from_date
        if to_date:
            data["to"] = to_date
        if group_by:
            data["group_by"] = group_by
        if ordering:
            data["ordering"] = ordering
        definition, params, result = reports.run(report, self.user, data)
        self._register_names(result, params.group_by)
        query = params.as_query()
        citation = {
            "index": len(self.citations) + 1,
            "report": definition.key,
            "title": str(definition.title),
            "period": params.period.as_dict(),
            "params": query,
            "link": report_link(definition.key, query),
        }
        self.citations.append(citation)
        return {
            "citation": citation["index"],
            "report": definition.key,
            "title": citation["title"],
            "period": citation["period"],
            "group_by": params.group_by,
            "columns": [c.as_dict() for c in result.columns],
            "rows": result.rows[:MAX_ROWS],
            "total_rows": len(result.rows),
            "totals": result.totals or [],
            "notes": [str(n) for n in result.notes],
        }
