"""Pure course pricing (E20-T04): discounts, proration, instalments and teacher pay.

Everything here works on values (no database), so the money rules are tested with
Hypothesis (``tests/test_pricing.py``):

* **Discounts** (E06 rules of kind ``sibling``, ``multi_class``, ``client``, ``scholarship``)
  follow the rate engine's stacking: highest priority first, a non-stackable first match
  applies alone; percentages come off the list price; amounts are rounded half-up per step
  and never go below zero.
* **Proration** charges ``fee * remaining / total`` rounded half-up, where the units are
  sessions or teaching weeks (weeks that lie entirely inside breaks don't count).
* **Instalments** split a fee exactly (largest remainder) into monthly parts.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from tutortrack.core.money import Money

HOUR = Decimal(60)
HUNDRED = Decimal(100)


@dataclass(frozen=True)
class CourseDiscount:
    name: str
    kind: str  # sibling | multi_class | client | scholarship
    percent: Decimal | None = None
    fixed_amount: Money | None = None
    priority: int = 0
    stackable: bool = True
    threshold: int = 2  # sibling: from the n-th child; multi_class: from n classes
    client_id: str | None = None
    student_id: str | None = None


@dataclass(frozen=True)
class Facts:
    """Who is enrolling: their position among siblings enrolled this term (1 = first child)
    and how many classes they take this term (including this one)."""

    sibling_position: int = 1
    classes_this_term: int = 1
    client_id: str = ""
    student_id: str = ""


@dataclass(frozen=True)
class Quote:
    list_price: Money
    price: Money
    discounts: tuple[tuple[str, Money], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "list_price": self.list_price.to_dict(),
            "price": self.price.to_dict(),
            "discounts": [{"name": n, "amount": a.to_dict()} for n, a in self.discounts],
        }


def applies(d: CourseDiscount, facts: Facts) -> bool:
    if d.kind == "sibling":
        return facts.sibling_position >= max(d.threshold, 2)
    if d.kind == "multi_class":
        return facts.classes_this_term >= max(d.threshold, 2)
    if d.kind == "client":
        return d.client_id is not None and d.client_id == facts.client_id
    if d.kind == "scholarship":
        return (d.student_id is not None and d.student_id == facts.student_id) or (
            d.client_id is not None and d.client_id == facts.client_id
        )
    return False


def pick(matches: Sequence[CourseDiscount]) -> list[CourseDiscount]:
    ordered = sorted(matches, key=lambda r: (-r.priority, r.name))
    if not ordered:
        return []
    if not ordered[0].stackable:
        return ordered[:1]
    return [r for r in ordered if r.stackable]


def quote(list_price: Money, discounts: Iterable[CourseDiscount], facts: Facts) -> Quote:
    base = list_price.round_to_minor()
    amount = base
    applied: list[tuple[str, Money]] = []
    for d in pick([d for d in discounts if applies(d, facts)]):
        before = amount
        if d.percent:
            amount = amount - (base * (d.percent / HUNDRED)).round_to_minor()
        if d.fixed_amount is not None and d.fixed_amount.currency == base.currency:
            amount = amount - d.fixed_amount.round_to_minor()
        if amount.is_negative():
            amount = Money.zero(base.currency)
        if amount != before:
            applied.append((d.name, amount - before))
    return Quote(base, amount, tuple(applied))


# --- proration ----------------------------------------------------------------------------------


def prorate(fee: Money, *, total: int, remaining: int) -> Money:
    """The share of ``fee`` for ``remaining`` of ``total`` units, rounded half-up."""
    fee = fee.round_to_minor()
    if total <= 0 or remaining >= total:
        return fee
    if remaining <= 0:
        return Money.zero(fee.currency)
    return (fee * Decimal(remaining) / Decimal(total)).round_to_minor()


def _in_breaks(day: date, breaks: Sequence[tuple[date, date]]) -> bool:
    return any(start <= day <= end for start, end in breaks)


def teaching_weeks(start: date, end: date, breaks: Sequence[tuple[date, date]]) -> list[date]:
    """The class's weeks (7-day blocks from ``start`` to ``end``) with at least one day that
    isn't in a break: holiday weeks don't count for proration. Returns each week's first
    day."""
    weeks: list[date] = []
    first = start
    while first <= end:
        days = (first + timedelta(days=i) for i in range(7))
        if any(d <= end and not _in_breaks(d, breaks) for d in days):
            weeks.append(first)
        first += timedelta(days=7)
    return weeks


def week_units(
    start: date, end: date, breaks: Sequence[tuple[date, date]], joining: date
) -> tuple[int, int]:
    """(teaching weeks in the class, teaching weeks starting on or after ``joining``)."""
    weeks = teaching_weeks(start, end, breaks)
    return len(weeks), sum(1 for w in weeks if w >= joining)


def session_units(session_dates: Sequence[date], joining: date) -> tuple[int, int]:
    """(sessions in the class, sessions on or after ``joining``)."""
    return len(session_dates), sum(1 for d in session_dates if d >= joining)


# --- instalments --------------------------------------------------------------------------------


def add_months(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(day.day, last))


def instalments(fee: Money, count: int, first: date) -> list[tuple[date, Money]]:
    """``count`` monthly parts from ``first`` that add up to ``fee`` exactly."""
    count = max(int(count), 1)
    parts = fee.round_to_minor().allocate([1] * count)
    return [(add_months(first, i), part) for i, part in enumerate(parts)]


# --- per-session amounts and rates --------------------------------------------------------------


def rate_for(amount: Money, *, per_hour: bool, minutes: int) -> Money:
    """The rate (4 dp) that prices one session of ``minutes`` at ``amount``."""
    if not per_hour:
        return amount
    rate = (amount.amount * HOUR / Decimal(minutes)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return Money(rate, amount.currency)


def teacher_session_pay(
    mode: str,
    config: dict[str, Any],
    currency: str,
    *,
    headcount: int,
    sessions: int,
    index: int,
) -> Money | None:
    """What a teacher earns for session ``index`` (0-based) of ``sessions``:
    ``per_session`` a fixed amount; ``headcount`` the highest tier whose ``from`` the
    roster reaches; ``fixed`` the class total split evenly (exactly) over the sessions;
    ``service`` (or nothing set) None: the usual tutor rates apply."""
    if mode == "per_session" and config.get("amount") not in (None, ""):
        return Money(Decimal(str(config["amount"])), currency).round_to_minor()
    if mode == "headcount":
        tiers = sorted(
            (int(t.get("from", 0)), str(t.get("amount", "0"))) for t in config.get("tiers") or []
        )
        chosen = None
        for start, amount in tiers:
            if headcount >= start:
                chosen = amount
        return Money(Decimal(chosen), currency).round_to_minor() if chosen is not None else None
    if mode == "fixed" and config.get("amount") not in (None, "") and sessions > 0:
        parts = Money(Decimal(str(config["amount"])), currency).allocate([1] * sessions)
        return parts[min(max(index, 0), sessions - 1)]
    return None
