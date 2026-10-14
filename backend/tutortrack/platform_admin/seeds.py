"""Dev seed for E30 Part 2: today's health score and subscription snapshot for the demo
organisation, plus five earlier month ends so the SaaS metrics page has a history."""

from decimal import Decimal

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step
from tutortrack.core.time import now


@seed_step(order=97)
def platform_insights_demo(ctx: SeedContext) -> None:
    from tutortrack.platform_admin import insights
    from tutortrack.platform_admin.models import SubscriptionSnapshot
    from tutortrack.platform_admin.selectors import month_ends

    today = now().date()
    with tenant_context(ctx.organisation):
        if SubscriptionSnapshot.objects.exists():
            return
        insights.record_day(today)
        current = SubscriptionSnapshot.objects.get(date=today)
        mrr = current.mrr if current.mrr > 0 else Decimal("49.00")
        for index, end in enumerate(month_ends(6, today)[:-1]):
            SubscriptionSnapshot.objects.create(
                date=end,
                plan_key=current.plan_key or "solo",
                status="trialing" if index == 0 else "active",
                interval="month",
                currency=current.currency or "GBP",
                seats=current.seats,
                mrr=Decimal(0) if index == 0 else mrr,
                signed_up_on=current.signed_up_on,
            )
    ctx.log("platform_admin: health score and subscription snapshots")
