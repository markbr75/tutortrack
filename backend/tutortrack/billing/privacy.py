"""Financial records in DSARs and erasure (E29 Part 2, ADR 0028).

Financial records are never deleted and their amounts never change. Erasure anonymises the
personal parts only:

* a student's name on charges and invoice lines becomes their token label, and their name
  is scrubbed from descriptions;
* the bill payer's details on an invoice (``billing_snapshot``: name, contact, email,
  address) are legally required for ``privacy.financial_retention_years``, so they are kept
  until then and anonymised by the ``erased_financial`` retention category afterwards (or
  straight away for invoices already older than the period).
"""

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

from .models import (
    BillingPlan,
    Charge,
    ClientLedgerEntry,
    CreditNote,
    Invoice,
    InvoiceLine,
    PackagePurchase,
    PaymentRequest,
    TutorInvoiceReview,
)


def _money(value: Any) -> str:
    return str(value) if value is not None else ""


def export(person: Person) -> list[Section]:
    clients = person.of("people.client")
    students = person.of("people.student")
    invoices = []
    for invoice in (
        Invoice.objects.filter(client_id__in=clients)
        .exclude(status="draft")
        .prefetch_related("lines")
    ):
        invoices.append(
            {
                "id": str(invoice.pk),
                "number": invoice.number,
                "status": invoice.status,
                "issue_date": invoice.issue_date,
                "total": _money(invoice.total),
                "balance_due": _money(invoice.balance_due),
                "billed_to": invoice.billing_snapshot,
                "lines": [
                    {
                        "description": line.description,
                        "student": line.student_name,
                        "gross": _money(line.gross),
                    }
                    for line in invoice.lines.all()
                ],
            }
        )
    charges = [
        {
            "id": str(c.pk),
            "date": c.date,
            "description": c.description,
            "gross": _money(c.gross),
            "status": c.status,
        }
        for c in Charge.objects.filter(Q(client_id__in=clients) | Q(student_id__in=students))
    ]
    credit_notes = [
        {
            "id": str(n.pk),
            "number": n.number,
            "reason": n.reason,
            "total": _money(n.total),
            "issued_at": n.issued_at,
        }
        for n in CreditNote.objects.filter(client_id__in=clients)
    ]
    requests = [
        {
            "id": str(r.pk),
            "number": r.number,
            "description": r.description,
            "amount": _money(r.amount),
            "status": r.status,
        }
        for r in PaymentRequest.objects.filter(client_id__in=clients)
    ]
    packages = [
        {
            "id": str(p.pk),
            "name": p.name,
            "units_total": p.units_total,
            "units_used": p.units_used,
            "status": p.status,
            "expires_at": p.expires_at,
        }
        for p in PackagePurchase.objects.filter(
            Q(client_id__in=clients) | Q(student_id__in=students)
        )
    ]
    reviews = [
        {
            "id": str(r.pk),
            "invoice_run": str(r.invoice_run_id),
            "status": r.status,
            "comment": r.comment,
            "decided_at": r.decided_at,
        }
        for r in TutorInvoiceReview.objects.filter(tutor_id__in=person.of("people.tutor"))
    ]
    return [
        Section("billing.invoices", _("Invoices"), invoices),
        Section("billing.charges", _("Charges"), charges),
        Section("billing.credit_notes", _("Credit notes"), credit_notes),
        Section("billing.payment_requests", _("Payment requests"), requests),
        Section("billing.packages", _("Packages"), packages),
        Section("billing.tutor_reviews", _("Invoice checks (tutor)"), reviews),
    ]


def _scrub_rows(model: Any, qs: Any, field: str, ctx: ErasureContext) -> int:
    count = 0
    for pk, value in qs.values_list("pk", field):
        scrubbed = ctx.scrub(value)
        if scrubbed != value:
            model.objects.filter(pk=pk).update(**{field: scrubbed})
            count += 1
    return count


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    clients = person.of("people.client")
    students = person.of("people.student")
    tutors = person.of("people.tutor")
    households = sorted({*clients, *person.context.get("people.client", set())})
    # Student names on lines become the token; descriptions lose the name.
    for line in InvoiceLine.objects.filter(charge__student_id__in=students).select_related(
        "charge"
    ):
        InvoiceLine.objects.filter(pk=line.pk).update(
            student_name=ctx.label("people.student", line.charge.student_id, _("Erased student")),
            description=ctx.scrub(line.description),
        )
        out.anonymised += 1
    for line in InvoiceLine.objects.filter(charge__tutor_id__in=tutors).select_related("charge"):
        InvoiceLine.objects.filter(pk=line.pk).update(
            tutor_name=ctx.label("people.tutor", line.charge.tutor_id, _("Erased tutor"))
        )
        out.anonymised += 1
    # Gap G3: what a tutor wrote when checking draft invoices.
    out.anonymised += (
        TutorInvoiceReview.objects.filter(tutor_id__in=tutors)
        .exclude(comment="")
        .update(comment="")
    )
    in_scope = Q(client_id__in=households) | Q(student_id__in=students)
    out.anonymised += _scrub_rows(Charge, Charge.objects.filter(in_scope), "description", ctx)
    out.anonymised += _scrub_rows(
        InvoiceLine,
        InvoiceLine.objects.filter(invoice__client_id__in=households),
        "description",
        ctx,
    )
    out.anonymised += _scrub_rows(
        ClientLedgerEntry,
        ClientLedgerEntry.objects.filter(client_id__in=households),
        "description",
        ctx,
    )
    out.anonymised += _scrub_rows(
        CreditNote, CreditNote.objects.filter(client_id__in=households), "reason", ctx
    )
    out.anonymised += _scrub_rows(
        PaymentRequest, PaymentRequest.objects.filter(client_id__in=households), "description", ctx
    )
    out.anonymised += _scrub_rows(
        BillingPlan, BillingPlan.objects.filter(in_scope), "description", ctx
    )
    out.anonymised += _scrub_rows(
        Invoice, Invoice.objects.filter(client_id__in=households), "notes", ctx
    )
    # The bill payer's details: only once the financial retention period has passed.
    cutoff = ctx.financial_cutoff.date()
    for invoice in Invoice.objects.filter(client_id__in=clients):
        snapshot = dict(invoice.billing_snapshot or {})
        anonymous = {
            **snapshot,
            "client_name": ctx.label("people.client", invoice.client_id, _("Erased client")),
            "contact_name": "",
            "email": "",
            "address": [],
        }
        if snapshot == anonymous:
            continue
        if ctx.include_financial or (
            invoice.issue_date is not None and invoice.issue_date < cutoff
        ):
            Invoice.objects.filter(pk=invoice.pk).update(billing_snapshot=anonymous)
            out.anonymised += 1
        else:
            out.retained += 1
    if out.retained:
        out.notes.append("bill payer details kept on invoices until the retention period ends")
    return out


register(
    Provider(
        key="billing",
        label=gettext_lazy("Invoices and charges"),
        export=export,
        erase=erase,
        order=40,
    )
)
