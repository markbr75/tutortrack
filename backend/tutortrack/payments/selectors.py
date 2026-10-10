"""Read-side queries other apps use (E04 revenue share)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

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
