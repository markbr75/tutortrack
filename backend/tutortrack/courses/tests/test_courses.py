"""E20 Group classes, courses and terms: terms and breaks (T01), classes and sessions (T02),
enrolment (T03), class billing (T04), transfers and withdrawals (T05), waitlists (T06),
registers and makeups (T07), rollover (T08), the public catalogue and online enrolment
(T09), plus the API with tenant isolation."""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tutortrack.billing import plans
from tutortrack.billing import services as billing
from tutortrack.billing.models import BillingPlan, Charge, CreditNote, Invoice, PaymentRequest
from tutortrack.catalogue.models import DiscountRule
from tutortrack.catalogue.tests.factories import RoomFactory, ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.courses import selectors, services
from tutortrack.courses.models import (
    ClassSession,
    Course,
    Enrolment,
    GroupClass,
    MakeupBooking,
    RolloverOffer,
    TermRollover,
)
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads import services as leads
from tutortrack.leads.models import WaitlistEntry
from tutortrack.people.tests.factories import StudentFactory, TutorProfileFactory
from tutortrack.portal.tests.test_portal import make_household
from tutortrack.scheduling import services as scheduling
from tutortrack.scheduling.models import Lesson
from tutortrack.tenancy import settings_service

from .factories import AcademicYearFactory, CourseFactory, TermFactory

pytestmark = pytest.mark.django_db

LONDON = ZoneInfo("Europe/London")
CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def today() -> date:
    return now().astimezone(LONDON).date()


def weekly_on(day: date) -> str:
    return f"FREQ=WEEKLY;BYDAY={CODES[day.weekday()]}"


def gbp(value: str) -> Money:
    return Money(value, "GBP")


def events_of(org, kind):
    with tenant_context(org):
        return list(OutboxEvent.objects.filter(event_type=kind).order_by("occurred_at"))


def settings(org, **values):
    with tenant_context(org):
        settings_service.update_settings("courses", {f"courses.{k}": v for k, v in values.items()})


@pytest.fixture
def world(org):
    tutor_membership = MembershipFactory(organisation=org, role="tutor")
    tutor = TutorProfileFactory(
        organisation=org, status="active", first_name="Nia", last_name="Adeyemi",
        membership=tutor_membership,
    )  # fmt: skip
    course = CourseFactory(organisation=org, name="Year 6 11+ Prep")
    year = AcademicYearFactory(organisation=org, name="2026/27")
    admin = MembershipFactory(organisation=org, role="admin")
    family = make_household(org, "The Patels")
    return {
        "tutor": tutor,
        "tutor_api": client_for(org, tutor_membership.user),
        "course": course,
        "year": year,
        "family": family,
        "student": family["students"][0],
        "sibling": family["students"][1],
        "admin": admin.user,
        "admin_api": client_for(org, admin.user),
    }


def make_term(org, world, start: date, weeks: int, breaks=(), name="Autumn"):
    with tenant_context(org):
        return services.save_term(
            None,
            academic_year=world["year"],
            name=name,
            start_date=start,
            end_date=start + timedelta(weeks=weeks) - timedelta(days=1),
            breaks=[{"name": "Half term", "start_date": b0, "end_date": b1} for b0, b1 in breaks],
        )


def make_class(org, world, term, *, first: date | None = None, capacity=8, **kw):
    first = first or term.start_date
    with tenant_context(org):
        group_class, _skipped = services.create_class(
            course=kw.pop("course", world["course"]),
            term=term,
            name=kw.pop("name", "Saturday 10am"),
            start_time=kw.pop("start_time", time(10)),
            duration_minutes=60,
            rrule=weekly_on(first),
            start_date=first,
            capacity=capacity,
            teachers=kw.pop("teachers", [{"tutor": world["tutor"]}]),
            status=kw.pop("status", "open"),
            **kw,
        )
        return GroupClass.objects.select_related("term", "course").get(pk=group_class.pk)


def future_class(org, world, *, weeks=6, breaks=(), **kw):
    """A term starting tomorrow with a weekly class from tomorrow (never today, so session
    times are never 'now')."""
    start = today() + timedelta(days=1)
    term = make_term(org, world, start, weeks, breaks, name=kw.pop("term_name", "Autumn"))
    return make_class(org, world, term, **kw)


def running_class(org, world, **kw):
    """Three weekly sessions in the past and five to come."""
    first = today() + timedelta(days=1) - timedelta(weeks=3)
    term = make_term(org, world, first, 8, name=kw.pop("term_name", "Autumn"))
    return make_class(org, world, term, first=first, **kw)


def session_students(org, session: ClassSession) -> set[str]:
    with tenant_context(org):
        return {
            str(s) for s in Lesson.objects.get(pk=session.lesson_id).attendees.values_list(
                "student_id", flat=True
            )
        }  # fmt: skip


def enrol(org, group_class, student, **kw):
    with tenant_context(org):
        return services.enrol(group_class, student, **kw)


# --- T01 terms and breaks -----------------------------------------------------------------------


def test_breaks_are_skipped_by_class_sessions(org, world):
    start = today() + timedelta(days=1)
    group_class = future_class(
        org, world, weeks=6, breaks=[(start + timedelta(days=14), start + timedelta(days=20))]
    )
    with tenant_context(org):
        rows = list(group_class.sessions.order_by("date").values_list("date", "number"))
    assert len(rows) == 5
    assert start + timedelta(days=14) not in [d for d, _n in rows]
    assert [n for _d, n in rows] == [1, 2, 3, 4, 5]


