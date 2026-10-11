"""Double-entry postings for summary journals (E23-T06) and GL exports (E23-T08).

Sales side (per record, in the organisation's local dates):

* invoice issued: Dr receivable (gross) / Cr revenue (net per line) / Cr sales tax;
* invoice voided: the reverse; credit note: Dr revenue, Dr sales tax / Cr receivable;
* write-off: Dr bad debts / Cr receivable;
* payment received: Dr clearing / Cr receivable; refund: the reverse;
* provider fees: Dr fees / Cr clearing.

Exports add provider payouts (Dr bank / Cr clearing) and tutor pay (bills: Dr tutor
costs or expenses / Cr payable; payouts: Dr payable / Cr bank).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.utils.translation import gettext as _

from tutortrack.core.time import local_date_range_to_utc

from .documents import JournalLine
from .mappings import AccountRef, Mappings

ZERO = Decimal(0)


@dataclass(frozen=True)
class Posting:
    date: date
    currency: str
    account: AccountRef
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    description: str = ""
    reference: str = ""
    tax_code: str = ""
    tax: Decimal = ZERO
    tracking: tuple[tuple[str, str], ...] = ()
    source: str = ""  # "invoice:<id>"


def _signed(amount: Decimal, *, debit: bool) -> tuple[Decimal, Decimal]:
    """(debit, credit) for an amount that may be negative (a negative debit is a credit)."""
    if (amount >= 0) == debit:
        return abs(amount), ZERO
    return ZERO, abs(amount)


class _Collector:
    def __init__(self, maps: Mappings, tz: str):
        self.maps = maps
        self.zone = ZoneInfo(tz)
        self.rows: list[Posting] = []

    def local(self, moment: datetime | None) -> date:
        if moment is None:
            raise ValueError("no date")
        return moment.astimezone(self.zone).date()

    def add(
        self,
        day: date,
        currency: str,
        account: AccountRef,
        amount: Decimal,
        *,
        debit: bool,
        description: str,
        reference: str,
        source: str,
        tax_code: str = "",
        tax: Decimal = ZERO,
        tracking: tuple[tuple[str, str], ...] = (),
    ) -> None:
        if not amount:
            return
        dr, cr = _signed(amount, debit=debit)
        self.rows.append(
            Posting(
                day,
                currency,
                account,
                dr,
                cr,
                description[:300],
                reference[:100],
                tax_code,
                tax,
                tracking,
                source,
            )
        )


def _sales_line_accounts(c: _Collector, line: Any, branch_id: Any) -> tuple[AccountRef, str]:
    from .builders import revenue_keys

    charge = getattr(line, "charge", None)
    keys, code = revenue_keys(charge)
    account = c.maps.account("revenue", *keys, code=code)
    tax_code = c.maps.tax_code(charge.tax_rate_id if charge else None, line.tax_percent)
    return account, tax_code


def _invoice(c: _Collector, invoice: Any, day: date, *, reverse: bool) -> None:
    ref = invoice.number
    src = f"invoice:{invoice.pk}"
    track = c.maps.tracking_for(invoice.branch_id)
    receivable = c.maps.account("receivable")
    sales_tax = c.maps.account("sales_tax")
    label = _("Invoice %(n)s voided") if reverse else _("Invoice %(n)s")
    desc = label % {"n": ref}
    c.add(
        day,
        invoice.currency,
        receivable,
        invoice.total.amount,
        debit=not reverse,
        description=desc,
        reference=ref,
        source=src,
        tracking=track,
    )
    for line in invoice.lines.select_related(
        "charge__product", "charge__lesson__service", "charge__job__service"
    ):
        account, tax_code = _sales_line_accounts(c, line, invoice.branch_id)
        c.add(
            day,
            invoice.currency,
            account,
            line.net.amount,
            debit=reverse,
            description=f"{desc}: {line.description}",
            reference=ref,
            source=src,
            tax_code=tax_code,
            tax=line.tax.amount,
            tracking=track,
        )
        c.add(
            day,
            invoice.currency,
            sales_tax,
            line.tax.amount,
            debit=reverse,
            description=desc,
            reference=ref,
            source=src,
            tax_code=tax_code,
            tracking=track,
        )


def sales_postings(
    maps: Mappings, start: date, end: date, tz: str, *, currency: str | None = None
) -> list[Posting]:
    from tutortrack.billing.models import ClientLedgerEntry, CreditNote, Invoice
    from tutortrack.payments.models import Payment, Refund

    c = _Collector(maps, tz)
    since, until = local_date_range_to_utc(start, end, tz)
    by_currency: dict[str, Any] = {"currency": currency} if currency else {}
    issued = Invoice.objects.filter(issue_date__gte=start, issue_date__lte=end, **by_currency)
    for invoice in issued.exclude(status=Invoice.Status.DRAFT).order_by("issue_date", "number"):
        _invoice(c, invoice, invoice.issue_date, reverse=False)
    for invoice in Invoice.objects.filter(
        status=Invoice.Status.VOID, voided_at__gte=since, voided_at__lt=until, **by_currency
    ).exclude(issue_date__isnull=True):
        _invoice(c, invoice, c.local(invoice.voided_at), reverse=True)
    receivable = maps.account("receivable")
    for note in CreditNote.objects.filter(
        issued_at__gte=since, issued_at__lt=until, **by_currency
    ).order_by("issued_at"):
        day, ref, src = c.local(note.issued_at), note.number, f"credit_note:{note.pk}"
        track = maps.tracking_for(note.branch_id)
        desc = _("Credit note %(n)s") % {"n": ref}
        c.add(
            day,
            note.currency,
            receivable,
            note.total.amount,
            debit=False,
            description=desc,
            reference=ref,
            source=src,
            tracking=track,
        )
        for line in note.lines.select_related(
            "invoice_line__charge__product",
            "invoice_line__charge__lesson__service",
            "invoice_line__charge__job__service",
        ):
            if line.invoice_line is not None:
                account, tax_code = _sales_line_accounts(c, line.invoice_line, note.branch_id)
            else:
                account, tax_code = maps.account("revenue"), maps.tax_code(None)
            c.add(
                day,
                note.currency,
                account,
                line.net.amount,
                debit=True,
                description=f"{desc}: {line.description}",
                reference=ref,
                source=src,
                tax_code=tax_code,
                tax=line.tax.amount,
                tracking=track,
            )
            c.add(
                day,
                note.currency,
                maps.account("sales_tax"),
                line.tax.amount,
                debit=True,
                description=desc,
                reference=ref,
                source=src,
                tax_code=tax_code,
                tracking=track,
            )
    for entry in ClientLedgerEntry.objects.filter(
        type=ClientLedgerEntry.Type.WRITE_OFF,
        occurred_at__gte=since,
        occurred_at__lt=until,
        **by_currency,
    ):
        invoice = Invoice.objects.filter(pk=entry.ref_id).first()
        ref = invoice.number if invoice else entry.ref_id
        day, amount = c.local(entry.occurred_at), -entry.amount.amount
        desc = _("Write-off of %(n)s") % {"n": ref}
        track = maps.tracking_for(invoice.branch_id if invoice else None)
        c.add(
            day,
            entry.currency,
            maps.account("bad_debt"),
            amount,
            debit=True,
            description=desc,
            reference=ref,
            source=f"write_off:{entry.ref_id}",
            tracking=track,
        )
        c.add(
            day,
            entry.currency,
            receivable,
            amount,
            debit=False,
            description=desc,
            reference=ref,
            source=f"write_off:{entry.ref_id}",
            tracking=track,
        )
    from .builders import clearing_account

    received = Payment.objects.filter(
        received_at__gte=since,
        received_at__lt=until,
        status__in=[
            Payment.Status.SUCCEEDED,
            Payment.Status.REFUNDED,
            Payment.Status.PARTIALLY_REFUNDED,
            Payment.Status.DISPUTED,
        ],
        **by_currency,
    ).select_related("client")
    for payment in received.order_by("received_at"):
        day, src = c.local(payment.received_at), f"payment:{payment.pk}"
        ref = payment.reference or payment.get_method_display()
        desc = _("Payment from %(client)s") % {"client": payment.client.display_name}
        track = maps.tracking_for(payment.branch_id)
        clearing = clearing_account(_Ctx(maps), payment)
        c.add(
            day,
            payment.currency,
            clearing,
            payment.amount.amount,
            debit=True,
            description=desc,
            reference=ref,
            source=src,
            tracking=track,
        )
        c.add(
            day,
            payment.currency,
            receivable,
            payment.amount.amount,
            debit=False,
            description=desc,
            reference=ref,
            source=src,
            tracking=track,
        )
        if payment.fee is not None and payment.fee.amount:
            fee_desc = _("Payment fees %(ref)s") % {"ref": ref}
            c.add(
                day,
                payment.currency,
                maps.account("fees"),
                payment.fee.amount,
                debit=True,
                description=fee_desc,
                reference=ref,
                source=src,
                tracking=track,
            )
            c.add(
                day,
                payment.currency,
                clearing,
                payment.fee.amount,
                debit=False,
                description=fee_desc,
                reference=ref,
                source=src,
                tracking=track,
            )
    refunds = Refund.objects.filter(
        status=Refund.Status.SUCCEEDED, created_at__gte=since, created_at__lt=until, **by_currency
    ).select_related("payment__client")
    for refund in refunds.order_by("created_at"):
        payment = refund.payment
        day, src = c.local(refund.created_at), f"refund:{refund.pk}"
        ref = payment.reference or payment.get_method_display()
        desc = _("Refund to %(client)s") % {"client": payment.client.display_name}
        track = maps.tracking_for(payment.branch_id)
        c.add(
            day,
            refund.currency,
            receivable,
            refund.amount.amount,
            debit=True,
            description=desc,
            reference=ref,
            source=src,
            tracking=track,
        )
        c.add(
            day,
            refund.currency,
            clearing_account(_Ctx(maps), payment),
            refund.amount.amount,
            debit=False,
            description=desc,
            reference=ref,
            source=src,
            tracking=track,
        )
    return c.rows


class _Ctx:
    """The bit of ``builders.Context`` that ``clearing_account`` needs."""

    def __init__(self, maps: Mappings):
        self.maps = maps


def other_postings(
    maps: Mappings, start: date, end: date, tz: str, *, currency: str | None = None
) -> list[Posting]:
    """Provider payouts and tutor pay, for GL exports."""
    from tutortrack.payments.models import ProviderPayout
    from tutortrack.payroll.models import PayItem, Payout

    c = _Collector(maps, tz)
    since, until = local_date_range_to_utc(start, end, tz)
    by_currency: dict[str, Any] = {"currency": currency} if currency else {}
    for payout in ProviderPayout.objects.select_related("account").filter(**by_currency):
        day = payout.arrival_date or c.local(payout.created_at)
        if not start <= day <= end:
            continue
        desc = _("Payout %(ref)s") % {"ref": payout.provider_ref}
        src = f"provider_payout:{payout.pk}"
        c.add(
            day,
            payout.currency,
            maps.account("bank"),
            payout.amount.amount,
            debit=True,
            description=desc,
            reference=payout.provider_ref,
            source=src,
        )
        c.add(
            day,
            payout.currency,
            maps.account("clearing", f"provider:{payout.account.provider}"),
            payout.amount.amount,
            debit=False,
            description=desc,
            reference=payout.provider_ref,
            source=src,
        )
    payable = maps.account("payable")
    approved = Payout.objects.select_related("pay_run", "tutor").filter(
        pay_run__approved_at__gte=since, pay_run__approved_at__lt=until, **by_currency
    )
    for payout in approved.exclude(status__in=[Payout.Status.FAILED, Payout.Status.CARRIED]):
        day, ref = c.local(payout.pay_run.approved_at), payout.pay_run.number
        src = f"bill:{payout.pk}"
        desc = _("Tutor pay %(name)s") % {"name": payout.tutor.full_name}
        track = maps.tracking_for(payout.pay_run.branch_id)
        for item in PayItem.objects.filter(payout=payout).select_related("expense__category"):
            account = maps.account("tutor_cost")
            if item.expense_id and item.expense is not None:
                category = item.expense.category
                account = (
                    maps.find("expense", f"expense_category:{category.pk}")
                    or (
                        AccountRef(category.account_code, category.account_code)
                        if category.account_code and maps.provider == "export"
                        else None
                    )
                    or maps.find("expense")
                    or account
                )
            c.add(
                day,
                payout.currency,
                account,
                item.amount.amount,
                debit=True,
                description=f"{desc}: {item.description}",
                reference=ref,
                source=src,
                tracking=track,
            )
        c.add(
            day,
            payout.currency,
            payable,
            payout.amount.amount,
            debit=False,
            description=desc,
            reference=ref,
            source=src,
            tracking=track,
        )
    paid = Payout.objects.select_related("pay_run", "tutor").filter(
        status=Payout.Status.PAID, paid_at__gte=since, paid_at__lt=until, **by_currency
    )
    for payout in paid:
        day, ref = c.local(payout.paid_at), payout.reference or payout.pay_run.number
        desc = _("Paid %(name)s") % {"name": payout.tutor.full_name}
        src = f"bill_payment:{payout.pk}"
        bank = maps.find("bank", "tutor_payouts") or maps.account("bank")
        c.add(
            day,
            payout.currency,
            payable,
            payout.amount.amount,
            debit=True,
            description=desc,
            reference=ref,
            source=src,
        )
        c.add(
            day,
            payout.currency,
            bank,
            payout.amount.amount,
            debit=False,
            description=desc,
            reference=ref,
            source=src,
        )
    return c.rows


def summarise(postings: list[Posting]) -> list[JournalLine]:
    """One line per account, tax code, tracking and side (a daily summary)."""
    sums: dict[tuple[Any, ...], list[Decimal]] = defaultdict(lambda: [ZERO, ZERO, ZERO])
    names: dict[tuple[Any, ...], AccountRef] = {}
    for p in postings:
        side = "dr" if p.debit else "cr"
        key = (p.account.id, p.tax_code, p.tracking, side)
        names[key] = p.account
        sums[key][0] += p.debit
        sums[key][1] += p.credit
        sums[key][2] += p.tax
    lines = []
    for key, (debit, credit, tax) in sorted(sums.items(), key=lambda kv: str(kv[0])):
        account = names[key]
        lines.append(
            JournalLine(
                account=account.id,
                account_code=account.code,
                debit=debit,
                credit=credit,
                tax_code=key[1],
                tax=tax,
                tracking=key[2],
                description=account.name or account.code,
            )
        )
    return lines


def balance(maps: Mappings, lines: list[JournalLine]) -> list[JournalLine]:
    gap = sum((x.debit for x in lines), ZERO) - sum((x.credit for x in lines), ZERO)
    if not gap:
        return lines
    rounding = maps.account("rounding")
    dr, cr = _signed(-gap, debit=True)
    return [
        *lines,
        JournalLine(
            account=rounding.id,
            account_code=rounding.code,
            debit=dr,
            credit=cr,
            description=_("Rounding"),
        ),
    ]
