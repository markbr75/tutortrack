"""Lesson communications built-in workflows (E33 T05): lesson reminders, report chasing and
escalation, the lesson feedback request and the unconfirmed lesson chaser.

Each organisation's first version comes from the settings these replace (the lesson
reminder's timing on the notification setting, and the ``delivery`` report, feedback and
unconfirmed-lesson hours), so nothing changes on the day they ship.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_noop as N_

from tutortrack.automations.builtin_workflows import builtin_workflow

STILL_PLANNED = {"predicate": "lesson.still_planned"}
DEFAULT_REMINDER_MINUTES = [24 * 60, 120]  # comms' lesson_reminder default timing


def _setting(key: str) -> Any:
    from tutortrack.tenancy.settings_service import get_setting

    return get_setting(key)


def _action(key: str) -> dict[str, Any]:
    return {"type": "action", "action": key, "config": {}}


# --- lesson reminders ------------------------------------------------------------------------


def _reminders(minutes_before: list[int]) -> dict[str, Any]:
    before = sorted({int(m) for m in minutes_before}, reverse=True)
    trigger = {"subject": "lesson", "field": "start", "minutes": [-m for m in before]}
    return {
        "trigger_type": "date",
        "trigger_config": trigger,
        "conditions": STILL_PLANNED,
        "steps": [_action("send_lesson_reminder")],
    }


def reminders_from_settings() -> dict[str, Any]:
    """The lesson reminder notification's timing (minutes before) and whether it is on."""
    from tutortrack.comms import services as comms

    setting = comms.effective("lesson_reminder")
    return _reminders(list(setting.timing) or DEFAULT_REMINDER_MINUTES) | {
        "enabled": setting.enabled
    }


@builtin_workflow(
    "lesson_reminders", "lessons",
    name=N_("Lesson reminders"),
    description=N_("Remind families and tutors before each lesson: 24 hours and 2 hours "
                   "before it starts. Who gets it, and by email or text, is set in "
                   "Notifications."),
    first_version=reminders_from_settings, max_runs_per_record=6,
    off_means=N_("Nobody is reminded about lessons."),
)  # fmt: skip
def lesson_reminders() -> dict[str, Any]:
    return _reminders(DEFAULT_REMINDER_MINUTES)


# --- report chasing --------------------------------------------------------------------------


def _report_chasing(remind_hours: int = 4, escalate_hours: int = 24) -> dict[str, Any]:
    def at(hours: int) -> dict[str, Any]:
        return {"type": "wait", "until": "lesson_report.due_at", "offset_hours": hours}

    steps = [at(-remind_hours), _action("remind_report_due")] if remind_hours else []
    steps += [at(0), _action("report_overdue"), at(escalate_hours), _action("escalate_report")]
    return {
        "trigger_type": "event",
        "trigger_config": {"event": "lesson_report.requested"},
        "steps": steps,
        "stop_when": ["lesson_report.submitted"],
    }


def report_chasing_from_settings() -> dict[str, Any]:
    """``delivery.report_reminder_hours`` (before the deadline) and
    ``report_escalate_hours`` (after it). The deadline itself stays a setting."""
    return _report_chasing(
        int(_setting("delivery.report_reminder_hours")),
        int(_setting("delivery.report_escalate_hours")),
    )


@builtin_workflow(
    "report_chasing", "lessons",
    name=N_("Lesson report chasing"),
    description=N_("Remind the tutor before the report is due, mark it overdue at the "
                   "deadline and escalate to staff a day later, until it is written."),
    first_version=report_chasing_from_settings,
    off_means=N_("Tutors aren't chased for reports: check Reports for overdue ones."),
)  # fmt: skip
def report_chasing() -> dict[str, Any]:
    return _report_chasing()


# --- lesson feedback request -----------------------------------------------------------------


def _feedback(delay_hours: int = 2, expiry_days: int = 7) -> dict[str, Any]:
    send = [{"type": "wait", "hours": delay_hours}] if delay_hours else []
    expire = [{"type": "wait", "days": expiry_days}, _action("expire_feedback")]
    return {
        "trigger_type": "event",
        "trigger_config": {"event": "lesson.completed"},
        "steps": [*send, _action("send_feedback_survey"), *expire],
    }


def feedback_from_settings() -> dict[str, Any]:
    """``delivery.feedback_enabled`` (off: switched off), ``feedback_delay_hours`` and
    ``feedback_expiry_days``."""
    return _feedback(
        int(_setting("delivery.feedback_delay_hours")),
        int(_setting("delivery.feedback_expiry_days")),
    ) | {"enabled": bool(_setting("delivery.feedback_enabled"))}


@builtin_workflow(
    "lesson_feedback", "lessons",
    name=N_("Lesson feedback request"),
    description=N_("Two hours after a lesson, ask the family to rate it; close the links "
                   "nobody answered after a week."),
    first_version=feedback_from_settings, enabled=False,
    off_means=N_("Families aren't asked to rate lessons."),
)  # fmt: skip
def lesson_feedback() -> dict[str, Any]:
    return _feedback()


# --- unconfirmed lesson chaser ---------------------------------------------------------------


def _unconfirmed(after_hours: int = 24) -> dict[str, Any]:
    trigger = {"subject": "lesson", "field": "end", "minutes": [after_hours * 60],
               "catch_up_minutes": 6 * 60}  # fmt: skip
    return {
        "trigger_type": "date",
        "trigger_config": trigger,
        "conditions": STILL_PLANNED,
        "steps": [_action("handle_unconfirmed")],
    }


def unconfirmed_from_settings() -> dict[str, Any]:
    """``delivery.unconfirmed_after_hours``; what then happens stays a setting
    (``delivery.unconfirmed_action``: complete automatically or flag)."""
    return _unconfirmed(int(_setting("delivery.unconfirmed_after_hours")))


@builtin_workflow(
    "unconfirmed_lessons", "lessons",
    name=N_("Unconfirmed lesson chaser"),
    description=N_("A day after a lesson that nobody marked, complete it automatically or "
                   "flag it and nudge the tutor (your setting)."),
    first_version=unconfirmed_from_settings,
    off_means=N_("Unmarked lessons stay as they are: Home lists them to mark."),
)  # fmt: skip
def unconfirmed_lessons() -> dict[str, Any]:
    return _unconfirmed()
