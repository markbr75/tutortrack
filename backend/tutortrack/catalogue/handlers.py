from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe

from .services import seed_catalogue


@subscribe("organisation.created")
def create_starter_catalogue(event: EventEnvelope) -> None:
    """Subjects, levels and tax rates for the organisation's country (FR-06-1)."""
    seed_catalogue()


@subscribe("onboarding.step_completed")
def create_first_service_from_onboarding(event: EventEnvelope) -> None:
    """The wizard's "Your first service" step (FR-02-6) creates the service."""
    if event.data.get("step") != "service" or event.data.get("skipped"):
        return
    from tutortrack.core.money import Money

    from .services import create_first_service

    answers = event.data.get("answers", {})
    price = answers["price"]
    create_first_service(
        subject=answers["subject"],
        level=answers.get("level", ""),
        duration_minutes=int(answers["duration_minutes"]),
        price=Money(price["amount"], price["currency"]),
    )
