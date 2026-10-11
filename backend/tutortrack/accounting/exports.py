"""General ledger exports for packages we don't sync with (E23-T08, FR-23-5): a generic
GL journal CSV (date, account, debit, credit, tax, reference), Sage 50 journal import,
MYOB general journal import and QuickBooks Desktop IIF. Date layouts follow each
package's import format, which is fixed by that package rather than the user's locale.

Postings come from ``journals`` (the same double entry as summary journals) using a
mapping set: ``export`` (codes typed in for the export) or a connected provider's.
"""

from __future__ import annotations

import csv
import io
from collections import OrderedDict
from datetime import date
from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

from . import journals
from .mappings import Mappings
from .models import AccountingConnection

FORMATS = ("generic", "sage50", "myob", "iif")


def _rows(provider: str, start: date, end: date, tz: str) -> list[journals.Posting]:
    conn = AccountingConnection.objects.filter(provider=provider).order_by("-created_at").first()
    maps = Mappings(provider, conn.chart if conn is not None else None)
    postings = journals.sales_postings(maps, start, end, tz) + journals.other_postings(
        maps, start, end, tz
    )
    return sorted(postings, key=lambda p: (p.date, p.source, p.credit > 0))


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _code(p: journals.Posting) -> str:
    return p.account.code or p.account.id


def export(fmt: str, *, provider: str, start: date, end: date, tz: str) -> tuple[str, str, bytes]:
    """``(filename, content type, content)``."""
    from .errors import MappingMissing

    if fmt not in FORMATS:
        raise BusinessRuleViolation(_("Unknown export format."))
    if end < start:
        raise BusinessRuleViolation(_("The period ends before it starts."))
    try:
        postings = _rows(provider, start, end, tz)
    except MappingMissing as exc:
        raise BusinessRuleViolation(str(exc)) from exc
    stem = f"gl-{start.isoformat()}-{end.isoformat()}"
    if fmt == "iif":
        return f"{stem}.iif", "text/plain; charset=utf-8", _iif(postings)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if fmt == "generic":
        writer.writerow(
            [
                "date",
                "journal",
                "account",
                "account_name",
                "debit",
                "credit",
                "tax_code",
                "tax",
                "currency",
                "reference",
                "description",
            ]
        )
        for p in postings:
            writer.writerow(
                [
                    p.date.isoformat(),
                    p.source,
                    _code(p),
                    p.account.name,
                    _money(p.debit),
                    _money(p.credit),
                    p.tax_code,
                    _money(p.tax),
                    p.currency,
                    p.reference,
                    p.description,
                ]
            )
    elif fmt == "sage50":
        writer.writerow(
            [
                "Type",
                "Account Reference",
                "Nominal A/C Ref",
                "Department Code",
                "Date",
                "Reference",
                "Details",
                "Net Amount",
                "Tax Code",
                "Tax Amount",
            ]
        )
        for p in postings:
            writer.writerow(
                [
                    "JD" if p.debit else "JC",
                    "",
                    _code(p),
                    "",
                    p.date.strftime("%d/%m/%Y"),
                    p.reference[:30],
                    p.description[:60],
                    _money(p.debit or p.credit),
                    p.tax_code or "T9",
                    "0.00",
                ]
            )
    else:  # myob
        writer.writerow(
            [
                "Journal Number",
                "Date",
                "Memo",
                "Account Number",
                "Debit Ex-Tax Amount",
                "Credit Ex-Tax Amount",
                "Tax Code",
                "Tax Amount",
            ]
        )
        numbers: OrderedDict[str, int] = OrderedDict()
        previous = ""
        for p in postings:
            if previous and p.source != previous:
                writer.writerow([])
            previous = p.source
            number = numbers.setdefault(p.source, len(numbers) + 1)
            writer.writerow(
                [
                    f"TT{number:06d}",
                    p.date.strftime("%d/%m/%Y"),
                    p.description[:255],
                    _code(p),
                    _money(p.debit) if p.debit else "",
                    _money(p.credit) if p.credit else "",
                    p.tax_code or "N-T",
                    "0.00",
                ]
            )
    return f"{stem}-{fmt}.csv", "text/csv; charset=utf-8", buffer.getvalue().encode()


def _iif(postings: list[journals.Posting]) -> bytes:
    lines = [
        "!TRNS\tTRNSTYPE\tDATE\tACCNT\tAMOUNT\tMEMO\tDOCNUM",
        "!SPL\tTRNSTYPE\tDATE\tACCNT\tAMOUNT\tMEMO\tDOCNUM",
        "!ENDTRNS",
    ]
    groups: OrderedDict[str, list[journals.Posting]] = OrderedDict()
    for p in postings:
        groups.setdefault(f"{p.source}:{p.date}", []).append(p)

    def row(kind: str, p: journals.Posting) -> str:
        amount = p.debit - p.credit
        name = (p.account.name or _code(p)).replace("\t", " ")
        memo = p.description.replace("\t", " ").replace("\n", " ")
        return "\t".join(
            [
                kind,
                "GENERAL JOURNAL",
                p.date.strftime("%m/%d/%Y"),
                name,
                _money(amount),
                memo,
                p.reference,
            ]
        )

    for items in groups.values():
        first, *rest = items
        lines.append(row("TRNS", first))
        lines.extend(row("SPL", p) for p in rest)
        lines.append("ENDTRNS")
    return ("\r\n".join(lines) + "\r\n").encode()


def summary(postings: list[Any]) -> dict[str, str]:
    debit = sum((p.debit for p in postings), Decimal(0))
    credit = sum((p.credit for p in postings), Decimal(0))
    return {"debit": _money(debit), "credit": _money(credit)}