def test_term_rules(org, world):
    start = today() + timedelta(days=1)
    term = make_term(org, world, start, 4)
    with tenant_context(org), pytest.raises(BusinessRuleViolation, match="overlap"):
        services.save_term(
            None, academic_year=world["year"], name="Clash", start_date=start + timedelta(days=3),
            end_date=start + timedelta(days=40),
        )  # fmt: skip
    with tenant_context(org), pytest.raises(BusinessRuleViolation, match="inside the term"):
        services.save_term(
            term,
            breaks=[{"name": "Out", "start_date": start - timedelta(days=5), "end_date": start}],
        )
    with tenant_context(org), pytest.raises(BusinessRuleViolation, match="academic year"):
        services.save_term(
            None, academic_year=world["year"], name="Far", start_date=start + timedelta(days=900),
            end_date=start + timedelta(days=950),
        )  # fmt: skip


def test_new_breaks_replan_the_sessions(org, world):
    group_class = future_class(org, world, weeks=6)
    start = group_class.start_date
    with tenant_context(org):
        assert group_class.sessions.count() == 6
        services.save_term(
            group_class.term,
            breaks=[{"name": "Half term", "start_date": start + timedelta(days=7),
                     "end_date": start + timedelta(days=13)}],
        )  # fmt: skip
        dates = set(group_class.sessions.values_list("date", flat=True))
        lessons = Lesson.objects.filter(series_id=group_class.series_id).exclude(status="cancelled")
        assert len(dates) == 5 == lessons.count()
        assert start + timedelta(days=7) not in dates


def test_breaks_pause_other_lessons_only_with_the_setting(org, world):
    start = today() + timedelta(days=1)
    make_term(
        org, world, start, 4, breaks=[(start + timedelta(days=7), start + timedelta(days=13))]
    )
    service = ServiceFactory(organisation=org)

    def series():
        with tenant_context(org):
            return scheduling.create_series(
                rrule=weekly_on(start), start_date=start, start_time=time(17), duration_minutes=60,
                service=service, attendees=[{"student": world["student"]}],
                tutors=[{"tutor": world["tutor"]}], until=start + timedelta(days=27),
                conflict_mode="create",
            )  # fmt: skip

    assert len(series().created) == 4
    settings(org, breaks_skip_all_lessons=True)
    with tenant_context(org):
        world["student"].refresh_from_db()
    created = series().created
    assert len(created) == 3
    assert start + timedelta(days=7) not in {lesson.occurrence_date for lesson in created}


def test_termly_billing_plans_follow_term_dates(org, world):
    start = today() + timedelta(days=10)
    autumn = make_term(org, world, start, 10, name="Autumn")
    spring = make_term(org, world, autumn.end_date + timedelta(days=15), 10, name="Spring")
    with tenant_context(org):
        plan = plans.create_plan(
            client=world["family"]["client"], description="Tuition", amount=gbp("300.00"),
            interval="termly", start_date=start + timedelta(days=7),
        )  # fmt: skip
        segments = list(plans.plan_segments(plan))
        assert [(s.period_start, s.period_end) for s in segments] == [
            (autumn.start_date, autumn.end_date),
            (spring.start_date, spring.end_date),
        ]
        first = segments[0]
        assert plans.amount_for(plan.amount, first, prorate=True) == gbp("270.00")
        # Past the last known term an open-ended plan waits for the next one.
        BillingPlan.objects.filter(pk=plan.pk).update(start_date=spring.end_date + timedelta(1))
        plan.refresh_from_db()
        assert plans.next_period(plan.pk, "")["status"] == "paused"


# --- T02 classes and sessions -------------------------------------------------------------------


def test_a_class_runs_on_lessons_with_its_teachers(org, world):
    group_class = future_class(org, world, weeks=4)
    with tenant_context(org):
        sessions = list(group_class.sessions.select_related("lesson").order_by("date"))
        assert len(sessions) == 4
        lesson = sessions[0].lesson
        assert lesson.title == "Year 6 11+ Prep \N{EN DASH} Saturday 10am"
        assert lesson.start.astimezone(LONDON).time() == time(10)
        assert [t.tutor_id for t in lesson.tutors.all()] == [world["tutor"].pk]
        assert lesson.attendees.count() == 0
        assert lesson.series_id == group_class.series_id


def test_capacity_is_limited_by_the_service_and_the_room(org, world):
    start = today() + timedelta(days=1)
    term = make_term(org, world, start, 4)
    with pytest.raises(BusinessRuleViolation, match="at most 12"):
        make_class(org, world, term, capacity=20)
    room = RoomFactory(organisation=org, capacity=4)
    with pytest.raises(BusinessRuleViolation, match="holds 4"):
        make_class(org, world, term, capacity=6, room=room)
    group_class = make_class(org, world, term, capacity=4, room=room)
    with tenant_context(org):
        assert {s.lesson.room_id for s in group_class.sessions.select_related("lesson")} == {
            room.pk
        }


def test_teacher_pay_by_session_headcount_and_fixed_total(org, world):
    group_class = future_class(
        org, world, weeks=3, teacher_pay_mode="headcount",
        teacher_pay={"tiers": [{"from": 0, "amount": "20.00"}, {"from": 2, "amount": "35.00"}]},
    )  # fmt: skip

    def pay():
        with tenant_context(org):
            first = group_class.sessions.order_by("date").first().lesson
            return first.tutors.get().pay_amount

    assert pay() == gbp("20.00")
    enrol(org, group_class, world["student"])
    enrol(org, group_class, world["sibling"])
    assert pay() == gbp("35.00")
    with tenant_context(org):
        services.update_class(
            group_class, teacher_pay_mode="fixed", teacher_pay={"amount": "100.00"}
        )
        amounts = [
            s.lesson.tutors.get().pay_amount.amount
            for s in group_class.sessions.select_related("lesson").order_by("date")
        ]
    assert sum(amounts) == Decimal("100.00")
    assert sorted(amounts) == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]


