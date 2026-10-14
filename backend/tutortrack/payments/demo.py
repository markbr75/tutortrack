"""In-product sample data (FR-02-6): two manual payments against the sample invoices: a
bank transfer that pays one in full and a cash part-payment on the overdue one. No money
moves and no receipt is sent (sample data never messages anyone)."""

from __future__ import annotations

from datetime import timedelta

from django.utils.translation import gettext as _

from tutortrack.tenancy.demo import DemoContext, demo_provider


@demo_provider(order=86)
def sample_payments(ctx: DemoContext) -> None:
    from decimal import Decimal

    from tutortrack.core.money import Money
    from tutortrack.core.time import now

    from . import services
    from .models import Payment

    invoices = ctx.extras.get("invoices", {})
    paid, overdue = invoices.get("paid"), invoices.get("overdue")
    if paid is not None:
        paid.refresh_from_db()
        services.record_manual_payment(
            client=paid.client,
            amount=paid.balance_due,
            method=Payment.Method.BANK_TRANSFER,
            received_at=now() - timedelta(days=2),
            reference=_("Sample payment"),
            allocations=[(paid, paid.balance_due)],
        )
    if overdue is not None:
        overdue.refresh_from_db()
        part = Money(
            (overdue.balance_due.amount / 2).quantize(Decimal("1")), overdue.balance_due.currency
        )
        if part.is_positive():
            services.record_manual_payment(
                client=overdue.client,
                amount=part,
                method=Payment.Method.CASH,
                reference=_("Sample part-payment"),
                allocations=[(overdue, part)],
            )
