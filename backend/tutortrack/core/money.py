"""Money value object. Floats are never used for money.

Rules (docs/02-architecture.md §4):
* amounts are ``Decimal``; currency is an ISO 4217 code
* rounding is ROUND_HALF_UP to the currency's minor unit, applied at line level
* ``allocate`` splits an amount by ratios without losing or creating minor units
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import cache, total_ordering
from typing import Any

from babel.numbers import format_currency, get_currency_precision, list_currencies

Number = Decimal | int


class CurrencyMismatch(ValueError):
    pass


@cache
def _known_currencies() -> frozenset[str]:
    return frozenset(list_currencies())


def validate_currency(code: str) -> str:
    code = (code or "").upper()
    if code not in _known_currencies():
        raise ValueError(f"Unknown currency code: {code!r}")
    return code


@cache
def minor_units(currency: str) -> int:
    """Number of decimal places for a currency (GBP 2, JPY 0, KWD 3)."""
    return int(get_currency_precision(validate_currency(currency)))


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, bool | float):
        raise TypeError("Money amounts must be Decimal, int or str, never float/bool")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise TypeError(f"Cannot convert {value!r} to Decimal") from exc


@total_ordering
@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _to_decimal(self.amount))
        object.__setattr__(self, "currency", validate_currency(self.currency))

    # --- constructors --------------------------------------------------------------------------
    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(Decimal(0), currency)

    @classmethod
    def from_minor(cls, minor: int, currency: str) -> Money:
        return cls(Decimal(minor).scaleb(-minor_units(currency)), currency)

    # --- conversion ----------------------------------------------------------------------------
    @property
    def minor_units(self) -> int:
        return minor_units(self.currency)

    def round_to_minor(self) -> Money:
        quantum = Decimal(1).scaleb(-self.minor_units)
        return Money(self.amount.quantize(quantum, rounding=ROUND_HALF_UP), self.currency)

    def to_minor(self) -> int:
        """Integer minor units (pence/cents) after half-up rounding."""
        return int(self.round_to_minor().amount.scaleb(self.minor_units))

    def is_rounded(self) -> bool:
        return self.amount == self.round_to_minor().amount

    def format(self, locale: str = "en_GB") -> str:
        return str(format_currency(self.amount, self.currency, locale=locale))

    def to_dict(self) -> dict[str, str]:
        return {"amount": str(self.amount), "currency": self.currency}

    # --- predicates ----------------------------------------------------------------------------
    def is_zero(self) -> bool:
        return self.amount == 0

    def is_positive(self) -> bool:
        return self.amount > 0

    def is_negative(self) -> bool:
        return self.amount < 0

    # --- arithmetic ----------------------------------------------------------------------------
    def _check(self, other: object) -> Money:
        if not isinstance(other, Money):
            raise TypeError(f"Expected Money, got {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(f"{self.currency} vs {other.currency}")
        return other

    def __add__(self, other: Money) -> Money:
        return Money(self.amount + self._check(other).amount, self.currency)

    def __radd__(self, other: Any) -> Money:
        # Allows sum([...], Money.zero("GBP")) and sum() starting from int 0.
        if other == 0 and not isinstance(other, Money):
            return self
        return self.__add__(other)

    def __sub__(self, other: Money) -> Money:
        return Money(self.amount - self._check(other).amount, self.currency)

    def __mul__(self, factor: Number) -> Money:
        if isinstance(factor, Money):
            raise TypeError("Cannot multiply Money by Money")
        return Money(self.amount * _to_decimal(factor), self.currency)

    __rmul__ = __mul__

    def __truediv__(self, divisor: Number) -> Money:
        if isinstance(divisor, Money):
            raise TypeError("Use ratio() to divide Money by Money")
        return Money(self.amount / _to_decimal(divisor), self.currency)

    def ratio(self, other: Money) -> Decimal:
        return self.amount / self._check(other).amount

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    def __lt__(self, other: Money) -> bool:
        return self.amount < self._check(other).amount

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.currency == other.currency and self.amount == other.amount

    def __hash__(self) -> int:
        return hash((self.amount.normalize(), self.currency))

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    # --- allocation ----------------------------------------------------------------------------
    def allocate(self, ratios: Sequence[Number]) -> list[Money]:
        """Split into parts proportional to ``ratios`` using largest-remainder.

        The amount is first rounded to minor units; the parts always sum exactly to it.
        Ties in remainders go to the earliest ratio, so results are deterministic.
        """
        if not ratios:
            raise ValueError("At least one ratio is required")
        weights = [_to_decimal(r) for r in ratios]
        if any(w < 0 for w in weights):
            raise ValueError("Ratios must be non-negative")
        total_weight = sum(weights, Decimal(0))
        if total_weight == 0:
            raise ValueError("Ratios must not all be zero")

        total = self.to_minor()
        sign = -1 if total < 0 else 1
        remaining_total = abs(total)

        exact = [Decimal(remaining_total) * w / total_weight for w in weights]
        shares = [int(e) for e in exact]  # floor for non-negative values
        leftover = remaining_total - sum(shares)
        order = sorted(range(len(exact)), key=lambda i: (-(exact[i] - shares[i]), i))
        for i in order[:leftover]:
            shares[i] += 1
        return [Money.from_minor(sign * s, self.currency) for s in shares]


def sum_money(values: Iterable[Money], currency: str) -> Money:
    """Sum Money values; returns zero in ``currency`` for an empty iterable."""
    total = Money.zero(currency)
    for value in values:
        total = total + value
    return total