# --- T03 enrolment ------------------------------------------------------------------------------


def test_a_mid_term_join_attends_future_sessions_only_and_is_prorated(org, world):
    group_class = running_class(org, world)
    enrolment = enrol(org, group_class, world["student"])
    assert enrolment.status == "enrolled"
    assert enrolment.start_date == today()
    with tenant_context(org):
        sessions = list(group_class.sessions.select_related("lesson").order_by("date"))
    past = [s for s in sessions if s.date < today()]
    future = [s for s in sessions if s.date >= today()]
    assert (len(past), len(future)) == (3, 5)
    assert all(str(world["student"].pk) not in session_students(org, s) for s in past)
    assert all(str(world["student"].pk) in session_students(org, s) for s in future)
    # 5 of 8 sessions remain: £120 x 5/8, invoiced straight away.
    assert enrolment.price_snapshot["fee_due"] == {"amount": "75.00", "currency": "GBP"}
    with tenant_context(org):
        charge = Charge.objects.get(source_key=services.fee_key(enrolment))
        assert (charge.kind, charge.gross) == ("course", gbp("75.00"))
        assert charge.invoice.status == Invoice.Status.ISSUED
        # Term-billed sessions cost nothing on their own.
        future[0].lesson.refresh_from_db()
        attendee = future[0].lesson.attendees.get()
        assert attendee.charge_amount == gbp("0.00")


def test_eligibility_by_age_and_year_group(org, world):
    group_class = future_class(org, world, min_age=9, max_age=11, year_groups=["Year 6"])
    student = world["student"]
    with pytest.raises(services.NotEligible, match="date of birth"):
        enrol(org, group_class, student)
    with tenant_context(org):
        student.date_of_birth = group_class.start_date.replace(year=group_class.start_date.year - 8)
        student.year_group = "Year 6"
        student.save()
    with pytest.raises(services.NotEligible, match="ages 9 and up"):
        enrol(org, group_class, student)
    with tenant_context(org):
        student.date_of_birth = group_class.start_date.replace(
            year=group_class.start_date.year - 10
        )
        student.year_group = "Year 5"
        student.save()
    with pytest.raises(services.NotEligible, match="Year 6"):
        enrol(org, group_class, student)
    assert enrol(org, group_class, student, check_eligibility=False).status == "enrolled"


def test_capacity_is_enforced_and_the_class_fills(org, world):
    group_class = future_class(org, world, capacity=2)
    enrol(org, group_class, world["student"])
    with pytest.raises(BusinessRuleViolation, match="already in this class"):
        enrol(org, group_class, world["student"])
    enrol(org, group_class, world["sibling"])
    with tenant_context(org):
        assert GroupClass.objects.get(pk=group_class.pk).status == "full"
    assert events_of(org, "class.full")
    third = StudentFactory(organisation=org)
    with pytest.raises(services.ClassFull) as caught:
        enrol(org, group_class, third)
    assert caught.value.extra["waitlist"] is True
    assert enrol(org, group_class, third, override_capacity=True).status == "enrolled"


def test_trials_are_free_until_converted(org, world):
    group_class = running_class(org, world)
    enrolment = enrol(org, group_class, world["student"], trial=True)
    assert enrolment.status == "trial"
    with tenant_context(org):
        assert not Charge.objects.filter(
            source_key__startswith=f"enrolment:{enrolment.pk}"
        ).exists()
        enrolment = services.convert_trial(enrolment)
        assert enrolment.status == "enrolled"
        assert Charge.objects.get(source_key=services.fee_key(enrolment)).gross == gbp("75.00")
    assert events_of(org, "enrolment.confirmed")


# --- T04 class billing --------------------------------------------------------------------------


def test_registration_fee_once_a_year_and_materials_each_class(org, world):
    with tenant_context(org):
        course = world["course"]
        course.registration_fee = gbp("25.00")
        course.materials_fee = gbp("10.00")
        course.save()
    first = future_class(org, world)
    second = make_class(org, world, first.term, name="Sunday 2pm", start_time=time(14))
    a = enrol(org, first, world["student"])
    b = enrol(org, second, world["student"])
    assert a.price_snapshot["due_now"]["amount"] == "155.00"
    assert b.price_snapshot["registration_fee"]["amount"] == "0.00"
    with tenant_context(org):
        reg = Charge.objects.filter(source_key__startswith="registration:")
        assert reg.count() == 1
        assert Charge.objects.filter(source_key__endswith=":materials").count() == 2
        invoice = Charge.objects.get(source_key=services.fee_key(a)).invoice
        assert invoice.total == gbp("155.00")  # fee, registration and materials together


def test_sibling_and_multi_class_discounts(org, world):
    with tenant_context(org):
        DiscountRule.objects.create(kind="sibling", name="Siblings", percent=Decimal(10))
        DiscountRule.objects.create(
            kind="multi_class", name="Second class", percent=Decimal(5), min_classes=2
        )
    first = future_class(org, world)
    second = make_class(org, world, first.term, name="Sunday 2pm", start_time=time(14))
    a = enrol(org, first, world["student"])
    b = enrol(org, first, world["sibling"])
    c = enrol(org, second, world["student"])
    assert a.fee == gbp("120.00")
    assert b.fee == gbp("108.00")
    assert [d["name"] for d in b.price_snapshot["discounts"]] == ["Siblings"]
    assert c.fee == gbp("114.00")


