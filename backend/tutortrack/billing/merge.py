"""Billing follows a merged client or student (FR-05-13).

Charges, invoices, credit notes, payment requests, packages, plans, collections cases and
split-billing shares are re-pointed to the survivor with their amounts untouched. Ledger
entries are never changed (E10), so they stay on the merged record as its history, and
the balance moves with a pair of adjustments: one clears the merged record's balance, the
other adds it to the survivor's (per currency). Both name the other record."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

from tutortrack.core.money import Money
from tutortrack.people.merging import (
    MergeContext,
    MergeProvider,
    Move,
    count,
    moves,
    register,
    repoint,
)

from . import ledger
from .models import (
    BillingPlan,
    BillingSplit,
    Charge,
    ClientLedgerEntry,
    CollectionsCase,
    CreditNote,
    Invoice,
    PackagePurchase,
    PaymentRequest,
)

CLIENT_RECORDS = (
    ("billing.charges", _l("Charges"), Charge),
    ("billing.invoices", _l("Invoices"), Invoice),
    ("billing.credit_notes", _l("Credit notes"), CreditNote),
    ("billing.payment_requests", _l("Payment requests"), PaymentRequest),
    ("billing.packages", _l("Packages"), PackagePurchase),
    ("billing.plans", _l("Billing plans"), BillingPlan),
    ("billing.collections", _l("Collections cases"), CollectionsCase),
    ("billing.splits", _l("Split-billing shares"), BillingSplit),
)
STUDENT_RECORDS = (
    ("billing.charges", _l("Charges"), Charge),
    ("billing.packages", _l("Packages"), PackagePurchase),
    ("billing.plans", _l("Billing plans"), BillingPlan),
    ("billing.splits", _l("Split-billing shares"), BillingSplit),
)


def _records(ctx: MergeContext) -> tuple[tuple[str, object, type], ...]:
    return CLIENT_RECORDS if ctx.subject_type == "people.client" else STUDENT_RECORDS


def _field(ctx: MergeContext) -> str:
    return "client" if ctx.subject_type == "people.client" else "student"


def balances(client: object) -> dict[str, Money]:
    """The client's non-zero ledger balance per currency."""
    rows = (
        ClientLedgerEntry.objects.filter(client=client)
        .values("currency")
        .annotate(total=Sum("amount_amount"))
    )
    out = {}
    for row in rows:
        amount = Money(Decimal(row["total"] or 0), row["currency"]).round_to_minor()
        if not amount.is_zero():
            out[row["currency"]] = amount
    return out


def _count(ctx: MergeContext) -> list[Move]:
    found = [(key, label, count(model, _field(ctx), ctx)) for key, label, model in _records(ctx)]
    if ctx.subject_type == "people.client":
        found.append(("billing.balance", _l("Account balances"), len(balances(ctx.source))))
    return moves(*found)


def _merge(ctx: MergeContext) -> list[Move]:
    name = _field(ctx)
    moved = [(key, label, repoint(model, name, ctx)) for key, label, model in _records(ctx)]
    if ctx.subject_type == "people.client":
        transferred = 0
        for _currency, amount in sorted(balances(ctx.source).items()):
            ledger.post(
                ctx.source,
                ClientLedgerEntry.Type.ADJUSTMENT,
                -amount,
                ref=ctx.target,
                description=_("Balance moved to %(name)s (records merged)") % {"name": ctx.target},
                user=ctx.user,
            )
            ledger.post(
                ctx.target,
                ClientLedgerEntry.Type.ADJUSTMENT,
                amount,
                ref=ctx.source,
                description=_("Balance moved from %(name)s (records merged)")
                % {"name": ctx.source},
                user=ctx.user,
            )
            transferred += 1
        moved.append(("billing.balance", _l("Account balances"), transferred))
    return moves(*moved)


register(
    MergeProvider(
        key="billing",
        label="Billing",
        subject_types=frozenset({"people.client", "people.student"}),
        count=_count,
        merge=_merge,
        history=("billing.ClientLedgerEntry.client",),
        order=50,
    )
)
