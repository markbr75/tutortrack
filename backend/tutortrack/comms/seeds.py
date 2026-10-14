"""Demo communications data (E13 Phase 2): a saved segment, a draft broadcast, canned
replies and a conversation from the first family in the inbox."""

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step


@seed_step(order=82)
def comms_phase2_demo(ctx: SeedContext) -> None:
    from django.db import transaction

    from tutortrack.comms import broadcasts, inbox
    from tutortrack.comms.models import CannedReply, Segment
    from tutortrack.people.models import Contact

    with tenant_context(ctx.organisation), transaction.atomic():
        if Segment.objects.exists():
            return
        segment = broadcasts.save_segment(
            name="Active families",
            audience="contacts",
            definition={"client_statuses": ["active"], "contacts": "primary"},
            description="The main contact of every active family",
        )
        broadcasts.create_broadcast(
            name="Half-term timetable",
            channel="email",
            purpose="operational",
            subject="Lessons over half term",
            body=(
                "Hello {{ recipient.first_name }},\n\nLessons pause over half term and start "
                "again the following Monday.\n\n{{ organisation.name }}"
            ),
            segment=segment,
        )
        replies = (
            ("Thanks, we'll call you", "Thanks for your message. We'll call you back today."),
            (
                "Tutor confirmed",
                "Good news: your tutor is confirmed. See the lessons in the portal.",
            ),
        )
        for title, body in replies:
            if not CannedReply.objects.filter(title=title).exists():
                inbox.save_canned_reply(title=title, body=body)
        contact = Contact.objects.exclude(email="").select_related("client").first()
        if contact is not None:
            author = inbox.Author("contact", str(contact.pk), contact.full_name)
            inbox.start_from_portal(
                author,
                kind="client",
                subject="Thursday's lesson",
                body="Hi, could we move Thursday's lesson to 5pm this week?",
                client=contact.client,
            )
        ctx.log("    created a segment, a draft broadcast, canned replies and a conversation")