def test_pay_as_you_go_charges_each_delivered_session(org, world):
    with tenant_context(org):
        course = world["course"]
        course.pricing_model = Course.PricingModel.PER_SESSION
        course.price = gbp("18.00")
        course.save()
    group_class = future_class(org, world)
    enrolment = enrol(org, group_class, world["student"])
    with tenant_context(org):
        assert not Charge.objects.filter(
            source_key__startswith=f"enrolment:{enrolment.pk}"
        ).exists()
        lesson = group_class.sessions.order_by("date").first().lesson
        assert lesson.attendees.get().charge_amount == gbp("18.00")
        start = now() - timedelta(hours=2)
        Lesson.objects.filter(pk=lesson.pk).update(start=start, end=start + timedelta(hours=1))
        lesson.refresh_from_db()
        services.mark_register(
            ClassSession.objects.get(lesson=lesson),
            [{"student": world["student"].pk, "outcome": "present"}],
        )
        billing.sync_lesson_charges(lesson.pk)
        assert Charge.objects.get(lesson=lesson).gross == gbp("18.00")


def test_monthly_courses_use_a_billing_plan(org, world):
    with tenant_context(org):
        course = world["course"]
        course.pricing_model = Course.PricingModel.PER_MONTH
        course.price = gbp("60.00")
        course.save()
    group_class = future_class(org, world, weeks=8)
    enrolment = enrol(org, group_class, world["student"])
    with tenant_context(org):
        plan = BillingPlan.objects.get(pk=enrolment.billing_plan_id)
        assert (plan.interval, plan.amount, plan.end_date) == (
            "monthly", gbp("60.00"), group_class.end_date,
        )  # fmt: skip
        assert plan.student_id == world["student"].pk


def test_instalments_add_up_to_the_fee(org, world):
    with tenant_context(org):
        course = world["course"]
        course.pricing_model = Course.PricingModel.INSTALMENTS
        course.price = gbp("100.00")
        course.instalments = 3
        course.save()
    group_class = future_class(org, world)
    enrolment = enrol(org, group_class, world["student"])
    with tenant_context(org):
        parts = Charge.objects.filter(source_key__startswith=f"{services.fee_key(enrolment)}:i")
        assert sorted(c.gross.amount for c in parts) == [
            Decimal("33.33"), Decimal("33.33"), Decimal("33.34"),
        ]  # fmt: skip
        assert parts.filter(invoice__isnull=False).count() == 1  # the first one now
        assert len({c.date for c in parts}) == 3


def test_fees_from_term_start_wait_for_the_invoice_run(org, world):
    settings(org, fee_timing="term_start")
    group_class = future_class(org, world)
    enrolment = enrol(org, group_class, world["student"])
    with tenant_context(org):
        charge = Charge.objects.get(source_key=services.fee_key(enrolment))
        assert charge.invoice_id is None
        assert charge.date == group_class.start_date


def test_proration_by_teaching_weeks_leaves_out_breaks(org, world):
    settings(org, proration_basis="weeks")
    first = today() + timedelta(days=1) - timedelta(weeks=2)
    term = make_term(
        org,
        world,
        first,
        8,
        breaks=[(first + timedelta(weeks=4), first + timedelta(weeks=5) - timedelta(days=1))],
    )
    group_class = make_class(org, world, term, first=first)
    with tenant_context(org):
        quote = services.quote(group_class, start_date=today())
    # 7 teaching weeks (one is half term); 5 remain from this week: £120 x 5/7.
    assert quote["units"] == {"basis": "weeks", "total": 7, "remaining": 5}
    assert quote["fee_due"]["amount"] == "85.71"


# --- T05 withdrawals and transfers --------------------------------------------------------------


def test_withdrawing_credits_unused_sessions_and_frees_the_place(org, world):
    group_class = future_class(org, world, weeks=4, capacity=1)
    enrolment = enrol(org, group_class, world["student"])
    waiting = StudentFactory(organisation=org)
    with tenant_context(org):
        services.join_waitlist(group_class, waiting)
        sessions = list(group_class.sessions.order_by("date"))
        invoice = Charge.objects.get(source_key=services.fee_key(enrolment)).invoice
        services.withdraw(enrolment, effective=sessions[2].date, reason="Moving away")
        enrolment.refresh_from_db()
        assert enrolment.status == "withdrawn"
        assert enrolment.end_date == sessions[2].date - timedelta(days=1)
        # Two of four sessions attended: half of £120 is credited on the unpaid invoice.
        note = CreditNote.objects.get(invoice=invoice)
        assert note.total == gbp("60.00")
        invoice.refresh_from_db()
        assert invoice.balance_due == gbp("60.00")
    assert str(world["student"].pk) in session_students(org, sessions[1])
    assert str(world["student"].pk) not in session_students(org, sessions[2])
    [freed] = events_of(org, "class.places_freed")
    assert freed.payload["subject"]["id"] == str(group_class.pk)
    with tenant_context(org):
        assert services.fill_vacancies(group_class.pk) == 1  # the handler's work
        assert WaitlistEntry.objects.get(student=waiting).status == "offered"


def test_no_refund_setting_keeps_the_fee(org, world):
    settings(org, withdrawal_refund="none")
    group_class = future_class(org, world, weeks=4)
    enrolment = enrol(org, group_class, world["student"])
    with tenant_context(org):
        services.withdraw(enrolment, reason="Stopping")
        assert not CreditNote.objects.exists()


