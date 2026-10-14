"""FR-25-3 commission arithmetic: property tests (Hypothesis) for rates, rounding,
clawbacks, tiers and the "for N months" window."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from hypothesis import given
from hypothesis import strategies as st

from tutortrack.core.money import Money
from tutortrack.growth import commission

amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=2)
rates = st.decimals(min_value=Decimal("0"), max_value=Decimal("100"), places=2)


def gbp(value: str | Decimal) -> Money:
    return Money(Decimal(value), "GBP")


def test_acceptance_example():
    """10% of a £200 payment is £20; a £50 refund claws back £5."""
    earned = commission.commission_for(gbp("200"), Decimal("10"))
    assert earned == gbp("20.00")
    assert commission.clawback_for(gbp("50"), Decimal("10"), earned, gbp("0")) == gbp("-5.00")


@given(amounts, rates)
def test_commission_is_rounded_half_up_and_bounded(base, rate):
    value = commission.commission_for(gbp(base), rate)
    assert value.is_rounded()
    assert gbp("0") <= value <= gbp(base)
    expected = (base * rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert value.amount == expected


@given(amounts, rates, st.lists(st.integers(min_value=1, max_value=100), min_size=1, max_size=6))
def test_clawbacks_never_exceed_what_was_earned(base, rate, shares):
    """Refunds of the whole payment, in any number of parts, take back at most the
    commission (and exactly it when the parts add up to the payment)."""
    payment = gbp(base)
    earned = commission.commission_for(payment, rate)
    parts = payment.allocate(shares)
    clawed = gbp("0")
    for part in parts:
        value = commission.clawback_for(part, rate, earned, clawed)
        assert not value.is_positive()
        clawed = clawed - value
        assert clawed <= earned
    assert earned - clawed <= gbp("0.01") * len(parts)


@given(st.integers(min_value=0, max_value=50))
def test_tiers_pick_the_highest_reached(converted):
    tiers = [{"from_clients": 5, "percent": "12"}, {"from_clients": 20, "percent": "15"}]
    rate = commission.tier_percent(Decimal("10"), tiers, converted)
    if converted >= 20:
        assert rate == Decimal("15")
    elif converted >= 5:
        assert rate == Decimal("12")
    else:
        assert rate == Decimal("10")


@given(
    st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2030, 12, 31)),
    st.integers(min_value=1, max_value=36),
)
def test_window_closes_after_n_months(start, months):
    start = start.replace(tzinfo=UTC)
    end = commission.add_months(start, months)
    assert commission.in_window(start, months, start)
    assert not commission.in_window(start, months, end)
    assert commission.in_window(start, None, end)  # lifetime


def test_tier_validation():
    assert commission.validate_tiers([{"from_clients": 3, "percent": "12.5"}]) == [
        {"from_clients": 3, "percent": "12.5"}
    ]
    for bad in (
        [{"from_clients": 0, "percent": "5"}],
        [{"from_clients": 2, "percent": "101"}],
        "x",
    ):
        try:
            commission.validate_tiers(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")
