"""Public holiday rules for importing into holiday calendars (E06-T08).

GB is England and Wales bank holidays; US is federal holidays. Other countries start with
an empty calendar that admins fill in (or import from a CSV through E28). One-off holidays
(coronations, jubilees) are added by hand.
"""

from __future__ import annotations

from datetime import date, timedelta

from dateutil.easter import easter


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th ``weekday`` (Monday = 0) of the month; n = -1 for the last."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _substitute(day: date, taken: set[date]) -> date:
    """Weekend holidays move to the next free weekday (UK practice)."""
    while day.weekday() >= 5 or day in taken:
        day += timedelta(days=1)
    return day


def _gb(year: int) -> list[tuple[date, str]]:
    days: list[tuple[date, str]] = []
    taken: set[date] = set()
    new_year = _substitute(date(year, 1, 1), taken)
    taken.add(new_year)
    days.append((new_year, "New Year's Day"))
    e = easter(year)
    days += [(e - timedelta(days=2), "Good Friday"), (e + timedelta(days=1), "Easter Monday")]
    days += [
        (_nth_weekday(year, 5, 0, 1), "Early May bank holiday"),
        (_nth_weekday(year, 5, 0, -1), "Spring bank holiday"),
        (_nth_weekday(year, 8, 0, -1), "Summer bank holiday"),
    ]
    christmas = _substitute(date(year, 12, 25), taken)
    taken.add(christmas)
    boxing = _substitute(date(year, 12, 26), taken)
    days += [(christmas, "Christmas Day"), (boxing, "Boxing Day")]
    return days


def _observed_us(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _us(year: int) -> list[tuple[date, str]]:
    return [
        (_observed_us(date(year, 1, 1)), "New Year's Day"),
        (_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"),
        (_nth_weekday(year, 2, 0, 3), "Washington's Birthday"),
        (_nth_weekday(year, 5, 0, -1), "Memorial Day"),
        (_observed_us(date(year, 6, 19)), "Juneteenth"),
        (_observed_us(date(year, 7, 4)), "Independence Day"),
        (_nth_weekday(year, 9, 0, 1), "Labor Day"),
        (_nth_weekday(year, 10, 0, 2), "Columbus Day"),
        (_observed_us(date(year, 11, 11)), "Veterans Day"),
        (_nth_weekday(year, 11, 3, 4), "Thanksgiving Day"),
        (_observed_us(date(year, 12, 25)), "Christmas Day"),
    ]


RULES = {"GB": _gb, "UK": _gb, "US": _us}


def public_holidays(country: str, year: int) -> list[tuple[date, str]]:
    rule = RULES.get(country.upper())
    return sorted(rule(year)) if rule else []


def supported(country: str) -> bool:
    return country.upper() in RULES
