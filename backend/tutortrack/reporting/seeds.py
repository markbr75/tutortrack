"""Dev seed (E26): exchange rates and the fact tables for the seeded data."""

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step


@seed_step(order=990)
def reporting_facts(ctx: SeedContext) -> None:
    from . import facts, fx

    fx.fetch_latest(fx.FakeProvider())
    with tenant_context(ctx.organisation):
        counts = facts.rebuild()
    ctx.log(f"Reporting facts rebuilt: {counts}")
