"""In-product sample data (FR-02-6): an approved five-star review of a sample tutor."""

from __future__ import annotations

from django.utils.translation import gettext as _

from tutortrack.tenancy.demo import DemoContext, demo_provider


@demo_provider(order=90)
def sample_review(ctx: DemoContext) -> None:
    from . import services
    from .models import Review

    client = ctx.extras.get("clients", {}).get("Patel")
    tutor = ctx.extras.get("tutors", {}).get("Nia")
    if client is None:
        return
    review = services.create_review(
        client=client,
        tutor=tutor,
        rating=5,
        text=_("Arjun's confidence in maths has grown so much this term."),
        reviewer_name="Priya P.",
        publish_consent=True,
        source=Review.Source.STAFF,
    )
    services.moderate(review, action="approve")
