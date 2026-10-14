"""FR-30-7 SaaS metrics and FR-30-6 health score maths: worked examples and property
tests (Hypothesis) for MRR, movements, churn, NRR, ARPA, cohorts and score bounds."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from tutortrack.platform_admin import health, metrics
from tutortrack.platform_admin.metrics import OrgMonth, PriceComponent

amounts = st.decimals(min_value=Decimal("0"), max_value=Decimal("5000"), places=2)
mrr_maps = st.dictionaries(st.sampled_from([f"org{i}" for i in range(12)]), amounts, max_size=12)


def test_subscription_mrr_from_list_prices():
    prices = [
        PriceComponent("base_fee", Decimal("29.0000")),
        PriceComponent("active_tutor", Decimal("4.5000"), included_quantity=3),
        PriceComponent("branch", Decimal("10.0000"), included_quantity=1),
        PriceComponent("revenue_share", Decimal("1.0000")),  # not recurring: left out
    ]
    monthly = metrics.subscription_mrr(
        prices, seats=5, branches=2, interval="month", currency="GBP"
    )
    assert monthly == Decimal("48.00")  # 29 + 2 x 4.50 + 1 x 10
    annual = [PriceComponent("base_fee", Decimal("290.0000"))]
    # 290 / 12 = 24.1666... rounds half-up to 24.17
    assert metrics.subscription_mrr(
        annual, seats=0, branches=1, interval="year", currency="GBP"
    ) == Decimal("24.17")
    assert metrics.subscription_mrr(
        annual, seats=0, branches=1, interval="year", currency="JPY"
    ) == Decimal("24")


@given(
    st.decimals(min_value=Decimal("0"), max_value=Decimal("10000"), places=4),
    st.integers(min_value=0, max_value=500),
    st.integers(min_value=0, max_value=50),
)
def test_mrr_is_rounded_and_never_negative(unit, seats, included):
    prices = [PriceComponent("base_fee", unit), PriceComponent("active_tutor", unit, included)]
    for interval in ("month", "year"):
        value = metrics.subscription_mrr(
            prices, seats=seats, branches=1, interval=interval, currency="GBP"
        )
        assert value >= 0
        assert value == value.quantize(Decimal("0.01"))
    yearly = metrics.subscription_mrr(
        prices, seats=seats, branches=1, interval="year", currency="GBP"
    )
    exact = (unit + unit * max(0, seats - included)) / 12
    assert abs(yearly - exact) <= Decimal("0.005")


@given(mrr_maps, mrr_maps, st.sets(st.sampled_from([f"org{i}" for i in range(12)])))
def test_movements_reconcile_start_to_end(before, after, paid_earlier):
    moved = metrics.movements(before, after, paid_earlier=paid_earlier)
    assert moved.start == sum(before.values(), Decimal(0))
    assert moved.end == sum(after.values(), Decimal(0))
    assert moved.start + moved.net_new == moved.end
    for bucket in (moved.new, moved.reactivation, moved.expansion, moved.contraction, moved.churn):
        assert bucket >= 0
    assert moved.churn <= moved.start


def test_movement_buckets_worked_example():
    before = {"a": Decimal("50"), "b": Decimal("30"), "c": Decimal("20"), "d": Decimal("0")}
    after = {
        "a": Decimal("70"),
        "b": Decimal("10"),
        "c": Decimal("0"),
        "d": Decimal("40"),
        "e": Decimal("25"),
    }
    moved = metrics.movements(before, after, paid_earlier={"d"})
    assert (moved.new, moved.reactivation) == (Decimal("25"), Decimal("40"))
    assert (moved.expansion, moved.contraction, moved.churn) == (
        Decimal("20"),
        Decimal("20"),
        Decimal("20"),
    )
    assert (moved.customers_start, moved.customers_end) == (3, 4)
    assert (moved.customers_new, moved.customers_churned) == (2, 1)


def _month(day: str, states: dict[str, tuple[str, str]]) -> tuple[date, dict[str, OrgMonth]]:
    return date.fromisoformat(day), {o: OrgMonth(s, Decimal(v)) for o, (s, v) in states.items()}


def test_monthly_series_rates_and_arpa():
    months = [
        _month(
            "2026-07-31", {"a": ("active", "100"), "b": ("active", "50"), "t": ("trialing", "0")}
        ),
        _month(
            "2026-08-31", {"a": ("active", "120"), "b": ("cancelled", "50"), "t": ("active", "30")}
        ),
        _month("2026-09-30", {"a": ("past_due", "120"), "t": ("active", "30")}),
    ]
    first_paid = {"a": date(2026, 1, 5), "b": date(2026, 3, 1), "t": date(2026, 8, 20)}
    rows = metrics.monthly_series(months, currency="GBP", first_paid=first_paid)
    july, august, september = rows
    assert (july.mrr, july.customers, july.trialing) == (Decimal("150"), 2, 1)
    assert july.logo_churn_rate is None
    assert august.mrr == Decimal("150")  # 120 + 30; b's cancellation counts as churn
    assert august.arr == Decimal("1800")
    assert august.arpa == Decimal("75.00")
    m = august.movements
    assert (m.new, m.expansion, m.churn) == (Decimal("30"), Decimal("20"), Decimal("50"))
    assert august.logo_churn_rate == Decimal("0.5000")
    assert august.revenue_churn_rate == Decimal("0.3333")  # 50 / 150
    assert august.net_revenue_retention == Decimal("0.8000")  # (150 + 20 - 50) / 150
    assert september.past_due_mrr == Decimal("120")  # still MRR, flagged for dunning
    assert september.movements.net_new == Decimal("0")


@given(
    st.lists(
        st.tuples(st.integers(min_value=1, max_value=12), st.booleans(), st.booleans()), max_size=40
    )
)
def test_trial_conversion_counts_only_trials(rows):
    orgs = [(date(2026, m, 3), trialed, paid) for m, trialed, paid in rows]
    cohorts = metrics.trial_conversion(orgs)
    assert sum(c.trials for c in cohorts) == sum(1 for _d, t, _p in orgs if t)
    for cohort in cohorts:
        assert 0 <= cohort.converted <= cohort.trials
        assert cohort.rate is not None
        assert Decimal(0) <= cohort.rate <= Decimal(1)


def test_cohort_retention_by_first_paying_month():
    months = [
        _month("2026-07-31", {"a": ("active", "100"), "b": ("active", "100")}),
        _month(
            "2026-08-31", {"a": ("active", "150"), "b": ("cancelled", "100"), "c": ("active", "40")}
        ),
        _month("2026-09-30", {"a": ("active", "150"), "c": ("active", "40")}),
    ]
    first_paid = {
        "a": date(2026, 7, 2),
        "b": date(2026, 7, 9),
        "c": date(2026, 8, 1),
        "z": date(2025, 1, 1),
    }
    july, august = metrics.cohort_retention(months, first_paid)
    assert (july.month, july.size, july.starting_mrr) == (date(2026, 7, 1), 2, Decimal("200"))
    assert july.logos == [Decimal("1.0000"), Decimal("0.5000"), Decimal("0.5000")]
    assert july.revenue == [Decimal("1.0000"), Decimal("0.7500"), Decimal("0.7500")]
    assert (august.size, august.logos) == (1, [Decimal("1.0000"), Decimal("1.0000")])


@given(amounts, st.integers(min_value=0, max_value=1000))
def test_arpa_rounds_half_up(mrr, customers):
    value = metrics.arpa(mrr, customers, "GBP")
    if customers == 0:
        assert value == 0
    else:
        assert value == value.quantize(Decimal("0.01"))
        assert abs(value * customers - mrr) <= Decimal("0.005") * customers


# --- health score -------------------------------------------------------------------------------

inputs = st.builds(
    health.HealthInputs,
    modules_used=st.integers(0, 6),
    staff_total=st.integers(0, 50),
    staff_active=st.integers(0, 50),
    tutors_now=st.integers(0, 200),
    tutors_before=st.integers(0, 200),
    payments_now=st.integers(0, 2000),
    payments_before=st.integers(0, 2000),
    errors=st.integers(0, 100),
    support_conversations=st.integers(0, 20),
    nps=st.one_of(st.none(), st.integers(-100, 100)),
)


@given(inputs)
def test_health_score_is_bounded_and_consistent(value):
    score, risk, parts = health.score(value)
    assert 0 <= score <= 100
    assert risk == health.risk_for(score)
    assert all(v is None or 0 <= v <= 100 for v in parts.values())


@given(inputs, st.integers(1, 20))
def test_more_errors_never_raise_the_score(value, extra):
    from dataclasses import replace

    worse = replace(value, errors=value.errors + extra)
    assert health.score(worse)[0] <= health.score(value)[0]


def test_health_worked_example():
    busy = health.HealthInputs(
        modules_used=6,
        staff_total=4,
        staff_active=4,
        tutors_now=10,
        tutors_before=10,
        payments_now=80,
        payments_before=60,
        errors=0,
        support_conversations=0,
        nps=50,
    )
    score, risk, parts = health.score(busy)
    assert parts == {
        "usage": 100,
        "tutors": 100,
        "payments": 100,
        "reliability": 100,
        "support": 100,
        "nps": 75,
    }
    assert (score, risk) == (98, "healthy")  # (90 x 100 + 10 x 75) / 100 = 97.5 -> 98
    idle = health.HealthInputs(staff_total=2, errors=3, support_conversations=2)
    score, risk, parts = health.score(idle)
    assert parts["payments"] is None
    assert parts["nps"] is None  # left out, weights rescaled
    assert risk == "at_risk"


def test_nps_formula():
    assert health.nps([]) is None
    assert health.nps([10, 9, 8, 7, 6, 0]) == 0  # 2 promoters, 2 detractors of 6
    assert health.nps([10, 10, 9]) == 100
    assert health.nps([10, 3, 5]) == -33
