"""Dev seed for E30 Part 2: the setup checklist ticked from the demo data, and one answered
support conversation for the platform console's inbox."""

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step


@seed_step(order=96)
def success_demo(ctx: SeedContext) -> None:
    from tutortrack.success import services
    from tutortrack.success.models import SupportConversation

    with tenant_context(ctx.organisation):
        services.checklist()
        if ctx.admin is None or SupportConversation.objects.exists():
            return
        services.open_conversation(
            ctx.admin,
            subject="Invoice runs",
            body="How do I invoice every family at the end of the month?",
            page="/billing",
        )
    ctx.log("success: setup checklist and a support conversation")
