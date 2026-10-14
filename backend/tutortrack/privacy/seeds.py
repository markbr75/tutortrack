"""Demo privacy data (E29 Part 2): retention policies and one open data request, so the
Privacy centre has something to show. Safeguarding cases are never seeded."""

from __future__ import annotations

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step


@seed_step(order=85)
def privacy_demo(ctx: SeedContext) -> None:
    from django.db import transaction

    from tutortrack.people.models import Contact

    from . import dsar, retention
    from .models import DataSubjectRequest

    with tenant_context(ctx.organisation), transaction.atomic():
        retention.ensure_policies()
        if DataSubjectRequest.objects.exists():
            return
        contact = Contact.objects.exclude(email="").order_by("created_at").first()
        if contact is None:
            return
        dsar.log_request(
            kind="access",
            subject_type="people.contact",
            subject_id=str(contact.pk),
            requester_name=contact.full_name,
            requester_email=contact.email,
            channel=DataSubjectRequest.Channel.EMAIL,
            details="Please send me a copy of the information you hold about my family.",
        )
        ctx.log("    a data request to verify")