def test_withdrawing_from_a_monthly_course_ends_its_plan(org, world):
    with tenant_context(org):
        course = world["course"]
        course.pricing_model = Course.PricingModel.PER_MONTH
        course.price = gbp("60.00")
        course.save()
    group_class = future_class(org, world, weeks=8)
    enrolment = enrol(org, group_class, world["student"])
    leaving = group_class.start_date + timedelta(days=20)
    with tenant_context(org):
        services.withdraw(enrolment, effective=leaving)
        plan = BillingPlan.objects.get(pk=enrolment.billing_plan_id)
        assert plan.end_date == leaving - timedelta(days=1)


def test_transfers_move_the_student_and_settle_the_difference(org, world):
    group_class = future_class(org, world, weeks=4)
    other = make_class(org, world, group_class.term, name="Sunday 2pm", start_time=time(14))
    enrolment = enrol(org, group_class, world["student"])
    with tenant_context(org):
        sessions = list(group_class.sessions.order_by("date"))
        record = services.transfer(enrolment, other, effective=sessions[2].date, reason="Clash")
        enrolment.refresh_from_db()
        assert enrolment.status == "transferred"
        new = record.to_enrolment
        assert (new.status, new.source, new.start_date) == (
            "enrolled",
            "transfer",
            sessions[2].date,
        )
        assert record.adjustment["credited"]["amount"] == "60.00"
    assert str(world["student"].pk) not in session_students(org, sessions[2])
    with tenant_context(org):
        later = [s for s in other.sessions.order_by("date") if s.date >= sessions[2].date]
    assert later
    assert all(str(world["student"].pk) in session_students(org, s) for s in later)
    assert events_of(org, "enrolment.transferred")


# --- T06 waitlist -------------------------------------------------------------------------------


def test_the_waitlist_offers_a_free_place_and_accepting_enrols(org, world):
    group_class = future_class(org, world, capacity=1)
    taken = enrol(org, group_class, world["student"])
    with tenant_context(org):
        entry = services.join_waitlist(group_class, world["sibling"])
        second = services.join_waitlist(group_class, StudentFactory(organisation=org))
        assert (leads.position(entry), leads.position(second)) == (1, 2)
        services.withdraw(taken, reason="Moving")
        assert services.fill_vacancies(group_class.pk) == 1
        entry.refresh_from_db()
        assert entry.status == "offered"
        # The offered place is held: nobody else can take it meanwhile.
        assert selectors.places_left(group_class) == 0
        with pytest.raises(services.ClassFull):
            services.enrol(group_class, StudentFactory(organisation=org))
    with tenant_context(org):
        WaitlistEntry.objects.filter(pk=entry.pk).update(offer_token_hash=leads._hash("tok"))
        leads.respond("tok", accept=True)
        enrolment = services.enrol_from_waitlist(entry.pk)
        assert (enrolment.status, enrolment.source) == ("enrolled", "waitlist")
        assert services.enrol_from_waitlist(entry.pk) is None  # idempotent
    accepted = events_of(org, "waitlist.place_accepted")
    assert accepted[-1].payload["data"]["group_class_id"] == str(group_class.pk)


def test_class_waitlists_dont_cascade_by_subject(org, world):
    group_class = future_class(org, world, capacity=1)
    with tenant_context(org):
        entry = services.join_waitlist(group_class, world["student"])
        other = leads.add_to_waitlist(student=world["sibling"], subject=group_class.course.name)
        assert leads.position(other) == 1  # a separate queue from the class's
        leads.offer_place(entry, details="x")
        assert leads.expire_offer(entry.pk) == ""  # the class offers again itself
    assert events_of(org, "waitlist.expired")[-1].payload["data"]["group_class_id"] == str(
        group_class.pk
    )


# --- T07 registers and makeups ------------------------------------------------------------------


def test_register_marks_everyone_with_absence_reasons(org, world):
    group_class = future_class(org, world)
    enrol(org, group_class, world["student"])
    enrol(org, group_class, world["sibling"])
    with tenant_context(org):
        session = group_class.sessions.order_by("date").first()
        start = now() - timedelta(hours=2)
        Lesson.objects.filter(pk=session.lesson_id).update(
            start=start, end=start + timedelta(hours=1)
        )
    response = world["admin_api"].post(
        f"/api/v1/class-sessions/{session.pk}/register",
        {"rows": [
            {"student": str(world["student"].pk), "outcome": "present"},
            {"student": str(world["sibling"].pk), "outcome": "absent_notified",
             "absence_reason": "Ill"},
        ]},
        format="json",
    )  # fmt: skip
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["lesson_status"] == "completed"
    rows = {r["student"]: r for r in body["rows"]}
    assert rows[str(world["sibling"].pk)]["absence_reason"] == "Ill"
    assert rows[str(world["sibling"].pk)]["outcome"] == "absent_notified"


