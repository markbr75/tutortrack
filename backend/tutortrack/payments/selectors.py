"""Read-side queries other apps use (E04 revenue share)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db.models import Sum

from .models import Payment, Provider


def processed_totals(start: datetime, end: datetime) -> dict[str, Decimal]:
    """Card and debit payments taken through TutorTrack in ``[start, end)``, per currency
    (manual payments recorded by staff don't count)."""
    rows = (
        Payment.objects.filter(
            status=Payment.Status.SUCCEEDED,
            received_at__gte=start,
            received_at__lt=end,
        )
        .exclude(provider=Provider.MANUAL)
        .values("currency")
        .annotate(total=Sum("amount_amount"))
    )
    return {r["currency"]: r["total"] or Decimal(0) for r in rows}


def similar_payment_exists(client: Any, amount: Decimal, day: Any, reference: str) -> bool:
    """A succeeded payment for the client with this amount on this day (and reference):
    imports skip it so a file can be imported again safely (E28)."""
    qs = Payment.objects.filter(client=client, amount_amount=amount, received_at__date=day).exclude(
        status=Payment.Status.FAILED
    )
    if reference:
        qs = qs.filter(reference=reference[:120])
    return qs.exists()
