"""The review request built-in workflow (E33 T06): send the review link, remind once and
close the link if nobody used it. It replaces ``ReviewRequestWorkflow``.

When families are asked (after N lessons with a tutor, after a trial, by staff or from a
workflow's "Ask for a review") stays in Growth > Reviews: it decides per tutor across every
student in a lesson and asks each family about a tutor once, which a sequence on one record
can't express.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_noop as N_

from tutortrack.automations.builtin_workflows import builtin_workflow


def _action(key: str) -> dict[str, Any]:
    return {"type": "action", "action": key, "config": {}}


def _review_request(reminder_days: int = 4) -> dict[str, Any]:
    return {
        "trigger_type": "event",
        "trigger_config": {"event": "review.requested"},
        "steps": [
            _action("send_review_link"),
            {"type": "wait", "days": reminder_days},
            _action("remind_review"),
            {"type": "wait", "until": "review_request.expires_at", "offset_days": 0},
            _action("close_review_request"),
        ],
    }


def review_request_from_settings() -> dict[str, Any]:
    """``growth.review_reminder_days``. How long the link stays open stays a setting
    (``growth.review_expiry_days``): it is on the link the family gets."""
    from tutortrack.tenancy.settings_service import get_setting

    return _review_request(int(get_setting("growth.review_reminder_days")))


@builtin_workflow(
    "review_request", "sales",
    name=N_("Review request"),
    description=N_("When a family is asked for a review, send them the link, remind them "
                   "once after 4 days and close the link when it runs out."),
    first_version=review_request_from_settings,
    can_switch_off=False,
    off_means=N_("Review requests aren't sent."),
)  # fmt: skip
def review_request() -> dict[str, Any]:
    return _review_request()