def test_makeups_go_to_another_class_of_the_same_course(org, world):
    first = running_class(org, world)
    other = make_class(
        org,
        world,
        first.term,
        first=first.start_date + timedelta(days=1),
        name="Sunday",
        start_time=time(14),
    )
    enrol(org, first, world["student"])
    with tenant_context(org):
        missed = first.sessions.filter(date__gte=today()).order_by("date").first()
        start = now() - timedelta(hours=3)
        Lesson.objects.filter(pk=missed.lesson_id).update(
            start=start, end=start + timedelta(hours=1)
        )
        services.mark_register(
            missed, [{"student": world["student"].pk, "outcome": "absent_notified"}]
        )
        target = other.sessions.filter(date__gt=today()).order_by("date").first()
        booking = services.book_makeup(target, world["student"], from_session=missed)
        assert booking.status == MakeupBooking.Status.BOOKED
        assert booking.makeup_credit_id is not None
        lesson = Lesson.objects.get(pk=target.lesson_id)
        assert lesson.attendees.get(student=world["student"]).charge_amount == gbp("0.00")
        from tutortrack.delivery.selectors import makeup_students

        assert str(world["student"].pk) in makeup_students(lesson)
        other_course = CourseFactory(organisation=org)
        elsewhere = make_class(
            org, world, first.term, course=other_course, name="Chess", start_time=time(17)
        )
        with pytest.raises(BusinessRuleViolation, match="same course"):
            services.book_makeup(
                elsewhere.sessions.filter(date__gt=today()).first(),
                world["sibling"],
                from_session=missed,
            )


# --- T08 term rollover --------------------------------------------------------------------------


def _two_terms(org, world, mode="confirm"):
    current = future_class(org, world, weeks=4)
    spring_start = current.term.end_date + timedelta(days=14)
    spring = make_term(org, world, spring_start, 4, name="Spring")
    nxt = make_class(
        org,
        world,
        spring,
        first=spring_start
        + timedelta(days=(current.start_date.weekday() - spring_start.weekday()) % 7),
    )
    enrol(org, current, world["student"])
    enrol(org, current, world["sibling"])
    with tenant_context(org):
        rollover = services.start_rollover(
            current.term, spring, mode=mode, deadline=now() + timedelta(days=7)
        )
    return current, nxt, rollover


def test_rollover_enrols_confirmed_students_and_releases_the_rest(org, world):
    _current, nxt, rollover = _two_terms(org, world)
    assert events_of(org, "term.rollover_started")
    with tenant_context(org):
        offers = {o.student_id: o for o in rollover.offers.all()}
        assert len(offers) == 2
        services.respond_rollover(offers[world["student"].pk], confirm=True)
        assert services.rollover_state(rollover.pk)["pending"] == 1
        result = services.finalise_rollover(rollover.pk)
        assert result == {"enrolled": 1, "released": 1, "failed": 0}
        assert Enrolment.objects.get(group_class=nxt).student_id == world["student"].pk
        assert TermRollover.objects.get(pk=rollover.pk).status == "finalised"


def test_opt_out_rollover_keeps_everyone_who_didnt_decline(org, world):
    _current, nxt, rollover = _two_terms(org, world, mode="opt_out")
    with tenant_context(org):
        offer = rollover.offers.get(student=world["sibling"])
        services.respond_rollover(offer, confirm=False)
        services.finalise_rollover(rollover.pk)
        assert list(
            Enrolment.objects.filter(group_class=nxt).values_list("student_id", flat=True)
        ) == [world["student"].pk]
        assert RolloverOffer.objects.get(pk=offer.pk).status == "released"


def test_families_answer_from_the_email_link_and_the_portal(org, world):
    _current, _nxt, rollover = _two_terms(org, world)
    with tenant_context(org):
        offer = rollover.offers.get(student=world["student"])
        sibling_offer = rollover.offers.get(student=world["sibling"])
    public = client_for(org, None)
    token = services._token(offer.pk)
    page = public.get(f"/api/v1/public/re-enrol/{token}")
    assert page.status_code == 200
    assert page.json()["open"] is True
    assert public.get("/api/v1/public/re-enrol/wrong").status_code == 404
    answer = public.post(f"/api/v1/public/re-enrol/{token}", {"confirm": True}, format="json")
    assert answer.json()["status"] == "confirmed"
    portal = world["family"]["api"]
    listing = portal.get("/api/v1/portal/courses").json()
    assert {o["status"] for o in listing["rollover_offers"]} == {"confirmed", "pending"}
    reply = portal.post(
        f"/api/v1/portal/rollover-offers/{sibling_offer.pk}", {"confirm": False}, format="json"
    )
    assert reply.status_code == 200
    assert reply.json()["status"] == "declined"
    outsider = make_household(org, "The Smiths")["api"]
    assert (
        outsider.post(
            f"/api/v1/portal/rollover-offers/{offer.pk}", {"confirm": False}, format="json"
        ).status_code
        == 404
    )
    assert len(events_of(org, "term.rollover_responded")) == 2


# --- T09 public catalogue and online enrolment --------------------------------------------------


def test_public_catalogue_shows_open_public_classes_with_places(org, world):
    group_class = future_class(org, world, capacity=3, min_age=9, max_age=11)
    make_class(org, world, group_class.term, name="Draft", status="draft", start_time=time(15))
    enrol(org, group_class, world["student"], check_eligibility=False)
    public = client_for(org, None)
    body = public.get("/api/v1/public/catalogue").json()
    assert [c["id"] for c in body["classes"]] == [str(group_class.pk)]
    card = body["classes"][0]
    assert (card["places_left"], card["price"], card["course"]["name"]) == (
        2,
        "£120.00",
        "Year 6 11+ Prep",
    )
    assert public.get("/api/v1/public/catalogue", {"age": 15}).json()["classes"] == []
    weekday = group_class.start_date.weekday()
    assert (
        public.get("/api/v1/public/catalogue", {"weekday": (weekday + 1) % 7}).json()["classes"]
        == []
    )
    assert len(public.get("/api/v1/public/catalogue", {"weekday": weekday}).json()["classes"]) == 1


