"""Tutor pay in DSARs and erasure (E12 data, E29 Part 2). Pay items, payouts and
self-billing statements are financial records and stay; bank details and the payee name
are removed, and expense descriptions lose the person's name."""

from __future__ import annotations

from django.utils.translation import gettext as _

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    Section,
    register,
)

from .models import Expense, PayItem, Payout, PayStatement, TutorPayProfile


def export(person: Person) -> list[Section]:
    tutors = person.of("people.tutor")
    if not tutors:
        return []
    profile = [
        {
            "id": str(p.pk),
            "method": p.method,
            "payee_name": p.payee_name,
            "bank": p.bank_hint,
            "vat_registered": p.vat_registered,
            "vat_number": p.vat_number,
        }
        for p in TutorPayProfile.objects.filter(tutor_id__in=tutors)
    ]
    items = [
        {
            "id": str(i.pk),
            "date": i.date,
            "description": i.description,
            "amount": str(i.amount),
            "status": i.status,
        }
        for i in PayItem.objects.filter(tutor_id__in=tutors).order_by("-date")[:5000]
    ]
    payouts = [
        {"id": str(p.pk), "amount": str(p.amount), "status": p.status, "paid_at": p.paid_at}
        for p in Payout.objects.filter(tutor_id__in=tutors)
    ]
    statements = [
        {"id": str(s.pk), "number": s.number, "issued_at": s.issued_at, "total": str(s.total)}
        for s in PayStatement.objects.filter(tutor_id__in=tutors)
    ]
    expenses = [
        {
            "id": str(e.pk),
            "date": e.date,
            "description": e.description,
            "amount": str(e.amount),
            "status": e.status,
        }
        for e in Expense.objects.filter(tutor_id__in=tutors)
    ]
    return [
        Section("payroll.profile", _("Pay details"), profile),
        Section("payroll.items", _("Pay items"), items),
        Section("payroll.payouts", _("Payouts"), payouts),
        Section("payroll.statements", _("Pay statements"), statements),
        Section("payroll.expenses", _("Expenses"), expenses),
    ]


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    tutors = person.of("people.tutor")
    if not tutors:
        return out
    for profile in TutorPayProfile.objects.filter(tutor_id__in=tutors):
        TutorPayProfile.objects.filter(pk=profile.pk).update(
            payee_name=ctx.label("people.tutor", profile.tutor_id, _("Erased tutor")),
            bank_details="",
            bank_hint="",
            stripe_account_id="",
        )
        out.anonymised += 1
    for expense in Expense.objects.filter(tutor_id__in=tutors):
        if ctx.scrub(expense.description) != expense.description:
            Expense.objects.filter(pk=expense.pk).update(description=ctx.scrub(expense.description))
            out.anonymised += 1
    out.retained += PayStatement.objects.filter(tutor_id__in=tutors).count()
    return out


register(Provider(key="payroll", label="Tutor pay", export=export, erase=erase, order=42))
