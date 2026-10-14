"""What growth plugs into other apps at start-up (E25):

* E24 directory cards show tutors' average rating (when the organisation allows it);
* E14 automations get a "Request a review" action and a trial-lesson recipe.
"""

from __future__ import annotations

from typing import Any

from tutortrack.automations.recipes import RECIPES, Recipe
from tutortrack.automations.registry import Action, ActionField, register_action
from tutortrack.sites import selectors as sites

from . import selectors


def _request_review(ctx: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Subject client, enquiry (trial) or lesson: ask the family for a review."""
    from tutortrack.people.models import Client

    from . import services
    from .models import ReviewRequest

    obj, key = ctx.obj, ctx.subject.key
    trigger = ReviewRequest.Trigger.AUTOMATION
    if key == "enquiry":
        found = selectors.enquiry_people(obj.pk)
        if found is None:
            return {"requested": 0}
        client, tutor, student = found
        made = services.request_review(client=client, tutor=tutor, student=student, trigger=trigger)
        return {"requested": int(made is not None)}
    if key == "lesson":
        tutor_link = obj.tutors.select_related("tutor").first()
        count = 0
        for attendee in obj.attendees.select_related("client", "student"):
            made = services.request_review(
                client=attendee.client,
                tutor=tutor_link.tutor if tutor_link else None,
                student=attendee.student,
                trigger=trigger,
            )
            count += int(made is not None)
        return {"requested": count}
    client = obj if isinstance(obj, Client) else getattr(obj, "client", None)
    if client is None:
        return {"requested": 0}
    made = services.request_review(client=client, trigger=trigger)
    return {"requested": int(made is not None)}


register_action(
    Action(
        "request_review",
        "Ask for a review",
        _request_review,
        lambda ctx, config: "Ask the family for a review",
        (ActionField("note", "Note (not sent)", "text"),),
        subjects=("client", "student", "enquiry", "lesson"),
    )
)

if not any(r.key == "trial_review" for r in RECIPES):
    RECIPES.append(
        Recipe(
            "trial_review",
            "Trial lesson: ask for a review",
            "Two days after a trial lesson, ask the family to review the tutor.",
            "event",
            {"event": "trial_lesson.completed"},
            [
                {"type": "wait", "days": 2},
                {"type": "action", "action": "request_review", "config": {}},
            ],
        )
    )

sites.register_rating_provider(selectors.public_rating)
