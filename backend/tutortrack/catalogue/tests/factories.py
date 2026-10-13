from decimal import Decimal

import factory

from tutortrack.catalogue.models import (
    DiscountRule,
    HolidayCalendar,
    Level,
    Location,
    PayTier,
    PremiumRule,
    PriceList,
    Product,
    PromoCode,
    Room,
    Service,
    Subject,
    TaxRate,
)
from tutortrack.core.tests.factories import TenantFactory


class SubjectFactory(TenantFactory):
    class Meta:
        model = Subject

    name = factory.Sequence(lambda n: f"Subject {n}")


class LevelFactory(TenantFactory):
    class Meta:
        model = Level

    subject = factory.SubFactory(
        SubjectFactory, organisation=factory.SelfAttribute("..organisation")
    )
    name = factory.Sequence(lambda n: f"Level {n}")


class TaxRateFactory(TenantFactory):
    class Meta:
        model = TaxRate

    name = "Standard VAT"
    percent = Decimal("20")


class ServiceFactory(TenantFactory):
    class Meta:
        model = Service

    name = factory.Sequence(lambda n: f"Tuition {n}")
    currency = "GBP"
    charge_rate_amount = Decimal("40")
    pay_rate_amount = Decimal("25")


class LocationFactory(TenantFactory):
    class Meta:
        model = Location

    name = factory.Sequence(lambda n: f"Centre {n}")


class RoomFactory(TenantFactory):
    class Meta:
        model = Room

    location = factory.SubFactory(
        LocationFactory, organisation=factory.SelfAttribute("..organisation")
    )
    name = factory.Sequence(lambda n: f"Room {n}")


class PayTierFactory(TenantFactory):
    class Meta:
        model = PayTier

    name = factory.Sequence(lambda n: f"Tier {n}")


class PremiumRuleFactory(TenantFactory):
    class Meta:
        model = PremiumRule

    name = factory.Sequence(lambda n: f"Premium {n}")
    charge_percent = Decimal("10")


class DiscountRuleFactory(TenantFactory):
    class Meta:
        model = DiscountRule

    name = factory.Sequence(lambda n: f"Discount {n}")
    kind = DiscountRule.Kind.SIBLING
    percent = Decimal("5")


class PromoCodeFactory(TenantFactory):
    class Meta:
        model = PromoCode

    code = factory.Sequence(lambda n: f"CODE{n}")
    discount = factory.SubFactory(
        DiscountRuleFactory,
        organisation=factory.SelfAttribute("..organisation"),
        kind=DiscountRule.Kind.PROMO,
    )


class PriceListFactory(TenantFactory):
    class Meta:
        model = PriceList

    name = factory.Sequence(lambda n: f"Contract {n}")
    currency = "GBP"


class HolidayCalendarFactory(TenantFactory):
    class Meta:
        model = HolidayCalendar

    name = factory.Sequence(lambda n: f"Holidays {n}")
    country = "GB"


class ProductFactory(TenantFactory):
    class Meta:
        model = Product

    name = factory.Sequence(lambda n: f"Fee {n}")
    currency = "GBP"
    price_amount = Decimal("25")
