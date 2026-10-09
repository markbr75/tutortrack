"""Invoice, credit note and statement PDFs (WeasyPrint, E10-T03).

Rendered on demand from the issued document's own data (lines, totals and the billing
snapshot taken at issue), so a re-download always matches what was sent.
"""

from __future__ import annotations

from typing import Any

from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext_lazy as _

from tutortrack.core.money import Money

AGEING_LABELS = {
    "current": _("Not yet due"),
    "1_30": _("1\N{EN DASH}30 days overdue"),
    "31_60": _("31\N{EN DASH}60 days overdue"),
    "61_90": _("61\N{EN DASH}90 days overdue"),
    "90_plus": _("Over 90 days overdue"),
}


def _locale(org: Any) -> str:
    return str(getattr(org, "locale", "en-GB") or "en-GB").replace("-", "_")


def _fmt(locale: str) -> Any:
    def money(value: Money) -> str:
        return value.format(locale)

    return money


def _render(template: str, context: dict[str, Any], org: Any) -> bytes:
    from weasyprint import HTML

    locale = _locale(org)
    with translation.override(locale.replace("_", "-")):
        html = render_to_string(template, {**context, "org": org, "locale": locale})
    return bytes(HTML(string=html).write_pdf())


def money_rows(invoice: Any, locale: str) -> dict[str, str]:
    fmt = _fmt(locale)
    return {
        name: fmt(getattr(invoice, name))
        for name in (
            "subtotal",
            "tax_total",
            "total",
            "amount_paid",
            "amount_credited",
            "balance_due",
        )
    }


def invoice_pdf(invoice: Any) -> bytes:
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=invoice.organisation_id)
    locale = _locale(org)
    fmt = _fmt(locale)
    lines = [
        {
            "date": line.date,
            "description": line.description,
            "student": line.student_name,
            "tutor": line.tutor_name,
            "quantity": line.quantity.normalize(),
            "unit_price": fmt(line.unit_price.round_to_minor()),
            "tax_percent": line.tax_percent.normalize(),
            "amount": fmt(line.gross),
        }
        for line in invoice.lines.all()
    ]
    return _render(
        "billing/invoice.html",
        {
            "invoice": invoice,
            "snapshot": invoice.billing_snapshot or {},
            "lines": lines,
            "totals": money_rows(invoice, locale),
            "has_tax": invoice.tax_total.is_positive(),
        },
        org,
    )


def statement_pdf(client: Any, data: Any) -> bytes:
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=client.organisation_id)
    fmt = _fmt(_locale(org))
    return _render(
        "billing/statement.html",
        {
            "client": client,
            "statement": data,
            "opening": fmt(data.opening),
            "closing": fmt(data.closing),
            "rows": [
                {
                    "date": e.occurred_at.date(),
                    "description": e.description or e.get_type_display(),
                    "amount": fmt(e.amount),
                    "balance": fmt(e.balance_after),
                }
                for e in data.entries
            ],
            "ageing": [(AGEING_LABELS[k], fmt(v)) for k, v in data.ageing.items()],
        },
        org,
    )
