"""Commission arithmetic (FR-25-3), kept pure for property tests.

* ``commission_for``: percentage of collected revenue, rounded half-up to the minor unit
  (line level, like every money line).
* ``clawback_for``: the negative item for a refund: the refund at the original rate, never
  more than what is still left of the commission earned on that payment.
* ``tier_percent``: tiered rates: the highest tier the affiliate's converted clients reach.
* ``in_window``: "for N months" from attribution (calendar months, ``None`` = lifetime).
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

from tutortrack.core.money import Money

HUNDRED = Decimal(100)


def commission_for(base: Money, percent: Decimal) -> Money:
    """``percent`` % of ``base`` (half-up to the currency's minor unit)."""
    if percent < 0 or percent > HUNDRED:
        raise ValueError("Commission rates run from 0 to 100%.")
    return (base * (Decimal(percent) / HUNDRED)).round_to_minor()


def clawback_for(refund: Money, percent: Decimal, earned: Money, clawed: Money) -> Money:
    """The (negative or zero) clawback for ``refund`` of a payment that earned ``earned``
    at ``percent``, given ``clawed`` (a positive total) already taken back."""
    if refund.is_negative():
        raise ValueError("A refund is a positive amount.")
    left = earned - clawed
    if not left.is_positive():
        return Money.zero(refund.currency)
    wanted = commission_for(refund, percent)
    return -min(wanted, left)


def tier_percent(base_percent: Decimal, tiers: Iterable[dict[str, Any]], converted: int) -> Decimal:
    """The rate for an affiliate with ``converted`` clients: the base rate, or the highest
    tier whose ``from_clients`` they have reached."""
    best = (0, Decimal(base_percent))
    for tier in tiers:
        threshold = int(tier.get("from_clients") or 0)
        if converted >= threshold and threshold >= best[0]:
            best = (threshold, Decimal(str(tier.get("percent"))))
    return best[1]


def add_months(moment: datetime, months: int) -> datetime:
    month0 = moment.month - 1 + months
    year, month = moment.year + month0 // 12, month0 % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def in_window(attributed_at: datetime, months: int | None, at: datetime) -> bool:
    """Whether revenue at ``at`` still earns commission ``months`` after attribution."""
    if at < attributed_at:
        return True  # money received before the paperwork caught up
    return months is None or at < add_months(attributed_at, months)


def validate_tiers(tiers: Any) -> list[dict[str, str | int]]:
    """Normalise ``[{"from_clients": int, "percent": decimal}]``; raises ``ValueError``."""
    if tiers in (None, ""):
        return []
    if not isinstance(tiers, list):
        raise ValueError("Tiers are a list.")
    out: list[dict[str, str | int]] = []
    for tier in tiers:
        if not isinstance(tier, dict):
            raise ValueError("Each tier has from_clients and percent.")
        threshold = int(tier.get("from_clients") or 0)
        percent = Decimal(str(tier.get("percent")))
        if threshold < 1 or not Decimal(0) <= percent <= HUNDRED:
            raise ValueError("Tiers start from 1 client and rates run from 0 to 100%.")
        out.append({"from_clients": threshold, "percent": str(percent)})
    return sorted(out, key=lambda t: int(t["from_clients"]))
