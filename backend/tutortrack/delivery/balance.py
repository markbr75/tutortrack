"""Negative-balance prevention (FR-09-1), supplied by billing (E10).

Delivery comes before billing in the build order, so billing registers a guard here
(``set_guard``) instead of delivery importing billing. Until then nothing is blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from tutortrack.core.money import Money


@dataclass(frozen=True)
class Shortfall:
    client_id: str
    client_name: str
    available: Money
    needed: Money


class BalanceGuard(Protocol):
    def shortfalls(self, lesson: Any, charges: list[tuple[Any, Decimal]]) -> list[Shortfall]:
        """``charges``: (LessonAttendee, charge percent) for each chargeable attendee."""
        ...


class _NoGuard:
    def shortfalls(self, lesson: Any, charges: list[tuple[Any, Decimal]]) -> list[Shortfall]:
        return []


_guard: BalanceGuard = _NoGuard()


def set_guard(guard: BalanceGuard) -> None:
    global _guard
    _guard = guard


def guard() -> BalanceGuard:
    return _guard
