from decimal import Decimal

import factory

from tutortrack.catalogue.models import Level, Location, Product, Service, Subject, TaxRate
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


class ProductFactory(TenantFactory):
    class Meta:
        model = Product

    name = factory.Sequence(lambda n: f"Fee {n}")
    currency = "GBP"
    price_amount = Decimal("25")
