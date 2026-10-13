from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import factory

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.tests.factories import TenantFactory
from tutortrack.courses.models import AcademicYear, Course, Term, TermBreak


class AcademicYearFactory(TenantFactory):
    class Meta:
        model = AcademicYear

    name = factory.Sequence(lambda n: f"Year {2026 + n}")
    start_date = factory.LazyFunction(lambda: date.today() - timedelta(days=200))
    end_date = factory.LazyFunction(lambda: date.today() + timedelta(days=400))


class TermFactory(TenantFactory):
    class Meta:
        model = Term

    academic_year = factory.SubFactory(
        AcademicYearFactory, organisation=factory.SelfAttribute("..organisation")
    )
    name = factory.Sequence(lambda n: f"Term {n}")
    start_date = factory.LazyFunction(lambda: date.today() + timedelta(days=1))
    end_date = factory.LazyFunction(lambda: date.today() + timedelta(days=60))


class TermBreakFactory(TenantFactory):
    class Meta:
        model = TermBreak

    term = factory.SubFactory(TermFactory, organisation=factory.SelfAttribute("..organisation"))
    name = "Half term"
    start_date = factory.LazyAttribute(lambda o: o.term.start_date + timedelta(days=14))
    end_date = factory.LazyAttribute(lambda o: o.term.start_date + timedelta(days=20))


class CourseFactory(TenantFactory):
    class Meta:
        model = Course

    name = factory.Sequence(lambda n: f"Course {n}")
    service = factory.SubFactory(
        ServiceFactory,
        organisation=factory.SelfAttribute("..organisation"),
        format="class",
        max_students=12,
        pricing_unit="per_lesson",
        pay_unit="per_lesson",
        charge_rate_amount=Decimal("15"),
        pay_rate_amount=Decimal("30"),
    )
    currency = "GBP"
    price_amount = Decimal("120.00")
    pricing_model = Course.PricingModel.PER_TERM
    default_capacity = 8
    is_public = True
