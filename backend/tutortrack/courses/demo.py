"""In-product sample data (FR-02-6): a term (the current one if the organisation has it),
an 11+ course and a Saturday 10:00 class with two sample students enrolled."""

from __future__ import annotations

from datetime import date, time, timedelta

from django.utils.translation import gettext as _

from tutortrack.tenancy.demo import DemoContext, demo_provider

from .models import Term

CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def _term(today: date) -> Term:
    from . import services
    from .models import AcademicYear

    current = Term.objects.filter(start_date__lte=today, end_date__gte=today).first()
    if current is not None:
        return current
    year = AcademicYear.objects.filter(start_date__lte=today, end_date__gte=today).first()
    if year is None:
        start_year = today.year if today.month >= 9 else today.year - 1
        year = services.save_academic_year(
            None,
            name=_("%(start)s/%(end)s (sample)")
            % {"start": start_year, "end": str(start_year + 1)[-2:]},
            start_date=date(start_year, 9, 1),
            end_date=date(start_year + 1, 8, 31),
        )
    start = max(today - timedelta(days=14), year.start_date)
    end = min(start + timedelta(weeks=10) - timedelta(days=1), year.end_date)
    return services.save_term(
        None, academic_year=year, name=_("Sample term"), start_date=start, end_date=end
    )


@demo_provider(order=75)
def sample_class(ctx: DemoContext) -> None:
    from decimal import Decimal

    from tutortrack.billing.services import org_today
    from tutortrack.core import entitlements
    from tutortrack.core.money import Money
    from tutortrack.scheduling.models import Lesson

    from . import services

    service = ctx.extras.get("services", {}).get("group")
    tutor = ctx.extras.get("tutors", {}).get("Nia")
    students = ctx.extras.get("students", {})
    if service is None or tutor is None or not entitlements.has("courses"):
        return
    today = org_today()
    term = _term(today)
    course = services.save_course(
        None,
        name=_("Year 6 11+ Prep (sample)"),
        service=service,
        public_description=_("Verbal and non-verbal reasoning, maths and English for the 11+."),
        price=Money(Decimal("180.00"), service.currency),
        default_capacity=8,
        year_groups=["Year 5", "Year 6", "Year 7"],
    )
    saturday = today + timedelta(days=(5 - today.weekday()) % 7)
    group_class, _skipped = services.create_class(
        course=course,
        term=term,
        name=_("Saturday 10:00"),
        start_time=time(10),
        duration_minutes=90,
        rrule=f"FREQ=WEEKLY;BYDAY={CODES[saturday.weekday()]}",
        start_date=saturday,
        teachers=[{"tutor": tutor}],
        status="open",
        conflict_mode="create",
    )
    for name in ("Maya", "Arjun"):
        if name in students:
            services.enrol(
                group_class,
                students[name],
                check_eligibility=False,
                with_fees=False,
                override_capacity=True,
            )
    ctx.track_all(Lesson.objects.filter(class_session__group_class=group_class))
    ctx.extras["group_class"] = group_class
