"""Read side of payroll (E12): scoped lists and the tutor's earnings view (FR-12-9)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet

from tutortrack.core.permissions import has_perm, scope_queryset
from tutortrack.people.models import TutorProfile

from .models import Expense, PayItem, Payout, PayRun, PayStatement


def pay_items(user: Any) -> QuerySet[PayItem]:
    return scope_queryset(user, PayItem.objects.select_related("tutor", "pay_run"), "payroll.view")


def expenses(user: Any) -> QuerySet[Expense]:
    base = Expense.objects.select_related("tutor", "category", "decided_by")
    # Approvers see the claims in their scope; tutors see their own (submit:own).
    if has_perm(user, "payroll.expense.approve"):
        return scope_queryset(user, base, "payroll.expense.approve")
    return scope_queryset(user, base, "payroll.expense.submit")


def pay_runs(user: Any) -> QuerySet[PayRun]:
    return scope_queryset(user, PayRun.objects.all(), "payroll.view")


def statements(user: Any) -> QuerySet[PayStatement]:
    return scope_queryset(
        user, PayStatement.objects.select_related("tutor", "payout__pay_run"), "payroll.view"
    )


def tutor_for_user(user: Any) -> TutorProfile | None:
    return TutorProfile.objects.filter(membership__user=user).first()


def _totals(items: Any) -> dict[str, str]:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for item in items:
        totals[item.currency] += item.amount.amount
    return {c: str(v) for c, v in totals.items()}


def earnings(tutor: TutorProfile, today: date) -> dict[str, Any]:
    """Upcoming pay, held items with reasons, payouts, statements and year-to-date."""
    items = PayItem.objects.filter(tutor=tutor).exclude(status=PayItem.Status.VOID)
    upcoming = list(
        items.filter(
            status__in=[PayItem.Status.READY, PayItem.Status.IN_PAY_RUN, PayItem.Status.APPROVED]
        ).order_by("date")[:200]
    )
    held = list(items.filter(status=PayItem.Status.HELD).select_related("lesson").order_by("date"))
    year_start = today.replace(month=1, day=1)
    paid_this_year = items.filter(status=PayItem.Status.PAID, date__gte=year_start)
    payouts = list(
        Payout.objects.filter(tutor=tutor, status=Payout.Status.PAID)
        .select_related("pay_run")
        .order_by("-paid_at")[:24]
    )
    return {
        "upcoming": upcoming,
        "upcoming_total": _totals(upcoming),
        "held": held,
        "held_total": _totals(held),
        "payouts": payouts,
        "statements": list(
            PayStatement.objects.filter(tutor=tutor).select_related("payout__pay_run")[:24]
        ),
        "year_to_date": _totals(paid_this_year),
    }
