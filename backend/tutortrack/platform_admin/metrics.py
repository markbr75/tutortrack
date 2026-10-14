"""SaaS metrics maths (E30 FR-30-7): MRR/ARR, MRR movements, churn, net revenue retention,
ARPA, trial conversion and cohort retention. Pure functions over ``Decimal``s (money is
rounded half-up to the currency's minor unit with ``core.money``); the platform selectors
feed them month-end subscription snapshots read across organisations.

Definitions (one currency at a time; organisations are never converted between
currencies):

* **MRR** of an organisation at a month end: its subscription's monthly value on its last
  snapshot that month if the status is ``active`` or ``past_due``, else 0. Annual prices
  count as a twelfth.
* **Movements** from month A to month B per organisation (``a`` → ``b``): new (0 → >0, never
  paid before), reactivation (0 → >0, paid before), expansion (b > a > 0), contraction
  (a > b > 0), churn (a > 0 → 0). Always: ``end = start + new + reactivation + expansion -
  contraction - churn``.
* **Logo churn** = customers lost / customers at the start; **gross revenue churn** =
  (churn + contraction) / starting MRR; **NRR** = (start + expansion - contraction -
  churn) / starting MRR.
* **ARPA** = MRR / paying customers. **ARR** = 12 x MRR.
* **Trial conversion** per sign-up month: trials that ever became paying / trials.
* **Cohort retention**: organisations grouped by their first paying month; the share still
  paying (logos) and the share of the starting MRR still billed (revenue) k months later.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from tutortrack.core.money import Money

PAYING = frozenset({"active", "past_due"})
ZERO = Decimal(0)
RATE = Decimal("0.0001")  # rates are fractions with 4 places (12.34%)


@dataclass(frozen=True)
class PriceComponent:
    component: str  # PlanPrice.Component
    unit_amount: Decimal
    included_quantity: int = 0


def subscription_mrr(
    prices: Iterable[PriceComponent], *, seats: int, branches: int, interval: str, currency: str
) -> Decimal:
    """Monthly value of one subscription from its plan's list prices: the base fee, active
    tutors and extra branches above the included quantity; annual prices / 12. Revenue
    share depends on payments processed and is left out (``revenue_share``)."""
    total = ZERO
    for price in prices:
        if price.component == "base_fee":
            total += price.unit_amount
        elif price.component == "active_tutor":
            total += price.unit_amount * max(0, seats - price.included_quantity)
        elif price.component == "branch":
            total += price.unit_amount * max(0, branches - price.included_quantity)
    if interval == "year":
        total /= 12
    return Money(total, currency).round_to_minor().amount


def org_mrr(status: str, mrr: Decimal) -> Decimal:
    return mrr if status in PAYING and mrr > 0 else ZERO


def rate(part: Decimal | int, whole: Decimal | int) -> Decimal | None:
    if not whole:
        return None
    return (Decimal(part) / Decimal(whole)).quantize(RATE, rounding=ROUND_HALF_UP)


def arpa(mrr: Decimal, customers: int, currency: str) -> Decimal:
    if not customers:
        return ZERO
    return Money(mrr / customers, currency).round_to_minor().amount


@dataclass
class Movements:
    start: Decimal = ZERO
    new: Decimal = ZERO
    reactivation: Decimal = ZERO
    expansion: Decimal = ZERO
    contraction: Decimal = ZERO
    churn: Decimal = ZERO
    end: Decimal = ZERO
    customers_start: int = 0
    customers_end: int = 0
    customers_new: int = 0
    customers_churned: int = 0

    @property
    def net_new(self) -> Decimal:
        return self.new + self.reactivation + self.expansion - self.contraction - self.churn


def movements(
    before: Mapping[str, Decimal], after: Mapping[str, Decimal], *, paid_earlier: set[str]
) -> Movements:
    """MRR movements between two month ends. ``before``/``after`` map organisation ids to
    MRR (missing = 0); ``paid_earlier`` holds organisations that paid before ``before``."""
    out = Movements()
    for org in set(before) | set(after):
        a = before.get(org, ZERO)
        b = after.get(org, ZERO)
        out.start += a
        out.end += b
        out.customers_start += a > 0
        out.customers_end += b > 0
        if a == 0 and b > 0:
            out.customers_new += 1
            if org in paid_earlier:
                out.reactivation += b
            else:
                out.new += b
        elif a > 0 and b == 0:
            out.churn += a
            out.customers_churned += 1
        elif b > a:
            out.expansion += b - a
        elif a > b:
            out.contraction += a - b
    return out


@dataclass
class MonthRow:
    month: date
    mrr: Decimal
    arr: Decimal
    customers: int
    arpa: Decimal
    trialing: int
    past_due_mrr: Decimal
    movements: Movements
    logo_churn_rate: Decimal | None
    revenue_churn_rate: Decimal | None
    net_revenue_retention: Decimal | None


@dataclass(frozen=True)
class OrgMonth:
    status: str
    mrr: Decimal


def monthly_series(
    months: Sequence[tuple[date, Mapping[str, OrgMonth]]],
    *,
    currency: str,
    first_paid: Mapping[str, date],
) -> list[MonthRow]:
    """One row per month end, oldest first. ``months`` must be in order; the first month
    only provides the starting point for the second's movements."""
    rows: list[MonthRow] = []
    previous: dict[str, Decimal] = {}
    for index, (month, states) in enumerate(months):
        current = {org: org_mrr(s.status, s.mrr) for org, s in states.items()}
        paid_earlier = {org for org, first in first_paid.items() if first < _month_start(month)}
        moved = movements(previous, current, paid_earlier=paid_earlier) if index else Movements()
        if not index:
            moved.end = sum(current.values(), ZERO)
            moved.customers_end = sum(1 for v in current.values() if v > 0)
        mrr = moved.end
        customers = moved.customers_end
        rows.append(
            MonthRow(
                month=month,
                mrr=mrr,
                arr=mrr * 12,
                customers=customers,
                arpa=arpa(mrr, customers, currency),
                trialing=sum(1 for s in states.values() if s.status == "trialing"),
                past_due_mrr=sum(
                    (org_mrr(s.status, s.mrr) for s in states.values() if s.status == "past_due"),
                    ZERO,
                ),
                movements=moved,
                logo_churn_rate=rate(moved.customers_churned, moved.customers_start)
                if index
                else None,
                revenue_churn_rate=rate(moved.churn + moved.contraction, moved.start)
                if index
                else None,
                net_revenue_retention=rate(
                    moved.start + moved.expansion - moved.contraction - moved.churn, moved.start
                )
                if index
                else None,
            )
        )
        previous = current
    return rows


