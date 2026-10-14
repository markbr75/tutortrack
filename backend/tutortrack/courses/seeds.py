"""Demo courses (E20): an academic year, this term with half term, an 11+ course and an
open Saturday class taught by the first tutor."""

from datetime import date, time, timedelta
from decimal import Decimal

from tutortrack.core.context import tenant_context
from tutortrack.core.money import Money
from tutortrack.core.seeding import SeedContext, seed_step
from tutortrack.core.time import now

CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


@seed_step(order=75)
def courses_demo(ctx: SeedContext) -> None:
    from tutortrack.catalogue.models import Service
    from tutortrack.courses import services
    from tutortrack.courses.models import Course, Term
    from tutortrack.people.models import TutorProfile

    with tenant_context(ctx.organisation):
        if Course.objects.exists():
            return
        service = Service.objects.filter(format="class", active=True).first()
        tutor = TutorProfile.objects.filter(status=TutorProfile.Status.ACTIVE).first()
        if service is None or tutor is None:
            return
        today = now().date()
        start_year = today.year if today.month >= 9 else today.year - 1
        year = services.save_academic_year(
            None,
            name=f"{start_year}/{str(start_year + 1)[-2:]}",
            start_date=date(start_year, 9, 1),
            end_date=date(start_year + 1, 8, 31),
        )
        term_start = max(today - timedelta(days=14), year.start_date)
        term_end = min(term_start + timedelta(weeks=12) - timedelta(days=1), year.end_date)
        if Term.objects.filter(start_date__lte=term_end, end_date__gte=term_start).exists():
            return
        half_term = term_start + timedelta(weeks=6)
        term = services.save_term(
            None,
            academic_year=year,
            name="This term",
            start_date=term_start,
            end_date=term_end,
            breaks=[
                {
                    "name": "Half term",
                    "start_date": half_term,
                    "end_date": half_term + timedelta(days=6),
                }
            ],
        )
        course = services.save_course(
            None,
            name="Year 6 11+ Prep",
            service=service,
            public_description="Verbal and non-verbal reasoning, maths and English for the 11+.",
            price=Money(Decimal("180.00"), service.currency),
            default_capacity=min(8, service.max_students),
            year_groups=["Year 5", "Year 6"],
            is_public=True,
        )
        saturday = term_start + timedelta(days=(5 - term_start.weekday()) % 7)
        services.create_class(
            course=course,
            term=term,
            name="Saturday 10am",
            start_time=time(10),
            duration_minutes=90 if service.default_duration_minutes != 60 else 60,
            rrule=f"FREQ=WEEKLY;BYDAY={CODES[saturday.weekday()]}",
            start_date=saturday,
            teachers=[{"tutor": tutor}],
            status="open",
            conflict_mode="create",
        )
        ctx.log("    created a term, a course and an open class")
