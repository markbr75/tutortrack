"""Payments in DSARs and erasure (E29 Part 2). Payments are financial records: they are
kept with their amounts and references; free-text notes and bank statement narratives lose
the person's name, and mandate evidence loses the IP address and browser."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    Section,
    register,
)

from .models import AutoPayConsent, BankTransaction, Payment, PaymentGroup, PaymentMethod, SetupLink


def export(person: Person) -> list[Section]:
    clients = person.of("people.client")
    if not clients:
        return []
    payments = [
        {
            "id": str(p.pk),
            "received_at": p.received_at,
            "amount": str(p.amount),
            "method": p.method,
            "status": p.status,
            "reference": p.reference,
        }
        for p in Payment.objects.filter(client_id__in=clients)
    ]
    methods = [
        {
            "id": str(m.pk),
            "type": m.type,
            "brand": m.brand,
            "last4": m.last4,
            "expires": f"{m.exp_month or ''}/{m.exp_year or ''}",
            "status": m.status,
        }
        for m in PaymentMethod.objects.filter(client_id__in=clients)
    ]
    consents = [
        {"id": str(c.pk), "text": c.text, "given_at": c.given_at, "withdrawn_at": c.withdrawn_at}
        for c in AutoPayConsent.objects.filter(client_id__in=clients)
    ]
    return [
        Section("payments.payments", _("Payments"), payments),
        Section("payments.methods", _("Saved payment methods"), methods),
        Section("payments.autopay", _("Automatic payment agreements"), consents),
    ]


def _scrub(model: Any, qs: Any, fields: tuple[str, ...], ctx: ErasureContext) -> int:
    count = 0
    for row in qs.values("pk", *fields):
        changes = {f: ctx.scrub(row[f]) for f in fields if ctx.scrub(row[f]) != row[f]}
        if changes:
            model.objects.filter(pk=row["pk"]).update(**changes)
            count += 1
    return count


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    clients = sorted({*person.of("people.client"), *person.context.get("people.client", set())})
    if not clients:
        return out
    payments = Payment.objects.filter(client_id__in=clients)
    out.anonymised += _scrub(Payment, payments, ("notes", "reference"), ctx)
    out.anonymised += _scrub(
        PaymentGroup,
        PaymentGroup.objects.filter(payments__in=payments).distinct(),
        ("payer_name", "reference", "notes"),
        ctx,
    )
    out.anonymised += _scrub(
        BankTransaction,
        BankTransaction.objects.filter(
            Q(payment__in=payments) | Q(payment_group__payments__in=payments)
        ).distinct(),
        ("description", "reference", "counterparty"),
        ctx,
    )
    own = person.of("people.client")
    if own:
        out.anonymised += AutoPayConsent.objects.filter(client_id__in=own).update(
            ip_address=None, user_agent=""
        )
        out.deleted += SetupLink.objects.filter(client_id__in=own).delete()[0]
        out.retained += payments.filter(client_id__in=own).count()
    return out


register(
    Provider(key="payments", label=gettext_lazy("Payments"), export=export, erase=erase, order=41)
)
