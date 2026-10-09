"""Payment receipts (E11-T09), rendered like invoices (WeasyPrint)."""

from __future__ import annotations

from typing import Any

from django.template.loader import render_to_string
from django.utils import translation


def receipt_pdf(payment: Any) -> bytes:
    from weasyprint import HTML

    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=payment.organisation_id)
    locale = (org.locale or "en-GB").replace("-", "_")
    rows = [
        {"number": a.invoice.number, "amount": a.amount.format(locale)}
        for a in payment.allocations.select_related("invoice").all()
        if a.amount.is_positive()
    ]
    with translation.override(org.locale):
        html = render_to_string(
            "payments/receipt.html",
            {
                "org": org,
                "payment": payment,
                "amount": payment.amount.format(locale),
                "rows": rows,
            },
        )
    return bytes(HTML(string=html).write_pdf())