def test_online_enrolment_holds_the_place_until_paid(org, world):
    settings(org, online_payment="full")
    group_class = future_class(org, world)
    public = client_for(org, None)
    response = public.post(
        "/api/v1/public/enrol",
        {"group_class": str(group_class.pk),
         "contact": {"first_name": "Sam", "last_name": "Okafor", "email": "sam@example.com"},
         "student": {"first_name": "Tobi"}},
        format="json",
    )  # fmt: skip
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "pending_payment"
    assert "/pay/" in body["pay_url"]
    status = public.get(f"/api/v1/public/enrolments/{body['id']}", {"token": body["token"]})
    assert status.json()["status"] == "pending_payment"
    assert public.get(f"/api/v1/public/enrolments/{body['id']}", {"token": "x"}).status_code == 404
    with tenant_context(org):
        enrolment = Enrolment.objects.get(pk=body["id"])
        assert selectors.places_left(group_class) == group_class.capacity - 1
        request = PaymentRequest.objects.get(pk=enrolment.payment_request_id)
        assert request.amount == gbp("120.00")
        billing.pay_payment_request(request, gbp("120.00"))
        assert services.confirm_enrolment(enrolment.pk) == "enrolled"
        invoice = Charge.objects.get(source_key=services.fee_key(enrolment)).invoice
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PAID  # the payment became credit


def test_unpaid_places_are_released(org, world):
    settings(org, online_payment="full")
    group_class = future_class(org, world)
    with tenant_context(org):
        enrolment = services.enrol(group_class, world["student"], source="portal", payment="full")
        assert enrolment.status == "pending_payment"
        assert services.release_enrolment(enrolment.pk) == "withdrawn"
        assert PaymentRequest.objects.get(pk=enrolment.payment_request_id).status == "cancelled"
    assert events_of(org, "enrolment.released")


def test_online_enrolment_checks_eligibility_before_creating_a_family(org, world):
    group_class = future_class(org, world, year_groups=["Year 6"])
    from tutortrack.people.models import Client

    with tenant_context(org):
        before = Client.objects.count()
    response = client_for(org, None).post(
        "/api/v1/public/enrol",
        {"group_class": str(group_class.pk),
         "contact": {"first_name": "Sam", "last_name": "Okafor", "email": "sam@example.com"},
         "student": {"first_name": "Tobi", "year_group": "Year 3"}},
        format="json",
    )  # fmt: skip
    assert response.status_code == 422
    with tenant_context(org):
        assert Client.objects.count() == before


def test_a_full_class_takes_website_waitlist_signups(org, world):
    group_class = future_class(org, world, capacity=1)
    enrol(org, group_class, world["student"])
    response = client_for(org, None).post(
        "/api/v1/public/enrol",
        {"group_class": str(group_class.pk), "join_waitlist": True,
         "contact": {"first_name": "Sam", "last_name": "Okafor", "email": "sam@example.com"},
         "student": {"first_name": "Tobi"}},
        format="json",
    )  # fmt: skip
    assert response.status_code == 201, response.json()
    assert (response.json()["status"], response.json()["waitlist_position"]) == ("waitlisted", 1)


