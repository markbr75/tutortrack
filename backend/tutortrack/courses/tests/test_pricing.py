"""E20-T04: the pure course pricing engine and termly plan periods, with Hypothesis."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from tutortrack.billing.plans import term_segments
from tutortrack.core.money import Money
from tutortrack.courses import pricing

amounts = st.decimals(min_value=Decimal("0"), max_value=Decimal("5000"), places=2)
days = st.dates(min_value=date(2026, 1, 1), max_value=date(2030, 12, 31))


def gbp(value: Decimal | str) -> Money:
    return Money(value, "GBP")


@given(fee=amounts, total=st.integers(1, 60), data=st.data())
def test_prorating_stays_within_the_fee_and_splits_add_up(fee, total, data):
    remaining = data.draw(st.integers(0, total))
    part = pricing.prorate(gbp(fee), total=total, remaining=remaining)
    rest = pricing.prorate(gbp(fee), total=total, remaining=total - remaining)
    assert Money.zero("GBP") <= part <= gbp(fee)
    assert abs((part + rest).amount - fee) <= Decimal("0.01")
    if remaining < total:
        assert pricing.prorate(gbp(fee), total=total, remaining=remaining + 1) >= part


@given(fee=amounts, count=st.integers(1, 12), first=days)
def test_instalments_add_up_exactly_month_by_month(fee, count, first):
    parts = pricing.instalments(gbp(fee), count, first)
    assert len(parts) == count
    assert sum((p.amount for _d, p in parts), Decimal(0)) == fee
    amounts_ = [p.amount for _d, p in parts]
    assert max(amounts_) - min(amounts_) <= Decimal("0.01")
    dates = [d for d, _p in parts]
    assert dates == sorted(dates)
    assert all((b - a).days >= 28 for a, b in pairwise(dates))


discount = st.builds(
    pricing.CourseDiscount,
    name=st.sampled_from(["A", "B", "C"]),
    kind=st.sampled_from(["sibling", "multi_class"]),
    percent=st.one_of(st.none(), st.decimals(min_value=0, max_value=100, places=2)),
    fixed_amount=st.one_of(st.none(), amounts.map(gbp)),
    priority=st.integers(0, 3),
    stackable=st.booleans(),
    threshold=st.integers(2, 3),
)


@given(price=amounts, rules=st.lists(discount, max_size=4), position=st.integers(1, 4))
def test_discounts_never_go_below_zero_or_above_the_list_price(price, rules, position):
    facts = pricing.Facts(sibling_position=position, classes_this_term=position)
    quote = pricing.quote(gbp(price), rules, facts)
    assert Money.zero("GBP") <= quote.price <= quote.list_price
    total_off = sum((a.amount for _n, a in quote.discounts), Decimal(0))
    assert quote.list_price.amount + total_off == quote.price.amount
    matching = [r for r in rules if pricing.applies(r, facts)]
    picked = pricing.pick(matching)
    if picked and not picked[0].stackable:
        assert len(picked) == 1


def test_a_non_stackable_rule_first_applies_alone():
    rules = [
        pricing.CourseDiscount("Siblings", "sibling", percent=Decimal(10), priority=2,
                               stackable=False),
        pricing.CourseDiscount("Two classes", "multi_class", percent=Decimal(5), priority=1),
    ]  # fmt: skip
    quote = pricing.quote(gbp("100"), rules, pricing.Facts(sibling_position=2, classes_this_term=2))
    assert quote.price == gbp("90.00")
    assert [n for n, _a in quote.discounts] == ["Siblings"]


@given(start=days, weeks=st.integers(1, 16), data=st.data())
@settings(max_examples=50)
def test_whole_break_weeks_drop_out_of_teaching_weeks(start, weeks, data):
    end = start + timedelta(weeks=weeks) - timedelta(days=1)
    k = data.draw(st.integers(0, weeks - 1))
    holiday = (start + timedelta(weeks=k), start + timedelta(weeks=k, days=6))
    assert len(pricing.teaching_weeks(start, end, [])) == weeks
    assert len(pricing.teaching_weeks(start, end, [holiday])) == weeks - 1
    joining = data.draw(st.dates(min_value=start - timedelta(days=3), max_value=end))
    total, remaining = pricing.week_units(start, end, [holiday], joining)
    assert 0 <= remaining <= total == weeks - 1


@given(total=amounts, sessions=st.integers(1, 40))
def test_a_fixed_class_fee_for_teachers_splits_exactly(total, sessions):
    parts = [
        pricing.teacher_session_pay(
            "fixed", {"amount": str(total)}, "GBP", headcount=3, sessions=sessions, index=i
        )
        for i in range(sessions)
    ]
    assert sum((p.amount for p in parts if p is not None), Decimal(0)) == total


def test_headcount_tiers_pick_the_highest_reached():
    config = {"tiers": [{"from": 0, "amount": "20"}, {"from": 6, "amount": "30"}]}
    pay = [
        pricing.teacher_session_pay("headcount", config, "GBP", headcount=n, sessions=4, index=0)
        for n in (0, 5, 6, 12)
    ]
    assert pay == [gbp("20.00"), gbp("20.00"), gbp("30.00"), gbp("30.00")]
    assert (
        pricing.teacher_session_pay("service", {}, "GBP", headcount=1, sessions=1, index=0) is None
    )


@given(amount=amounts, minutes=st.sampled_from([30, 45, 60, 75, 90, 120]))
def test_session_rates_price_back_to_the_amount(amount, minutes):
    rate = pricing.rate_for(gbp(amount), per_hour=True, minutes=minutes)
    assert (rate * (Decimal(minutes) / Decimal(60))).round_to_minor() == gbp(amount)


@given(start=days, lengths=st.lists(st.integers(20, 100), min_size=1, max_size=4), data=st.data())
def test_termly_plan_periods_are_the_terms(start, lengths, data):
    terms = []
    cursor = start
    for length in lengths:
        terms.append((cursor, cursor + timedelta(days=length - 1)))
        cursor += timedelta(days=length + 14)  # holidays between terms
    plan_start = data.draw(st.dates(min_value=start, max_value=terms[-1][1]))
    segments = list(term_segments(terms, plan_start))
    assert segments
    for segment in segments:
        assert (segment.period_start, segment.period_end) in terms
        assert segment.period_start <= segment.start <= segment.end <= segment.period_end
        assert Decimal(0) < segment.fraction <= Decimal(1)
    covered = sum(s.days for s in segments)
    expected = sum((t1 - max(t0, plan_start)).days + 1 for t0, t1 in terms if t1 >= plan_start)
    assert covered == expected
