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


# --- record timelines (E05 FR-05-10) ------------------------------------------------------------


def payment_timeline(user: Any, target_type: str, target_id: str, limit: int) -> list[Any]:
    """Payments from a client (or a contact's family) for the activity timeline."""
    from tutortrack.core.permissions import has_perm, scope_queryset
    from tutortrack.crm.selectors import TimelineItem
    from tutortrack.people.selectors import timeline_scope

    clients = timeline_scope(target_type, target_id)["client"]
    if not clients or not has_perm(user, "payments.payment.view"):
        return []
    rows = scope_queryset(
        user, Payment.objects.filter(client_id__in=clients), "payments.payment.view"
    ).order_by("-received_at", "-created_at")[:limit]
    return [
        TimelineItem(
            "payment",
            str(p.pk),
            p.received_at or p.created_at,
            f"{p.amount.amount} {p.currency}",
            f"{p.method} · {p.status}",
            None,
        )
        for p in rows
    ]
