"""Sales and onboarding built-in workflows (E33 T06): enquiry follow-up, the stage time
limits, the trial lesson follow-up and welcoming a new family.

The first two replace ``EnquiryFollowUpWorkflow``. Each stage's time limit stays on the
pipeline stage (Leads > Pipeline); the workflows wait for it. A sequence has one start, so
the follow-up covers the first stage and the time limits start again each time an enquiry
moves on (the move stops the run for the stage it left).
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_noop as N_

from tutortrack.automations.builtin_workflows import builtin_workflow

ENQUIRY_STOPS = ["enquiry.stage_changed", "enquiry.won", "enquiry.lost"]
NOT_IMPORTED = {"field": "event.data.source", "op": "not_equals", "value": "import"}
HAS_TIME_LIMIT = {"predicate": "enquiry.stage_has_time_limit"}


def _setting(key: str) -> Any:
    from tutortrack.tenancy.settings_service import get_setting

    return get_setting(key)


def _action(key: str, config: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {"type": "action", "action": key, "config": config or {}, **extra}


def _time_limit() -> list[dict[str, Any]]:
    wait = {"type": "wait", "until": "enquiry.stage_deadline", "offset_hours": 0}
    return [wait, _action("flag_enquiry_waiting", only_if=HAS_TIME_LIMIT)]


# --- enquiry follow-up -----------------------------------------------------------------------


def _follow_up(thank: bool = True) -> dict[str, Any]:
    steps = [_action("thank_for_enquiry")] if thank else []
    return {
        "trigger_type": "event",
        "trigger_config": {"event": "enquiry.received"},
        "conditions": NOT_IMPORTED,  # imported leads: no thank-you or time limit (E28)
        "steps": [*steps, _action("tell_enquiry_owner"), *_time_limit()],
        "stop_when": ENQUIRY_STOPS,
    }


def follow_up_from_settings() -> dict[str, Any]:
    """``leads.acknowledge`` (off: no thank-you to the family)."""
    return _follow_up(bool(_setting("leads.acknowledge")))


@builtin_workflow(
    "enquiry_follow_up", "sales",
    name=N_("Enquiry follow-up"),
    description=N_("When an enquiry arrives, thank the family and tell whoever looks after "
                   "it; if it is still in its first stage when the stage's time limit is "
                   "up, flag it and tell staff."),
    first_version=follow_up_from_settings,
    off_means=N_("Families aren't thanked automatically and enquiries aren't flagged when "
                 "they wait too long."),
)  # fmt: skip
def enquiry_follow_up() -> dict[str, Any]:
    return _follow_up()


@builtin_workflow(
    "enquiry_stage_limits", "sales",
    name=N_("Enquiry stage time limits"),
    description=N_("Each time an enquiry moves to a stage with a time limit, flag it and "
                   "tell staff if it is still there when the time is up."),
    max_runs_per_record=50,
    off_means=N_("Enquiries aren't flagged when they wait too long in a later stage."),
)  # fmt: skip
def enquiry_stage_limits() -> dict[str, Any]:
    return {
        "trigger_type": "event",
        "trigger_config": {"event": "enquiry.stage_changed"},
        "conditions": HAS_TIME_LIMIT,
        "steps": _time_limit(),
        "stop_when": ENQUIRY_STOPS,
    }


# --- trial lesson follow-up ------------------------------------------------------------------


def _trial(hours: int = 24) -> dict[str, Any]:
    return {
        "trigger_type": "event",
        "trigger_config": {"event": "lesson.completed"},
        "conditions": {"predicate": "lesson.trial"},
        "steps": [{"type": "wait", "hours": hours}, _action("ask_trial_outcome")],
    }


def trial_from_settings() -> dict[str, Any]:
    """``leads.trial_follow_up_hours``."""
    return _trial(int(_setting("leads.trial_follow_up_hours")))


@builtin_workflow(
    "trial_follow_up", "sales",
    name=N_("Trial lesson follow-up"),
    description=N_("A day after a trial lesson, remind staff to record how it went, unless "
                   "they already have."),
    first_version=trial_from_settings,
    off_means=N_("Nobody is reminded to record trial outcomes: check open enquiries."),
)  # fmt: skip
def trial_follow_up() -> dict[str, Any]:
    return _trial()


# --- welcome a new family --------------------------------------------------------------------

WELCOME = (
    "Hello {{ recipient.first_name }},\n\nWelcome, and thank you for choosing us. "
    "You'll find upcoming lessons, lesson reports and invoices in the client portal. "
    "Reply to this email if there's anything we can help with."
)


@builtin_workflow(
    "welcome_family", "sales",
    name=N_("Welcome a new family"),
    description=N_("When an enquiry is won, send the family a welcome message; two weeks "
                   "later, give whoever looks after it a task to check in."),
    enabled=False,
    off_means=N_("New families aren't sent a welcome message."),
)  # fmt: skip
def welcome_family() -> dict[str, Any]:
    message = {"to": ["client"], "channels": ["email"], "subject": "Welcome", "body": WELCOME}
    task = {"title": "Check in with {{ enquiry.client.name }}: how are the first lessons?",
            "assignee": "owner", "due_in_hours": 48}  # fmt: skip
    return {
        "trigger_type": "event",
        "trigger_config": {"event": "enquiry.won"},
        "steps": [
            _action("send_message", message),
            {"type": "wait", "days": 14},
            _action("create_task", task),
        ],
    }
