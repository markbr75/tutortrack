"""Demo catalogue: starter subjects and tax rates, plus a few services and fees (E06)."""

from decimal import Decimal

from tutortrack.core.context import tenant_context
from tutortrack.core.money import Money
from tutortrack.core.seeding import SeedContext, seed_step


@seed_step(order=40)
def catalogue_demo(ctx: SeedContext) -> None:
    from tutortrack.catalogue import services
    from tutortrack.catalogue.models import Level, Service

    with tenant_context(ctx.organisation):
        services.seed_catalogue(ctx.organisation.country)
        if Service.objects.exists():
            return
        gbp = ctx.organisation.default_currency
        gcse = Level.objects.filter(subject__name="Maths", name="GCSE Higher").first()
        services.create_service(
            name="GCSE Maths 1:1",
            subject=gcse.subject if gcse else None,
            level=gcse,
            charge_rate=Money(Decimal("45"), gbp),
            pay_rate=Money(Decimal("28"), gbp),
            allowed_durations=[60, 90],
        )
        services.create_service(
            name="Piano lesson",
            pricing_unit="per_lesson",
            default_duration_minutes=30,
            charge_rate=Money(Decimal("25"), gbp),
            pay_percent=Decimal("60"),
        )
        services.create_service(
            name="11+ group class",
            format="class",
            max_students=8,
            pricing_unit="per_student_per_lesson",
            charge_rate=Money(Decimal("20"), gbp),
            pay_rate=Money(Decimal("35"), gbp),
            pay_unit="per_lesson",
        )
        services.save_location(None, name="Leeds Centre", type="centre", capacity=40)
        services.save_location(None, name="Online", type="online")
        services.save_product(
            None, name="Registration fee", category="registration", price=Money(Decimal("30"), gbp)
        )
        services.save_package(
            None,
            name="10 hours of tuition",
            quantity_type="hours",
            quantity=Decimal("10"),
            price=Money(Decimal("420"), gbp),
            validity_days=180,
        )
        ctx.log("    created demo services, locations, a fee and a package")
