"""E06-T07..T09: the Phase 2 precedence levels and modifiers of the rate engine (pure,
table-driven) plus Hypothesis properties for money."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tutortrack.catalogue.models import Service
from tutortrack.catalogue.rates import (
    AttendeeFacts,
    AttendeeInput,
    Discount,
    LessonFacts,
    Premium,
    PricingRules,
    RateContext,
    TierRate,
    TutorInput,
    resolve_rates,
)
from tutortrack.core.money import Money

from .test_rates import gbp, service

LONDON = ZoneInfo("Europe/London")
SATURDAY_10 = datetime(2026, 11, 7, 10, 0, tzinfo=LONDON)
MONDAY_18 = datetime(2026, 11, 2, 18, 0, tzinfo=LONDON)


@pytest.fixture(autouse=True)
def _no_tax(monkeypatch):
    monkeypatch.setattr("tutortrack.catalogue.rates._tax", lambda service: (None, False))


def run(svc=None, minutes=60, rules=None, attendees=None, tutors=None, **kwargs):
    return resolve_rates(
        RateContext(
            svc or service(),
            minutes,
            attendees=attendees or [AttendeeInput("s0", client_id="c0")],
            tutors=tutors if tutors is not None else [TutorInput("t0")],
            rules=rules,
            **kwargs,
        )
    )


# --- precedence (FR-06-4, FR-06-5, FR-06-11) -----------------------------------------------------


def test_fr_06_11_client_price_list_beats_the_service_rate():
    rules = PricingRules(price_lists={"c0": (gbp("30"), "Council contract")})
    q = run(rules=rules)
    assert q.charges[0].amount == gbp("30.00")
    assert q.charges[0].trace[0] == "Council contract price £30.00/h"


def test_price_list_is_beaten_by_the_job_rate():
    rules = PricingRules(price_lists={"c0": (gbp("30"), "Council contract")})
    q = run(rules=rules, job_charge_rate=gbp("45"))
    assert q.charges[0].amount == gbp("45.00")


def test_fr_06_5_tier_charge_rate_only_when_the_setting_is_on():
    tiers = {"t0": TierRate("Senior", pay_rate=gbp("30"), charge_rate=gbp("50"))}
    assert run(rules=PricingRules(tier_rates=tiers)).charges[0].amount == gbp("40.00")
    q = run(rules=PricingRules(tier_rates=tiers, tier_affects_charge=True))
    assert q.charges[0].amount == gbp("50.00")
    assert q.charges[0].trace[0] == "Senior tier rate £50.00/h"


@pytest.mark.parametrize(
    ("rules", "tutor", "expected", "label"),
    [
        (PricingRules(), TutorInput("t0"), "25.00", "service pay rate £25.00/h"),
        (
            PricingRules(tier_rates={"t0": TierRate("Senior", pay_rate=gbp("30"))}),
            TutorInput("t0"),
            "30.00",
            "Senior tier pay rate £30.00/h",
        ),
        (
            PricingRules(
                tier_rates={"t0": TierRate("Senior", pay_rate=gbp("30"))},
                tutor_rates={"t0": gbp("33")},
            ),
            TutorInput("t0"),
            "33.00",
            "tutor's own rate £33.00/h",
        ),
        (
            PricingRules(tutor_rates={"t0": gbp("33")}),
            TutorInput("t0", job_rate_override=gbp("28")),
            "28.00",
            "tutor's job rate £28.00/h",
        ),
    ],
)
def test_fr_06_4_pay_precedence_table(rules, tutor, expected, label):
    q = run(rules=rules, tutors=[tutor])
    assert q.pay[0].amount == gbp(expected)
    assert q.pay[0].trace[0] == label


# --- premiums (FR-06-6) ------------------------------------------------------------------------


def weekend(**kw):
    return Premium(name="Weekend", weekdays=(5, 6), charge_percent=Decimal("10"), **kw)


def test_fr_06_6_weekend_premium_on_charge_and_pay():
    p = weekend(pay_fixed=gbp("2"))
    q = run(rules=PricingRules(premiums=[p], facts=LessonFacts(local_start=SATURDAY_10)))
    assert q.charges[0].amount == gbp("44.00")
    assert q.charges[0].trace == ["service rate £40.00/h", "60 minutes", "Weekend +10%"]
    assert q.pay[0].amount == gbp("27.00")
    q = run(rules=PricingRules(premiums=[p], facts=LessonFacts(local_start=MONDAY_18)))
    assert q.charges[0].amount == gbp("40.00")


@pytest.mark.parametrize(
    ("premium", "facts", "applies"),
    [
        (Premium(name="Eve", time_from=time(17), charge_percent=Decimal(5)),
         LessonFacts(local_start=MONDAY_18), True),
        (Premium(name="Eve", time_from=time(17), charge_percent=Decimal(5)),
         LessonFacts(local_start=SATURDAY_10), False),
        (Premium(name="Hol", public_holidays=True, charge_percent=Decimal(5)),
         LessonFacts(local_start=MONDAY_18, is_holiday=True), True),
        (Premium(name="Hol", public_holidays=True, charge_percent=Decimal(5)),
         LessonFacts(local_start=MONDAY_18), False),
        (Premium(name="Rush", short_notice_hours=24, charge_percent=Decimal(5)),
         LessonFacts(notice_hours=Decimal(3)), True),
        (Premium(name="Rush", short_notice_hours=24, charge_percent=Decimal(5)),
         LessonFacts(notice_hours=Decimal(48)), False),
        (Premium(name="Home", location_types=("client_home",), charge_percent=Decimal(5)),
         LessonFacts(location_type="client_home"), True),
        (Premium(name="Online", delivery="online", charge_percent=Decimal(5)),
         LessonFacts(online=False), False),
    ],
)  # fmt: skip
def test_fr_06_6_premium_conditions(premium, facts, applies):
    q = run(rules=PricingRules(premiums=[premium], facts=facts))
    assert (q.charges[0].amount == gbp("42.00")) is applies


def test_non_stackable_premium_with_top_priority_applies_alone():
    big = Premium(name="Holiday", priority=10, stackable=False, charge_percent=Decimal(50))
    small = Premium(name="Weekend", priority=1, charge_percent=Decimal(10))
    q = run(rules=PricingRules(premiums=[small, big]))
    assert q.charges[0].amount == gbp("60.00")
    both = Premium(name="Evening", priority=5, charge_percent=Decimal(5))
    q = run(rules=PricingRules(premiums=[small, both]))
    assert q.charges[0].amount == gbp("46.00")  # stackable rules add up


def test_fixed_premium_is_split_with_a_split_group_rate():
    svc = service(max_students=3, group_charge=Service.GroupCharge.SPLIT)
    p = Premium(name="Room hire", charge_fixed=gbp("3"))
    q = run(
        svc,
        rules=PricingRules(premiums=[p]),
        attendees=[AttendeeInput(f"s{i}", client_id="c") for i in range(3)],
    )
    assert q.total_charge == gbp("43.00")
    assert sum(line.amount.amount for line in q.charges) == Decimal("43.00")


def test_lesson_override_is_final():
    rules = PricingRules(premiums=[weekend()], facts=LessonFacts(local_start=SATURDAY_10))
    q = run(rules=rules, attendees=[AttendeeInput("s0", rate_override=gbp("35"))])
    assert q.charges[0].amount == gbp("35.00")
    assert q.charges[0].premiums == []


# --- discounts (FR-06-7) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("discount", "facts", "expected"),
    [
        (Discount(name="Sibling", kind="sibling", percent=Decimal(10)),
         AttendeeFacts(sibling_position=2), "36.00"),
        (Discount(name="Sibling", kind="sibling", percent=Decimal(10)),
         AttendeeFacts(sibling_position=1), "40.00"),
        (Discount(name="Volume", kind="volume", volume_min_lessons=8, fixed_amount=gbp("5")),
         AttendeeFacts(lessons_in_month=8), "35.00"),
        (Discount(name="Volume", kind="volume", volume_min_lessons=8, fixed_amount=gbp("5")),
         AttendeeFacts(lessons_in_month=7), "40.00"),
        (Discount(name="Trial", kind="first_lesson", fixed_price=gbp("15")),
         AttendeeFacts(first_lesson=True), "15.00"),
        (Discount(name="Trial", kind="first_lesson", fixed_price=gbp("15")),
         AttendeeFacts(first_lesson=False), "40.00"),
        (Discount(name="Loyal", kind="client", client_id="c0", percent=Decimal(25)),
         AttendeeFacts(), "30.00"),
        (Discount(name="Bursary", kind="scholarship", student_id="s0", percent=Decimal(100)),
         AttendeeFacts(), "0.00"),
        (Discount(name="SPRING", kind="promo", promo=True, percent=Decimal(20)),
         AttendeeFacts(), "32.00"),
    ],
)  # fmt: skip
def test_fr_06_7_discount_kinds(discount, facts, expected):
    rules = PricingRules(discounts=[discount], attendee_facts={"s0": facts})
    q = run(rules=rules)
    assert q.charges[0].amount == gbp(expected)
    if expected != "40.00":
        assert q.charges[0].discounts[0].name == discount.name
        assert q.charges[0].undiscounted_amount == gbp("40.00")


def test_trace_explains_job_rate_premium_and_discount():
    """AC FR-06-4: ["job rate £40/h", "weekend premium +10%", "sibling discount -5%"]."""
    rules = PricingRules(
        premiums=[Premium(name="weekend premium", weekdays=(5,), charge_percent=Decimal(10))],
        discounts=[Discount(name="sibling discount", kind="sibling", percent=Decimal(5))],
        facts=LessonFacts(local_start=SATURDAY_10),
        attendee_facts={"s0": AttendeeFacts(sibling_position=2)},
    )
    q = run(rules=rules, job_charge_rate=gbp("40"))
    assert q.charges[0].trace == [
        "job rate £40.00/h",
        "60 minutes",
        "weekend premium +10%",
        "sibling discount -5%",
    ]
    assert q.charges[0].amount == gbp("41.80")  # 44 less 5% (discounts apply after premiums)


def test_percentage_pay_from_net_or_gross():
    svc = service(pay_rate_amount=None, pay_percent=Decimal("50"))
    disc = Discount(name="Loyal", kind="client", client_id="c0", percent=Decimal(50))
    gross = run(svc, rules=PricingRules(discounts=[disc]))
    net = run(svc, rules=PricingRules(discounts=[disc], pay_percent_basis="net"))
    assert gross.pay[0].amount == gbp("20.00")
    assert net.pay[0].amount == gbp("10.00")


# --- Hypothesis (money) ---------------------------------------------------------------------------

percents = st.decimals(min_value=0, max_value=200, places=2)
amounts = st.decimals(min_value=0, max_value=500, places=2)


@settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    rate=st.decimals(min_value=0, max_value=300, places=4),
    minutes=st.integers(min_value=5, max_value=600).map(lambda m: m - m % 5 or 5),
    n=st.integers(min_value=1, max_value=6),
    premium_pct=percents,
    premium_fixed=amounts,
    disc_pct=st.decimals(min_value=0, max_value=100, places=2),
    disc_fixed=amounts,
    split=st.booleans(),
)
def test_lines_are_rounded_non_negative_and_split_totals_add_up(
    rate, minutes, n, premium_pct, premium_fixed, disc_pct, disc_fixed, split
):
    svc = service(
        charge_rate_amount=rate,
        max_students=6,
        group_charge=Service.GroupCharge.SPLIT if split else Service.GroupCharge.PER_STUDENT,
    )
    premium = Premium(
        name="P",
        charge_percent=premium_pct,
        charge_fixed=Money(premium_fixed, "GBP"),
        pay_percent=premium_pct,
    )
    attendees = [AttendeeInput(f"s{i}", client_id="c") for i in range(n)]
    without_discounts = run(svc, minutes, PricingRules(premiums=[premium]), attendees=attendees)
    for line in without_discounts.charges + without_discounts.pay:  # type: ignore[operator]
        assert line.amount.is_rounded()
        assert not line.amount.is_negative()
    if split and n > 1:
        lesson = (Money(rate, "GBP") * (Decimal(minutes) / 60)).round_to_minor()
        expected = (
            lesson
            + (lesson * (premium_pct / 100)).round_to_minor()
            + Money(premium_fixed, "GBP").round_to_minor()
        )
        assert without_discounts.total_charge == expected
    discount = Discount(name="D", kind="client", client_id="c", percent=disc_pct,
                        fixed_amount=Money(disc_fixed, "GBP"))  # fmt: skip
    q = run(
        svc, minutes, PricingRules(premiums=[premium], discounts=[discount]), attendees=attendees
    )
    for line, before in zip(q.charges, without_discounts.charges, strict=True):
        assert line.amount.is_rounded()
        assert not line.amount.is_negative()
        assert line.amount <= before.amount
        assert line.undiscounted_amount == before.amount
