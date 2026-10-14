"""Actions the AI may *propose* (command bar, enquiry triage, inbox routing) and that a
person then confirms (FR-31-5, human in the loop).

Each action is whitelisted here with the permission it needs. ``describe`` validates the
parameters and the person's access when the proposal is made (so the AI only proposes
what the person could do); ``execute`` runs it through the owning app's services after
confirmation, checking access again. Nothing here writes another app's models directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from tutortrack.core.permissions import has_perm, scope_queryset


@dataclass(frozen=True)
class Action:
    key: str
    permission: str
    describe: Callable[[Any, dict[str, Any]], str]
    execute: Callable[[Any, dict[str, Any]], dict[str, Any]]


ACTIONS: dict[str, Action] = {}


def _register(action: Action) -> Action:
    ACTIONS[action.key] = action
    return action


def _invalid(message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message)


def _scoped(user: Any, model: Any, codename: str, pk: Any) -> Any:
    try:
        obj = scope_queryset(user, model.objects.all(), codename).filter(pk=pk).first()
    except (ValueError, TypeError):
        obj = None
    if obj is None:
        raise NotFound(_("Record not found, or you can't change it."))
    return obj


# --- reschedule a lesson (or it and the following ones) --------------------------------------


def _lesson_change(user: Any, params: dict[str, Any]) -> tuple[Any, datetime, str]:
    from tutortrack.scheduling.models import Lesson

    lesson = _scoped(user, Lesson, "scheduling.lesson.edit", params.get("lesson_id"))
    if lesson.status != Lesson.Status.PLANNED:
        raise _invalid(_("Only planned lessons can be moved."))
    try:
        local = datetime.fromisoformat(str(params.get("new_start")))
    except ValueError as exc:
        raise _invalid(_("Give the new start as a date and time.")) from exc
    zone = ZoneInfo(lesson.timezone)
    start = (local if local.tzinfo else local.replace(tzinfo=zone)).astimezone(ZoneInfo("UTC"))
    scope = str(params.get("scope") or "this")
    if scope not in ("this", "following"):
        raise _invalid(_("Choose this lesson or this and following."))
    if scope == "following" and lesson.series_id is None:
        scope = "this"
    return lesson, start, scope


def _describe_reschedule(user: Any, params: dict[str, Any]) -> str:
    lesson, start, scope = _lesson_change(user, params)
    when = start.astimezone(ZoneInfo(lesson.timezone)).strftime("%a %d %b %Y %H:%M")
    if scope == "following":
        return _("Move %(lesson)s and the following lessons in its series to %(when)s") % {
            "lesson": lesson.title,
            "when": when,
        }
    return _("Move %(lesson)s to %(when)s") % {"lesson": lesson.title, "when": when}


def _execute_reschedule(user: Any, params: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.scheduling import services

    lesson, start, scope = _lesson_change(user, params)
    if scope == "following":
        services.edit_series(
            lesson.series,
            scope="following",
            from_lesson=lesson,
            start_time=start.astimezone(ZoneInfo(lesson.timezone)).time(),
        )
        lesson.refresh_from_db()
    else:
        result = services.update_lesson(
            lesson,
            start=start,
            end=start + (lesson.end - lesson.start),
            can_edit_locked=has_perm(user, "scheduling.edit_locked"),
        )
        lesson = result.lesson
    return {"lesson_id": str(lesson.pk), "start": lesson.start.isoformat()}


_register(
    Action(
        "reschedule_lesson",
        "scheduling.lesson.edit",
        _describe_reschedule,
        _execute_reschedule,
    )
)


# --- create a task -------------------------------------------------------------------------------


def _task_fields(user: Any, params: dict[str, Any]) -> dict[str, Any]:
    if not has_perm(user, "crm.task.create"):
        raise PermissionDenied(_("You can't create tasks."))
    title = str(params.get("title") or "").strip()[:200]
    if not title:
        raise _invalid(_("Give the task a title."))
    fields: dict[str, Any] = {"title": title, "assignee": user}
    if params.get("due_date"):
        try:
            due = date.fromisoformat(str(params["due_date"]))
        except ValueError as exc:
            raise _invalid(_("Use a date like 2026-10-31.")) from exc
        from tutortrack.reporting.periods import org_timezone

        fields["due_at"] = datetime(
            due.year, due.month, due.day, 9, tzinfo=ZoneInfo(org_timezone())
        )
    if params.get("notes"):
        fields["description"] = str(params["notes"])[:2000]
    return fields


def _describe_task(user: Any, params: dict[str, Any]) -> str:
    fields = _task_fields(user, params)
    if "due_at" in fields:
        return _("Create a task for you: %(title)s (due %(due)s)") % {
            "title": fields["title"],
            "due": fields["due_at"].strftime("%a %d %b"),
        }
    return _("Create a task for you: %(title)s") % {"title": fields["title"]}


def _execute_task(user: Any, params: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.crm import services

    task = services.create_task(**_task_fields(user, params))
    return {"task_id": str(task.pk)}


_register(Action("create_task", "crm.task.create", _describe_task, _execute_task))


# --- update an enquiry from triage ----------------------------------------------------------------

ENQUIRY_FIELDS = ("priority", "subjects", "expected_start", "notes_append")


def _enquiry_changes(user: Any, params: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    from tutortrack.leads.models import Enquiry

    enquiry = _scoped(user, Enquiry, "leads.enquiry.edit", params.get("enquiry_id"))
    changes: dict[str, Any] = {}
    if params.get("priority"):
        if params["priority"] not in Enquiry.Priority.values:
            raise _invalid(_("Unknown priority."))
        changes["priority"] = params["priority"]
    if params.get("subjects"):
        changes["subjects"] = [
            {"subject": str(s.get("subject", ""))[:100], "level": str(s.get("level", ""))[:100]}
            for s in params["subjects"]
            if isinstance(s, dict) and s.get("subject")
        ][:10]
    if params.get("expected_start"):
        try:
            changes["expected_start"] = date.fromisoformat(str(params["expected_start"]))
        except ValueError as exc:
            raise _invalid(_("Use a date like 2026-10-31.")) from exc
    if params.get("notes_append"):
        extra = str(params["notes_append"]).strip()[:2000]
        changes["notes"] = f"{enquiry.notes}\n\n{extra}".strip()
    if not changes:
        raise _invalid(_("Nothing to change."))
    return enquiry, changes


def _describe_enquiry(user: Any, params: dict[str, Any]) -> str:
    enquiry, changes = _enquiry_changes(user, params)
    parts = []
    if "priority" in changes:
        parts.append(_("priority %(p)s") % {"p": changes["priority"]})
    if "subjects" in changes:
        parts.append(
            _("subjects %(s)s")
            % {"s": ", ".join(f"{s['subject']} {s['level']}".strip() for s in changes["subjects"])}
        )
    if "expected_start" in changes:
        parts.append(_("start %(d)s") % {"d": changes["expected_start"].isoformat()})
    if "notes" in changes:
        parts.append(_("add the details to the notes"))
    return _("Update %(enquiry)s: %(changes)s") % {
        "enquiry": enquiry.title,
        "changes": "; ".join(parts),
    }


def _execute_enquiry(user: Any, params: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.leads import services

    enquiry, changes = _enquiry_changes(user, params)
    services.update_enquiry(enquiry, **changes)
    return {"enquiry_id": str(enquiry.pk)}


_register(Action("update_enquiry", "leads.enquiry.edit", _describe_enquiry, _execute_enquiry))


# --- assign an inbox conversation -----------------------------------------------------------------


def _assignment(user: Any, params: dict[str, Any]) -> tuple[Any, Any]:
    from tutortrack.comms.models import Thread
    from tutortrack.identity.models import Membership

    thread = _scoped(user, Thread, "comms.inbox.assign", params.get("thread_id"))
    try:
        membership = (
            Membership.objects.filter(
                user_id=params.get("assignee_id"), status=Membership.Status.ACTIVE
            )
            .select_related("user")
            .first()
        )
    except (ValueError, TypeError):
        membership = None
    if membership is None:
        raise _invalid(_("Choose a team member."))
    return thread, membership.user


def _describe_assignment(user: Any, params: dict[str, Any]) -> str:
    thread, assignee = _assignment(user, params)
    name = assignee.get_full_name() or assignee.email
    return _("Assign “%(subject)s” to %(name)s") % {
        "subject": thread.subject or _("conversation"),
        "name": name,
    }


def _execute_assignment(user: Any, params: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.comms import inbox

    thread, assignee = _assignment(user, params)
    inbox.assign(thread, assignee, by=user)
    return {"thread_id": str(thread.pk), "assignee_id": str(assignee.pk)}


_register(Action("assign_thread", "comms.inbox.assign", _describe_assignment, _execute_assignment))


def get(key: str) -> Action:
    action = ACTIONS.get(key)
    if action is None:
        raise _invalid(_("Unknown action."))
    return action
