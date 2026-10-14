"""In-product sample data (FR-02-6): invoices in several states from the completed sample
lessons. The Patel family has an issued invoice (``payments.demo`` pays it) and a draft for
their latest lessons; the Okafors have an overdue invoice (part-paid by ``payments.demo``).
Sample invoices are numbered from their own ``DEMO-`` sequence (``core.demo_mode``), so the
real numbering stays gap-free when they are cleared."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from tutortrack.tenancy.demo import DemoContext, demo_provider


@demo_provider(order=85)
def sample_invoices(ctx: DemoContext) -> None:
    from tutortrack.core.exceptions import BusinessRuleViolation

    from . import services

    clients = ctx.extras.get("clients", {})
    today = services.org_today()
    invoices: dict[str, Any] = {}

    def draft(client: Any, until: Any = None) -> Any:
        try:
            return services.create_draft(client, until=until)
        except BusinessRuleViolation:  # nothing billable (say, the org bills in advance)
            return None

    patel, okafor = clients.get("Patel"), clients.get("Okafor")
    if patel is not None:
        invoice = draft(patel, until=today - timedelta(days=8))
        if invoice is not None:
            invoices["paid"] = services.issue_invoice(invoice, send=False)
        invoices["draft"] = draft(patel)
    if okafor is not None:
        invoice = draft(okafor)
        if invoice is not None:
            services.update_draft(invoice, due_date=today - timedelta(days=3))
            invoices["overdue"] = services.issue_invoice(invoice, send=False)
    ctx.extras["invoices"] = invoices
