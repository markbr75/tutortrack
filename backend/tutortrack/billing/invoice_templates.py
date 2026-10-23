"""Invoice templates (ADR 0046): how an invoice looks, chosen per job, per family or by the
organisation's default.

A template is structured settings, not free HTML: a style, an accent colour, a logo, the
wording around the lines and which columns show. ``layout`` turns a template into the plain
dict the invoice HTML (``billing/invoice.html``) reads; issuing an invoice stores that dict
in its billing snapshot, so later edits never change an invoice already sent.
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.tenancy.settings_service import get_setting

from .models import Charge, Invoice, InvoiceTemplate

TEMPLATE_FIELDS = frozenset(
    {
        "name", "is_default", "style", "accent_colour", "logo_mode", "logo", "title",
        "trading_name", "intro", "payment_instructions", "footer", "show_date",
        "show_student", "show_tutor", "show_quantity", "show_unit_price",
    }
)  # fmt: skip
COLUMNS = ("date", "student", "tutor", "quantity", "unit_price")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def _check(template: InvoiceTemplate) -> None:
    if not template.name.strip():
        raise _invalid("name", _("Give the template a name."))
    if template.accent_colour and not HEX.match(template.accent_colour):
        raise _invalid("accent_colour", _("Use a colour like #1D4ED8, or leave it empty."))
    if template.style not in InvoiceTemplate.Style.values:
        raise _invalid("style", _("Choose a style."))
    if template.logo_mode not in InvoiceTemplate.Logo.values:
        raise _invalid("logo_mode", _("Choose which logo to show."))
    if template.logo_mode == InvoiceTemplate.Logo.OWN and template.logo_id is None:
        raise _invalid("logo", _("Upload a logo, or choose the brand kit logo or no logo."))


def _known(fields: dict[str, Any]) -> None:
    unknown = set(fields) - TEMPLATE_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Unknown template fields: {', '.join(sorted(unknown))}")


def _clear_default(keep: InvoiceTemplate | None = None) -> None:
    others = InvoiceTemplate.objects.filter(is_default=True)
    if keep is not None and keep.pk:
        others = others.exclude(pk=keep.pk)
    for other in others:
        with audit.track(other):
            other.is_default = False
            other.save(update_fields=["is_default", "updated_at"])


# --- writes ----------------------------------------------------------------------------------


@transaction.atomic
def create_template(**fields: Any) -> InvoiceTemplate:
    """Add a template. The first one becomes the default."""
    _known(fields)
    template = InvoiceTemplate(**fields)
    _check(template)
    if not InvoiceTemplate.objects.exists():
        template.is_default = True
    if template.is_default:
        _clear_default()
    template.save()
    audit.record_create(template)
    return template


@transaction.atomic
def update_template(template: InvoiceTemplate, **changes: Any) -> InvoiceTemplate:
    _known(changes)
    if changes.get("is_default"):
        _clear_default(keep=template)
    with audit.track(template):
        for field, value in changes.items():
            setattr(template, field, value)
        _check(template)
        template.save()
    return template


@transaction.atomic
def delete_template(template: InvoiceTemplate) -> None:
    """Remove a template. Families and jobs that used it fall back to the default; issued
    invoices keep the copy in their snapshot."""
    with audit.track(template, action="delete"):
        template.delete()


# --- reads -----------------------------------------------------------------------------------


def templates() -> Any:
    return InvoiceTemplate.objects.select_related("logo")


def template_for_invoice(invoice: Invoice) -> InvoiceTemplate | None:
    """The job's template when every charge on the invoice is for one job, else the
    family's, else the organisation's default (``None``: the built-in look)."""
    from tutortrack.jobs.models import Job

    job_ids = set(Charge.objects.filter(invoice=invoice).values_list("job_id", flat=True))
    if len(job_ids) == 1 and None not in job_ids:
        chosen = Job.objects.filter(pk=job_ids.pop()).values_list("invoice_template", flat=True)
        template_id = chosen.first()
        if template_id:
            return InvoiceTemplate.objects.filter(pk=template_id).first()
    if invoice.client.invoice_template_id:
        return InvoiceTemplate.objects.filter(pk=invoice.client.invoice_template_id).first()
    return InvoiceTemplate.objects.filter(is_default=True).first()


def layout(template: InvoiceTemplate | None) -> dict[str, Any]:
    """The settings the invoice HTML reads. Blank wording falls back to the billing settings
    ("How to pay", footer); a blank colour and the brand logo come from the brand kit when the
    invoice is drawn."""
    t = template or InvoiceTemplate()
    return {
        "template_id": str(template.pk) if template else "",
        "style": t.style,
        "accent": t.accent_colour,
        "logo_mode": t.logo_mode,
        "logo_id": str(t.logo_id) if t.logo_id else "",
        "title": t.title,
        "trading_name": t.trading_name,
        "intro": t.intro,
        "payment_instructions": t.payment_instructions
        or get_setting("billing.payment_instructions"),
        "footer": t.footer or get_setting("billing.invoice_footer"),
        "columns": {column: bool(getattr(t, f"show_{column}")) for column in COLUMNS},
    }


def invoice_layout(invoice: Invoice) -> dict[str, Any]:
    """An issued invoice keeps the look it was sent with; a draft shows the current one."""
    snapshot = invoice.billing_snapshot or {}
    if "template" in snapshot:
        return dict(snapshot["template"])
    if invoice.status != Invoice.Status.DRAFT:
        # Issued before templates existed: the built-in look with the wording it was sent with.
        built_in = layout(None)
        built_in["payment_instructions"] = snapshot.get("payment_instructions", "")
        built_in["footer"] = snapshot.get("footer", "")
        return built_in
    return layout(template_for_invoice(invoice))


def sample_invoice(currency: str) -> dict[str, Any]:
    """A made-up invoice for the editor's preview: three lessons, nothing from the database."""
    from .services import org_today

    today = org_today()
    price = Money(Decimal("45.00"), currency)
    rows = [
        (today - timedelta(days=21), _("GCSE Maths, one to one"), "Arjun Patel", "Nia Adeyemi"),
        (today - timedelta(days=14), _("GCSE Maths, one to one"), "Arjun Patel", "Nia Adeyemi"),
        (today - timedelta(days=7), _("A level Physics"), "Maya Patel", "Sam Clarke"),
    ]
    total = Money(price.amount * len(rows), currency)
    zero = Money(Decimal("0"), currency)
    invoice = SimpleNamespace(
        number="INV-0042",
        issue_date=today,
        due_date=today + timedelta(days=14),
        po_number="",
        period_start=today - timedelta(days=28),
        period_end=today,
        notes="",
        amount_credited_amount=0,
        amount_paid_amount=0,
        subtotal=total,
        tax_total=zero,
        total=total,
        amount_paid=zero,
        amount_credited=zero,
        balance_due=total,
    )
    return {
        "invoice": invoice,
        "snapshot": {
            "client_name": "The Patel family",
            "contact_name": "Priya Patel",
            "address": ["1 High Street", "Leeds", "LS1 1AA"],
        },
        "rows": [
            {"date": day, "description": text, "student": student, "tutor": tutor}
            for day, text, student, tutor in rows
        ],
        "price": price,
    }
