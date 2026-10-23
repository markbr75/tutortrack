"""Invoice, credit note and statement PDFs (WeasyPrint, E10-T03).

Rendered on demand from the issued document's own data (lines, totals and the billing
snapshot taken at issue), so a re-download always matches what was sent.
"""

from __future__ import annotations

from typing import Any

from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext_lazy as _

from tutortrack.core import branding
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


def render_html(template: str, context: dict[str, Any], org: Any, branch_id: Any = None) -> str:
    """A document's HTML in the organisation's language, with the branch's brand kit (the
    organisation's when the branch has none). ``accent`` and ``logo`` default to the brand's;
    an invoice template can set its own."""
    locale = _locale(org)
    with translation.override(locale.replace("_", "-")):
        brand = branding.for_documents(org.pk, branch_id)
        page = {
            "accent": brand.get("primary_colour") or "",
            "logo": brand.get("logo_data_uri") or "",
            **context,
            "org": org,
            "locale": locale,
            "brand": brand,
        }
        if "layout" in context:
            page.update(_layout_look(context["layout"], brand))
            page["trading_name"] = (
                context["layout"].get("trading_name")
                or (context.get("snapshot") or {}).get("organisation")
                or org.name
            )
        return render_to_string(template, page)


def _render(template: str, context: dict[str, Any], org: Any, branch_id: Any = None) -> bytes:
    from weasyprint import HTML

    return bytes(HTML(string=render_html(template, context, org, branch_id)).write_pdf())


def _layout_look(layout: dict[str, Any], brand: dict[str, Any]) -> dict[str, str]:
    """The colour and logo an invoice template asks for, resolved against the brand kit."""
    from tutortrack.core.storage.inline import image_data_uri

    mode = layout.get("logo_mode", "brand")
    if mode == "own":
        logo = image_data_uri(layout.get("logo_id"))
    elif mode == "none":
        logo = ""
    else:
        logo = brand.get("logo_data_uri") or ""
    return {"accent": layout.get("accent") or brand.get("primary_colour") or "", "logo": logo}


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

    from .invoice_templates import invoice_layout

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
            "layout": invoice_layout(invoice),
            "lines": lines,
            "totals": money_rows(invoice, locale),
            "has_tax": invoice.tax_total.is_positive(),
        },
        org,
        invoice.branch_id,
    )


def _preview_context(layout: dict[str, Any], org: Any) -> dict[str, Any]:
    from .invoice_templates import sample_invoice

    locale = _locale(org)
    fmt = _fmt(locale)
    sample = sample_invoice(org.default_currency or "GBP")
    price = sample["price"]
    lines = [
        {**row, "quantity": 1, "unit_price": fmt(price), "tax_percent": 0, "amount": fmt(price)}
        for row in sample["rows"]
    ]
    return {
        "invoice": sample["invoice"],
        "snapshot": {**sample["snapshot"], "organisation": org.name},
        "layout": layout,
        "lines": lines,
        "totals": money_rows(sample["invoice"], locale),
        "has_tax": False,
        "preview": True,
    }


def invoice_preview_html(layout: dict[str, Any], org: Any) -> str:
    """The invoice editor's live preview: a sample invoice drawn with unsaved settings."""
    return render_html("billing/invoice.html", _preview_context(layout, org), org)


def invoice_preview_pdf(layout: dict[str, Any], org: Any) -> bytes:
    return _render("billing/invoice.html", _preview_context(layout, org), org)


def credit_note_pdf(note: Any) -> bytes:
    """A credit note (FR-10-5, gap G3): its number, the invoice it credits, the reason, the
    lines credited and how the credit is used. Billing details come from the credited
    invoice's snapshot, so they match what the client received."""
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=note.organisation_id)
    fmt = _fmt(_locale(org))
    invoice = note.invoice
    return _render(
        "billing/credit_note.html",
        {
            "note": note,
            "invoice": invoice,
            "snapshot": invoice.billing_snapshot or {},
            "lines": [
                {
                    "description": line.description,
                    "net": fmt(line.net),
                    "tax": fmt(line.tax),
                    "amount": fmt(line.gross),
                }
                for line in note.lines.all()
            ],
            "totals": {"net": fmt(note.net), "tax": fmt(note.tax), "total": fmt(note.total)},
            "has_tax": note.tax.is_positive(),
            "applied_to_invoice": note.application == "invoice",
        },
        org,
        invoice.branch_id,
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
        client.branch_id,
    )
