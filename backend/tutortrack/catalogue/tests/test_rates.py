"""E06-T04: rate resolution engine (table-driven precedence + Hypothesis properties)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tutortrack.catalogue.models import Service
from tutortrack.catalogue.rates import (
    AttendeeInput,
    RateContext,
    TutorInput,
    resolve_rates,
    tax_on,
)
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money

GBP = "GBP"


def gbp(amount: str) -> Money:
    return Money(Decimal(amount), GBP)


def service(**overrides) -> Service:
    """An unsaved service: the engine only reads its fields (tax lookup needs a tenant)."""
    values = {
        "name": "Tuition",
        "currency": GBP,
        "charge_rate_amount": Decimal("40"),
        "pay_rate_amount": Decimal("25"),
        "pricing_unit": Service.PricingUnit.PER_HOUR,
        "pay_unit": Service.PayUnit.PER_HOUR,
        "max_students": 1,
    }
    values.update(overrides)
    return Service(**values)


@pytest.fixture(autouse=True)
def _no_tax(monkeypatch):
    monkeypatch.setattr("tutortrack.catalogue.rates._tax", lambda service: (None, False))


def quote(svc, minutes=60, students=1, tutors=1, **kwargs):
    attendees = kwargs.pop("attendees", [AttendeeInput(f"s{i}") for i in range(students)])
    tutor_inputs = kwargs.pop("tutor_inputs", [TutorInput(f"t{i}") for i in range(tutors)])
    return resolve_rates(
        RateContext(svc, minutes, attendees=attendees, tutors=tutor_inputs, **kwargs)
    )


def test_fr_06_2_per_hour_scales_with_duration():
    """AC FR-06-2: £40/h for 90 minutes is £60.00."""
    q = quote(service(), minutes=90)
    assert q.charges[0].amount == gbp("60.00")
    assert q.charges[0].trace == ["service rate £40.00/h", "90 minutes"]
    assert q.pay[0].amount == gbp("37.50")


def test_fr_06_2_per_lesson_ignores_duration():
    """AC FR-06-2: per-lesson £45 for a 90-minute lesson is £45.00."""
    q = quote(service(pricing_unit="per_lesson", charge_rate_amount=Decimal("45")), minutes=90)
    assert q.charges[0].amount == gbp("45.00")


@pytest.mark.parametrize(
    ("attendee", "job_rate", "expected", "label"),
    [
        (AttendeeInput("s", rate_override=gbp("50")), gbp("30"), "50.00", "lesson rate £50.00/h"),
        (
            AttendeeInput("s", job_rate_override=gbp("35")),
            gbp("30"),
            "35.00",
            "student's job rate £35.00/h",
        ),
        (AttendeeInput("s"), gbp("30"), "30.00", "job rate £30.00/h"),
        (AttendeeInput("s"), None, "40.00", "service rate £40.00/h"),
    ],
)
def test_charge_precedence(attendee, job_rate, expected, label):
    q = quote(service(), attendees=[attendee], job_charge_rate=job_rate)
    assert q.charges[0].amount == gbp(expected)
    assert q.charges[0].trace[0] == label


@pytest.mark.parametrize(
    ("tutor", "svc", "expected", "label"),
    [
        (TutorInput("t", rate_override=gbp("30")), {}, "30.00", "lesson pay rate £30.00/h"),
        (TutorInput("t", job_rate_override=gbp("28")), {}, "28.00", "tutor's job rate £28.00/h"),
        (TutorInput("t"), {}, "25.00", "service pay rate £25.00/h"),
        (
            TutorInput("t"),
            {"pay_rate_amount": None, "pay_percent": Decimal("60")},
            "24.00",
            "60% of the lesson charge",
        ),
        (TutorInput("t"), {"pay_rate_amount": None}, "0.00", "no pay rate set"),
    ],
)
def test_pay_precedence(tutor, svc, expected, label):
    q = quote(service(**svc), tutor_inputs=[tutor])
    assert q.pay[0].amount == gbp(expected)
    assert q.pay[0].trace[0] == label


def test_group_per_student_each_pays_full_rate():
    q = quote(service(format="small_group", max_students=4), students=3)
    assert [c.amount for c in q.charges] == [gbp("40.00")] * 3
    assert q.total_charge == gbp("120.00")


def test_group_split_shares_the_lesson_exactly():
    svc = service(format="small_group", max_students=4, group_charge="split")
    q = quote(svc, students=3)
    assert sorted(c.amount.amount for c in q.charges) == [
        Decimal("13.33"),
        Decimal("13.33"),
        Decimal("13.34"),
    ]
    assert q.total_charge == gbp("40.00")
    assert "split between 3 students" in q.charges[0].trace


def test_per_student_per_lesson_ignores_split():
    svc = service(
        format="class", max_students=10, group_charge="split", pricing_unit="per_student_per_lesson"
    )
    q = quote(svc, students=4)
    assert [c.amount for c in q.charges] == [gbp("40.00")] * 4


def test_monthly_services_are_not_charged_per_lesson():
    q = quote(service(pricing_unit="per_month"))
    assert q.charges[0].amount == gbp("0.00")
    assert "billed by subscription, not per lesson" in q.charges[0].trace


def test_percentage_pay_shared_between_tutors():
    q = quote(service(pay_rate_amount=None, pay_percent=Decimal("50")), tutors=2, minutes=90)
    assert [p.amount for p in q.pay] == [gbp("15.00"), gbp("15.00")]


def test_per_lesson_pay():
    q = quote(service(pay_unit="per_lesson"), minutes=90)
    assert q.pay[0].amount == gbp("25.00")


def test_rejects_wrong_currency_negative_rates_and_too_many_students():
    with pytest.raises(BusinessRuleViolation):
        quote(service(), attendees=[AttendeeInput("s", rate_override=Money("10", "EUR"))])
    with pytest.raises(BusinessRuleViolation):
        quote(service(), attendees=[AttendeeInput("s", rate_override=gbp("-1"))])
    with pytest.raises(BusinessRuleViolation):
        quote(service(), students=2)
    with pytest.raises(BusinessRuleViolation):
        quote(service(), students=0)


def test_snapshot_is_json_safe():
    import json

    snapshot = quote(service(), minutes=45).as_dict()
    assert json.loads(json.dumps(snapshot))["total_charge"] == {"amount": "30.00", "currency": GBP}


@pytest.mark.parametrize(
    ("amount", "percent", "inclusive", "expected"),
    [("120.00", "20", True, "20.00"), ("100.00", "20", False, "20.00"), ("60.00", "0", False, "0")],
)
def test_tax_inclusive_and_exclusive(amount, percent, inclusive, expected):
    assert tax_on(gbp(amount), Decimal(percent), inclusive) == gbp(expected)


rates = st.decimals(min_value=0, max_value=1000, places=4, allow_nan=False, allow_infinity=False)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=200)
@given(
    rate=rates,
    minutes=st.integers(min_value=5, max_value=480),
    students=st.integers(min_value=1, max_value=12),
    unit=st.sampled_from(["per_hour", "per_lesson", "per_student_per_lesson"]),
    split=st.booleans(),
    percent=st.none() | st.decimals(min_value=0, max_value=100, places=2),
)
def test_amounts_are_rounded_non_negative_and_splits_add_up(
    rate, minutes, students, unit, split, percent
):
    svc = service(
        format="class",
        max_students=12,
        charge_rate_amount=rate,
        pricing_unit=unit,
        group_charge="split" if split else "per_student",
        pay_rate_amount=None if percent is not None else rate,
        pay_percent=percent,
    )
    q = quote(svc, minutes=minutes, students=students, tutors=2)
    for line in [*q.charges, *q.pay]:
        assert line.amount.is_rounded()
        assert not line.amount.is_negative()
    if split and students > 1 and unit != "per_student_per_lesson":
        hours = Decimal(minutes) / 60 if unit == "per_hour" else Decimal(1)
        assert q.total_charge == (Money(rate, GBP) * hours).round_to_minor()
    if percent is not None:
        assert q.total_pay == (q.total_charge * (percent / 100)).round_to_minor()
