"""Demo tags, notes and tasks (E05)."""

from datetime import timedelta

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step
from tutortrack.core.time import now


@seed_step(order=55)
def crm_demo(ctx: SeedContext) -> None:
    from tutortrack.crm import services
    from tutortrack.crm.models import Tag
    from tutortrack.people.models import Client

    with tenant_context(ctx.organisation):
        if Tag.objects.exists():
            return
        vip = Tag.objects.create(name="VIP", colour="#b45309")
        Tag.objects.create(name="Exam year", colour="#1d4ed8", entity_types=["people.student"])
        client = Client.objects.order_by("created_at").first()
        if client is None:
            return
        services.apply_tag(vip, "people.client", [str(client.pk)])
        services.create_note(
            target_type="people.client",
            target_id=str(client.pk),
            body="<p>Prefers lessons after 4pm on weekdays.</p>",
            pinned=True,
        )
        services.create_task(
            title=f"Call {client.display_name} about GCSE mock results",
            target_type="people.client",
            target_id=str(client.pk),
            assignee=ctx.admin,
            due_at=now() + timedelta(days=2),
        )
