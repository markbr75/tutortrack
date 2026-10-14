"""In-product sample data (FR-02-6, FR-27-6): two services with charge and pay rates."""

from __future__ import annotations

from decimal import Decimal

from django.utils.translation import gettext as _

from tutortrack.core.money import Money
from tutortrack.tenancy.demo import DemoContext, demo_provider


@demo_provider(order=40)
def sample_services(ctx: DemoContext) -> None:
    from . import services

    currency = str(ctx.organisation.default_currency or "GBP")
    one_to_one = services.create_service(
        name=_("GCSE Maths 1:1 (sample)"),
        charge_rate=Money(Decimal("45.00"), currency),
        pay_rate=Money(Decimal("28.00"), currency),
        default_duration_minutes=60,
        allowed_durations=[60],
    )
    group = services.create_service(
        name=_("11+ group class (sample)"),
        format="class",
        max_students=8,
        pricing_unit="per_student_per_lesson",
        default_duration_minutes=90,
        charge_rate=Money(Decimal("20.00"), currency),
        pay_rate=Money(Decimal("35.00"), currency),
        pay_unit="per_lesson",
    )
    ctx.extras["services"] = {"one_to_one": one_to_one, "group": group}