def test_portal_families_enrol_their_children(org, world):
    group_class = future_class(org, world)
    portal = world["family"]["api"]
    catalogue = portal.get("/api/v1/portal/classes").json()
    assert [c["id"] for c in catalogue["classes"]] == [str(group_class.pk)]
    response = portal.post(
        "/api/v1/portal/enrol",
        {"group_class": str(group_class.pk), "student": str(world["student"].pk)},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "enrolled"
    stranger = StudentFactory(organisation=org)
    assert portal.post(
        "/api/v1/portal/enrol",
        {"group_class": str(group_class.pk), "student": str(stranger.pk)}, format="json",
    ).status_code == 404  # fmt: skip
    listing = portal.get("/api/v1/portal/courses").json()
    assert [e["class_name"] for e in listing["enrolments"]] == ["Saturday 10am"]


def test_the_catalogue_widget_and_website_block_are_registered(org, world):
    from tutortrack.sites import blocks, widgets

    kind = widgets.get("class_catalogue")
    assert kind is not None
    assert kind.element == "tt-class-catalogue"
    group_class = future_class(org, world)
    block = blocks.get("class_catalogue")
    with tenant_context(org):
        assert kind.is_available()
        data = block.load({"limit": 5}, org)
    assert [c["id"] for c in data["classes"]] == [str(group_class.pk)]
    cleaned = blocks.validate([{"type": "class_catalogue", "props": {"heading": "Classes"}}])
    assert cleaned[0]["props"]["limit"] == 12


# --- API ----------------------------------------------------------------------------------------


def test_staff_set_up_a_term_course_and_class_and_enrol_through_the_api(org, world):
    api = world["admin_api"]
    start = today() + timedelta(days=1)
    term = api.post(
        "/api/v1/terms",
        {"academic_year": str(world["year"].pk), "name": "Spring", "start_date": str(start),
         "end_date": str(start + timedelta(days=41)),
         "breaks": [{"name": "Half term", "start_date": str(start + timedelta(days=14)),
                     "end_date": str(start + timedelta(days=20))}]},
        format="json",
    )  # fmt: skip
    assert term.status_code == 201, term.json()
    course = api.post(
        "/api/v1/courses",
        {"name": "GCSE Maths", "service": str(world["course"].service_id),
         "price": {"amount": "200.00", "currency": "GBP"}, "pricing_model": "per_term",
         "default_capacity": 10, "is_public": True},
        format="json",
    )  # fmt: skip
    assert course.status_code == 201, course.json()
    created = api.post(
        "/api/v1/classes",
        {"course": course.json()["id"], "term": term.json()["id"], "name": "Tuesday 5pm",
         "start_time": "17:00", "duration_minutes": 60, "rrule": weekly_on(start),
         "capacity": 6, "status": "open", "teachers": [{"tutor": str(world["tutor"].pk)}]},
        format="json",
    )  # fmt: skip
    assert created.status_code == 201, created.json()
    class_id = created.json()["group_class"]["id"]
    assert len(api.get(f"/api/v1/classes/{class_id}/sessions").json()) == 5
    quote = api.post(
        "/api/v1/enrolments/quote",
        {"group_class": class_id, "student": str(world["student"].pk)}, format="json",
    )  # fmt: skip
    assert quote.json()["fee_due"]["amount"] == "200.00"
    enrolment = api.post(
        "/api/v1/enrolments",
        {"group_class": class_id, "student": str(world["student"].pk)},
        format="json",
        HTTP_IDEMPOTENCY_KEY="enrol-1",
    )
    assert enrolment.status_code == 201, enrolment.json()
    roster = api.get(f"/api/v1/classes/{class_id}/roster").json()
    assert [r["student_name"] for r in roster] == [world["student"].full_name]
    withdrawn = api.post(
        f"/api/v1/enrolments/{enrolment.json()['id']}/withdraw", {"reason": "Busy"}, format="json"
    )
    assert withdrawn.json()["status"] == "withdrawn"


def test_tutors_see_and_mark_only_their_own_classes(org, world):
    mine = future_class(org, world)
    other_tutor = TutorProfileFactory(organisation=org, status="active")
    theirs = make_class(
        org, world, mine.term, name="Other", start_time=time(15), teachers=[{"tutor": other_tutor}]
    )
    api = world["tutor_api"]
    ids = {c["id"] for c in api.get("/api/v1/classes").json()["results"]}
    assert ids == {str(mine.pk)}
    assert api.get(f"/api/v1/classes/{theirs.pk}").status_code == 404
    assert api.post(f"/api/v1/classes/{mine.pk}/cancel", {}, format="json").status_code == 403


def test_cancelling_a_class_withdraws_everyone_and_cancels_sessions(org, world):
    group_class = future_class(org, world, weeks=4)
    enrolment = enrol(org, group_class, world["student"])
    with tenant_context(org):
        services.cancel_class(group_class, reason="Not enough students")
        enrolment.refresh_from_db()
        assert enrolment.status == "withdrawn"
        assert not Lesson.objects.filter(series_id=group_class.series_id, status="planned").exists()
        assert CreditNote.objects.get().total == gbp("120.00")
    assert events_of(org, "class.cancelled")


def _course(org):
    return CourseFactory(organisation=org)


class TestCourseIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/courses"

    def make_object(self, organisation):
        return _course(organisation)


class TestAcademicYearIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/academic-years"

    def make_object(self, organisation):
        return AcademicYearFactory(organisation=organisation)


class TestTermIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/terms"

    def make_object(self, organisation):
        return TermFactory(organisation=organisation)


def _class_in(organisation):
    tutor = TutorProfileFactory(organisation=organisation, status="active")
    course = CourseFactory(organisation=organisation)
    term = TermFactory(organisation=organisation)
    with tenant_context(organisation):
        group_class, _ = services.create_class(
            course=course, term=term, name="Isolated", start_time=time(9),
            duration_minutes=60, teachers=[{"tutor": tutor}],
        )  # fmt: skip
    return group_class


class TestClassIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/classes"

    def make_object(self, organisation):
        return _class_in(organisation)


class TestEnrolmentIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/enrolments"

    def make_object(self, organisation):
        group_class = _class_in(organisation)
        with tenant_context(organisation):
            return services.enrol(group_class, StudentFactory(organisation=organisation))


class TestSessionIsolation:
    def test_sessions_of_other_organisations_are_404(self, org, other_org):
        theirs = _class_in(other_org)
        with tenant_context(other_org):
            session = theirs.sessions.first()
        api = client_for(org, MembershipFactory(organisation=org, role="admin").user)
        assert api.get(f"/api/v1/class-sessions/{session.pk}").status_code == 404
        assert api.get(f"/api/v1/class-sessions/{session.pk}/register").status_code == 404


class TestRolloverIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/enrolments/rollover"

    def make_object(self, organisation):
        current = TermFactory(organisation=organisation)
        nxt = TermFactory(
            organisation=organisation, academic_year=current.academic_year,
            start_date=current.end_date + timedelta(days=10),
            end_date=current.end_date + timedelta(days=60),
        )  # fmt: skip
        with tenant_context(organisation):
            return services.start_rollover(current, nxt, deadline=now() + timedelta(days=3))


def test_course_validation(org, world):
    split = ServiceFactory(organisation=org, format="class", max_students=10, group_charge="split")
    with tenant_context(org), pytest.raises(BusinessRuleViolation, match="each student"):
        services.save_course(
            None, name="X", service=split, price=gbp("10.00"), pricing_model="per_session"
        )
    with tenant_context(org), pytest.raises(BusinessRuleViolation, match="at least two"):
        services.save_course(
            None,
            name="X",
            service=world["course"].service,
            price=gbp("10.00"),
            pricing_model="instalments",
        )
    with tenant_context(org), pytest.raises(BusinessRuleViolation, match="at most 12"):
        services.save_course(
            None, name="X", service=world["course"].service, price=gbp("10.00"), default_capacity=30
        )
    usd = Money("10.00", "USD")
    with tenant_context(org), pytest.raises(BusinessRuleViolation, match="currency"):
        services.save_course(None, name="X", service=world["course"].service, price=usd)
