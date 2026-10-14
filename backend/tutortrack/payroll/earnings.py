"""Annual earnings summary for tutors (FR-12-9 "annual earnings summary for tax returns",
gap G3): what a tutor was paid in a year, by kind and by month, as JSON and PDF.

"Paid in the year" means pay items whose payout was paid in the period (the payout's paid
date in the organisation's time zone), the same rule as the US 1099 figures. The period is
the calendar year, or the UK tax year (6 April to 5 April) when ``basis="tax_year"`` (the
default for organisations in the United Kingdom). Expense and mileage reimbursements are
shown apart from earnings: they repay costs. Amounts are sums of rounded items, per
currency. This is a summary to help with a tax return, not a tax document.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.utils.translation import gettext as _

from tutortrack.core.money import Money
from tutortrack.people.models import TutorProfile

from .models import PayItem, Payout

REIMBURSEMENTS = (PayItem.Kind.EXPENSE, PayItem.Kind.MILEAGE)
BASES = ("calendar", "tax_year")


@dataclass
class CurrencySummary:
    currency: str
    earnings: Money
    reimbursements: Money
    total: Money
    by_kind: list[dict[str, Any]] = field(default_factory=list)
    by_month: list[dict[str, Any]] = field(default_factory=list)
    payouts: int = 0


@dataclass
class AnnualSummary:
    tutor: TutorProfile
    year: int
    basis: str
    start: date
    end: date
    currencies: list[CurrencySummary] = field(default_factory=list)


def default_basis() -> str:
    from .services import _org

    return "tax_year" if str(_org().country).upper() == "GB" else "calendar"


def period(year: int, basis: str) -> tuple[date, date]:
    """``(first day, last day)``; a UK tax year is named by the year it starts in."""
    if basis == "tax_year":
        return date(year, 4, 6), date(year + 1, 4, 5)
    return date(year, 1, 1), date(year, 12, 31)


def summary(tutor: TutorProfile, year: int, basis: str | None = None) -> AnnualSummary:
    from datetime import timedelta

    from .services import _org

    basis = basis if basis in BASES else default_basis()
    start, end = period(year, basis)
    zone = ZoneInfo(_org().timezone)
    since = datetime.combine(start, time.min, tzinfo=zone)
    until = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone)
    items = PayItem.objects.filter(
        tutor=tutor,
        status=PayItem.Status.PAID,
        payout__status=Payout.Status.PAID,
        payout__paid_at__gte=since,
        payout__paid_at__lt=until,
    ).select_related("payout")
    kinds: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    months: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    payouts: dict[str, set[Any]] = defaultdict(set)
    earned: dict[str, Decimal] = defaultdict(Decimal)
    repaid: dict[str, Decimal] = defaultdict(Decimal)
    for item in items:
        cur = item.currency
        amount = item.amount.amount
        kinds[cur][item.kind] += amount
        paid = item.payout.paid_at.astimezone(zone) if item.payout and item.payout.paid_at else None
        if paid is not None:
            months[cur][f"{paid.year:04d}-{paid.month:02d}"] += amount
        payouts[cur].add(item.payout_id)
        if item.kind in REIMBURSEMENTS:
            repaid[cur] += amount
        else:
            earned[cur] += amount
    labels = dict(PayItem.Kind.choices)
    out = []
    for cur in sorted(kinds):
        out.append(
            CurrencySummary(
                currency=cur,
                earnings=Money(earned[cur], cur).round_to_minor(),
                reimbursements=Money(repaid[cur], cur).round_to_minor(),
                total=Money(earned[cur] + repaid[cur], cur).round_to_minor(),
                by_kind=[
                    {
                        "kind": kind,
                        "label": str(labels.get(kind, kind)),
                        "amount": Money(value, cur).round_to_minor(),
                        "reimbursement": kind in REIMBURSEMENTS,
                    }
                    for kind, value in sorted(kinds[cur].items())
                ],
                by_month=[
                    {"month": month, "amount": Money(value, cur).round_to_minor()}
                    for month, value in sorted(months[cur].items())
                ],
                payouts=len(payouts[cur]),
            )
        )
    return AnnualSummary(tutor, year, basis, start, end, out)


def pdf(data: AnnualSummary) -> bytes:
    from django.template.loader import render_to_string
    from django.utils import translation
    from weasyprint import HTML

    from tutortrack.core import branding

    from .services import _org

    org = _org()
    locale = str(org.locale or "en-GB")
    with translation.override(locale):
        fmt_locale = locale.replace("-", "_")
        html = render_to_string(
            "payroll/annual_summary.html",
            {
                "summary": data,
                "org": org,
                "title": _("Earnings summary"),
                "rows": [
                    {
                        "currency": c.currency,
                        "earnings": c.earnings.format(fmt_locale),
                        "reimbursements": c.reimbursements.format(fmt_locale),
                        "total": c.total.format(fmt_locale),
                        "payouts": c.payouts,
                        "by_kind": [
                            {**k, "amount": k["amount"].format(fmt_locale)} for k in c.by_kind
                        ],
                        "by_month": [
                            {**m, "amount": m["amount"].format(fmt_locale)} for m in c.by_month
                        ],
                    }
                    for c in data.currencies
                ],
                "brand": branding.for_documents(org.pk),
            },
        )
    return bytes(HTML(string=html).write_pdf())