def _month_start(month_end: date) -> date:
    return month_end.replace(day=1)


@dataclass
class TrialCohort:
    month: date
    trials: int = 0
    converted: int = 0

    @property
    def rate(self) -> Decimal | None:
        return rate(self.converted, self.trials)


def trial_conversion(orgs: Iterable[tuple[date | None, bool, bool]]) -> list[TrialCohort]:
    """``orgs``: (sign-up date, ever trialing, ever paying). Grouped by sign-up month."""
    cohorts: dict[date, TrialCohort] = {}
    for signed_up, trialed, paid in orgs:
        if signed_up is None or not trialed:
            continue
        key = signed_up.replace(day=1)
        cohort = cohorts.setdefault(key, TrialCohort(key))
        cohort.trials += 1
        cohort.converted += bool(paid)
    return [cohorts[k] for k in sorted(cohorts)]


@dataclass
class RetentionCohort:
    month: date
    size: int
    starting_mrr: Decimal
    logos: list[Decimal | None] = field(default_factory=list)  # share still paying, k=0..
    revenue: list[Decimal | None] = field(default_factory=list)  # share of starting MRR


def cohort_retention(
    months: Sequence[tuple[date, Mapping[str, OrgMonth]]], first_paid: Mapping[str, date]
) -> list[RetentionCohort]:
    """Cohorts by first paying month (only months inside ``months``)."""
    index = {_month_start(m): i for i, (m, _states) in enumerate(months)}
    mrr_at = [{o: org_mrr(s.status, s.mrr) for o, s in states.items()} for _m, states in months]
    members: dict[int, list[str]] = {}
    for org, first in first_paid.items():
        i = index.get(first.replace(day=1))
        if i is not None:
            members.setdefault(i, []).append(org)
    out = []
    for i in sorted(members):
        orgs = members[i]
        start = sum((mrr_at[i].get(o, ZERO) for o in orgs), ZERO)
        cohort = RetentionCohort(_month_start(months[i][0]), len(orgs), start)
        for k in range(i, len(months)):
            current = mrr_at[k]
            paying = sum(1 for o in orgs if current.get(o, ZERO) > 0)
            billed = sum((current.get(o, ZERO) for o in orgs), ZERO)
            cohort.logos.append(rate(paying, len(orgs)))
            cohort.revenue.append(rate(billed, start))
        out.append(cohort)
    return out


def as_money(amount: Decimal, currency: str) -> dict[str, Any]:
    return Money(amount, currency).round_to_minor().to_dict()
