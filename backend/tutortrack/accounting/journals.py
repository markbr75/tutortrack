"""Double-entry postings for summary journals (E23-T06) and GL exports (E23-T08).

Sales side (per record, in the organisation's local dates):

* invoice issued: Dr receivable (gross) / Cr revenue (net per line) / Cr sales tax;
* invoice voided: the reverse; credit note: Dr revenue, Dr sales tax / Cr receivable;
* write-off: Dr bad debts / Cr receivable;
* payment received: Dr clearing / Cr receivable; refund and lost dispute (chargeback):
  the reverse;
* provider fees: Dr fees / Cr clearing.

With ``accounting.bad_debt_vat_relief`` a write-off reclaims the VAT in it (gap G5):
Dr bad debts (net) and Dr sales tax (the VAT fraction of the amount written off) / Cr
receivable.

Exports add provider payouts (Dr bank / Cr clearing) and tutor pay (bills: Dr tutor
costs or expenses, Dr input VAT on self-billing invoices / Cr payable; payouts: Dr
payable / Cr bank).

Every function takes a ``routing.Scope``: a ledger only posts its branches' records
(gap G5: per-branch ledgers). ``convert`` turns postings in another currency into the
ledger's base currency at the day's rate (summary journals in other currencies, gap G5).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.utils.translation import gettext as _

from tutortrack.core.money import Money, minor_units
from tutortrack.core.time import local_date_range_to_utc

from .documents import JournalLine
from .errors import MappingMissing
from .mappings import AccountRef, Mappings
from .routing import EVERYTHING, Scope

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
    from .builders import line_charge, revenue_account

    charge = line_charge(line)
    account = revenue_account(c.maps, charge)
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
    maps: Mappings,
    start: date,
    end: date,
    tz: str,
    *,
    currency: str | None = None,
    scope: Scope = EVERYTHING,
) -> list[Posting]:
    from tutortrack.billing.models import ClientLedgerEntry, CreditNote, Invoice
    from tutortrack.payments.models import Dispute, Payment, Refund

    c = _Collector(maps, tz)
    since, until = local_date_range_to_utc(start, end, tz)
    by_currency: dict[str, Any] = {"currency": currency} if currency else {}
    issued = scope.filter(
        Invoice.objects.filter(issue_date__gte=start, issue_date__lte=end, **by_currency)
    )
    for invoice in issued.exclude(status=Invoice.Status.DRAFT).order_by("issue_date", "number"):
        _invoice(c, invoice, invoice.issue_date, reverse=False)
    for invoice in scope.filter(
        Invoice.objects.filter(
            status=Invoice.Status.VOID, voided_at__gte=since, voided_at__lt=until, **by_currency
        )
    ).exclude(issue_date__isnull=True):
        _invoice(c, invoice, c.local(invoice.voided_at), reverse=True)
    receivable = maps.account("receivable")
    for note in scope.filter(
        CreditNote.objects.filter(issued_at__gte=since, issued_at__lt=until, **by_currency)
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
        if not scope.allows(invoice.branch_id if invoice else None):
            continue
        ref = invoice.number if invoice else entry.ref_id
        day, amount = c.local(entry.occurred_at), -entry.amount.amount
        desc = _("Write-off of %(n)s") % {"n": ref}
        track = maps.tracking_for(invoice.branch_id if invoice else None)
        for net, tax, tax_code in write_off_parts(maps, invoice, amount):
            c.add(
                day,
                entry.currency,
                maps.account("bad_debt"),
                net,
                debit=True,
                description=desc,
                reference=ref,
                source=f"write_off:{entry.ref_id}",
                tax_code=tax_code if tax else "",
                tax=tax,
                tracking=track,
            )
            c.add(
                day,
                entry.currency,
                maps.account("sales_tax") if tax else maps.account("bad_debt"),
                tax,
                debit=True,
                description=_("VAT reclaimed on the write-off of %(n)s") % {"n": ref},
                reference=ref,
                source=f"write_off:{entry.ref_id}",
                tax_code=tax_code,
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

    received = scope.filter(
        Payment.objects.filter(
            received_at__gte=since,
            received_at__lt=until,
            status__in=[
                Payment.Status.SUCCEEDED,
                Payment.Status.REFUNDED,
                Payment.Status.PARTIALLY_REFUNDED,
                Payment.Status.DISPUTED,
            ],
            **by_currency,
        )
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
    refunds = scope.filter(
        Refund.objects.filter(
            status=Refund.Status.SUCCEEDED,
            created_at__gte=since,
            created_at__lt=until,
            **by_currency,
        ),
        "payment__branch_id",
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
    # Lost disputes (chargebacks, gap G5): the money goes back out like a refund.
    lost = scope.filter(
        Dispute.objects.filter(
            status=Dispute.Status.LOST, closed_at__gte=since, closed_at__lt=until, **by_currency
        ),
        "payment__branch_id",
    ).select_related("payment__client")
    for dispute in lost.order_by("closed_at"):
        payment = dispute.payment
        day, src = c.local(dispute.closed_at), f"chargeback:{dispute.pk}"
        ref = payment.reference or payment.get_method_display()
        desc = _("Chargeback to %(client)s") % {"client": payment.client.display_name}
        track = maps.tracking_for(payment.branch_id)
        for account, debit in (
            (receivable, True),
            (clearing_account(_Ctx(maps), payment), False),
        ):
            c.add(
                day,
                dispute.currency,
                account,
                dispute.amount.amount,
                debit=debit,
                description=desc,
                reference=ref,
                source=src,
                tracking=track,
            )
    return c.rows + package_postings(maps, start, end, tz, currency=currency, scope=scope)


def bad_debt_vat(
    amount: Money, groups: list[tuple[Decimal, Decimal]]
) -> list[tuple[Decimal, Decimal]]:
    """Split a written-off ``amount`` over an invoice's tax groups, each ``(gross, tax)``:
    in proportion to their gross (largest remainder, so the parts add up exactly), and
    each part's VAT is the group's VAT fraction of it (tax / gross), rounded half-up to the
    minor unit. Returns ``(net, tax)`` per group, in order."""
    if not groups:
        return []
    zero = Money.zero(amount.currency)
    weights = [max(gross, ZERO) for gross, _tax in groups]
    if not sum(weights, ZERO):
        return [(amount.amount if i == 0 else ZERO, ZERO) for i in range(len(groups))]
    out: list[tuple[Decimal, Decimal]] = []
    for (gross, tax), part in zip(groups, amount.allocate(weights), strict=True):
        vat = zero
        if gross > 0 and tax > 0 and part.is_positive():
            vat = min((part * tax / gross).round_to_minor(), part)
        out.append(((part - vat).amount, vat.amount))
    return out


def write_off_parts(
    maps: Mappings, invoice: Any, amount: Decimal
) -> list[tuple[Decimal, Decimal, str]]:
    """What a write-off posts to bad debts: ``(net, tax, tax code)`` per tax rate. Without
    ``accounting.bad_debt_vat_relief`` it is one line, all net and outside VAT; with it the
    VAT in the amount written off is reclaimed at the invoice's rates (gap G5)."""
    from tutortrack.tenancy.settings_service import get_setting

    if invoice is None or not get_setting("accounting.bad_debt_vat_relief"):
        return [(amount, ZERO, maps.tax_code(None))]
    from .builders import line_charge

    groups: dict[tuple[str, Decimal], list[Decimal]] = {}
    for line in invoice.lines.select_related("charge", "parent__charge"):
        charge = line_charge(line)
        rate = str(charge.tax_rate_id) if charge is not None and charge.tax_rate_id else ""
        total = groups.setdefault((rate, line.tax_percent), [ZERO, ZERO])
        total[0] += line.net.amount + line.tax.amount
        total[1] += line.tax.amount
    keys = sorted(groups)
    if not keys:
        return [(amount, ZERO, maps.tax_code(None))]
    parts = bad_debt_vat(
        Money(amount, invoice.currency), [(groups[k][0], groups[k][1]) for k in keys]
    )
    out = []
    for (rate, percent), (net, tax) in zip(keys, parts, strict=True):
        if net or tax:
            code = maps.tax_code(rate or None, percent) if tax else maps.tax_code(None)
            out.append((net, tax, code))
    return out or [(amount, ZERO, maps.tax_code(None))]


def package_postings(
    maps: Mappings,
    start: date,
    end: date,
    tz: str,
    *,
    currency: str | None = None,
    scope: Scope = EVERYTHING,
) -> list[Posting]:
    """Deferred package revenue released (gap G3, FR-26-2 "package liabilities"): with
    ``accounting.package_deferred_revenue`` a package sale credits the deferred revenue
    liability; each day the revenue its used (or expired) units earned moves from the
    liability to sales: Dr deferred revenue / Cr revenue. Amounts come from
    ``billing.packages.recognised_net`` (net of tax, cumulative, so they add up exactly to
    the sale's net once every unit is used or expired)."""
    from tutortrack.billing import packages
    from tutortrack.billing.models import PackageConsumption, PackagePurchase

    from .builders import defers_packages, revenue_keys

    if not defers_packages():
        return []
    c = _Collector(maps, tz)
    since, until = local_date_range_to_utc(start, end, tz)
    by_currency: dict[str, Any] = {"currency": currency} if currency else {}
    moves = PackageConsumption.objects.filter(
        created_at__gte=since, created_at__lt=until, **by_currency
    ).values_list("purchase_id", "created_at")
    days: dict[Any, set[date]] = defaultdict(set)
    for purchase_id, at in moves:
        days[purchase_id].add(c.local(at))
    purchases = scope.filter(PackagePurchase.objects.filter(pk__in=list(days))).select_related(
        "charge"
    )
    for purchase in purchases.order_by("created_at"):
        desc = _("Package revenue: %(name)s") % {"name": purchase.name}
        ref, src = purchase.name[:100], f"package:{purchase.pk}"
        track = maps.tracking_for(purchase.branch_id)
        keys, code = revenue_keys(purchase.charge)
        for day in sorted(days[purchase.pk]):
            day_start, day_end = local_date_range_to_utc(day, day, tz)
            released = packages.recognised_net(purchase, day_end) - packages.recognised_net(
                purchase, day_start
            )
            for account, debit in (
                (maps.account("deferred_revenue", "package"), True),
                (maps.account("revenue", "package", *keys, code=code), False),
            ):
                c.add(
                    day,
                    purchase.currency,
                    account,
                    released.amount,
                    debit=debit,
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
    maps: Mappings,
    start: date,
    end: date,
    tz: str,
    *,
    currency: str | None = None,
    scope: Scope = EVERYTHING,
) -> list[Posting]:
    """Provider payouts and tutor pay, for GL exports."""
    from tutortrack.payments.models import ProviderPayout
    from tutortrack.payroll.models import PayItem, Payout, PayStatement

    c = _Collector(maps, tz)
    since, until = local_date_range_to_utc(start, end, tz)
    by_currency: dict[str, Any] = {"currency": currency} if currency else {}
    payouts = scope.filter(
        ProviderPayout.objects.select_related("account").filter(**by_currency),
        "account__branch_id",
    )
    for payout in payouts:
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
    approved = scope.filter(
        Payout.objects.select_related("pay_run", "tutor").filter(
            pay_run__approved_at__gte=since, pay_run__approved_at__lt=until, **by_currency
        ),
        "pay_run__branch_id",
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
        # VAT on a self-billing invoice (gap G5): input VAT the organisation reclaims, owed
        # to the tutor with the bill (as the bill synced to a ledger carries it).
        statement = PayStatement.objects.filter(payout=payout).first()
        vat = statement.vat.amount if statement is not None else ZERO
        if statement is not None and vat:
            purchase_tax = maps.find("purchase_tax")
            c.add(
                day,
                payout.currency,
                maps.find("input_tax") or maps.account("sales_tax"),
                vat,
                debit=True,
                description=_("VAT on self-billing invoice %(n)s") % {"n": statement.number},
                reference=ref,
                source=src,
                tax_code=(purchase_tax.code or purchase_tax.id) if purchase_tax else "",
                tracking=track,
            )
        c.add(
            day,
            payout.currency,
            payable,
            payout.amount.amount + vat,
            debit=False,
            description=desc,
            reference=ref,
            source=src,
            tracking=track,
        )
    paid = scope.filter(
        Payout.objects.select_related("pay_run", "tutor").filter(
            status=Payout.Status.PAID, paid_at__gte=since, paid_at__lt=until, **by_currency
        ),
        "pay_run__branch_id",
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


def balance(
    maps: Mappings, lines: list[JournalLine], *, kind: str = "rounding"
) -> list[JournalLine]:
    """Close any gap with one line: rounding, or (``kind="fx"``) the currency conversion
    differences account, which falls back to rounding when it isn't mapped."""
    gap = sum((x.debit for x in lines), ZERO) - sum((x.credit for x in lines), ZERO)
    if not gap:
        return lines
    account = (maps.find(kind) if kind != "rounding" else None) or maps.account("rounding")
    dr, cr = _signed(-gap, debit=True)
    label = _("Currency conversion difference") if kind == "fx" else _("Rounding")
    return [
        *lines,
        JournalLine(
            account=account.id,
            account_code=account.code,
            debit=dr,
            credit=cr,
            description=label,
        ),
    ]


class RateSource:
    """Exchange rates for ``convert``: the platform's daily rates (E26 ``FxRate``, the
    latest on or before the day)."""

    def __init__(self) -> None:
        from tutortrack.reporting.fx import Converter

        self.converter = Converter()

    def rate(self, source: str, target: str, day: date) -> Decimal | None:
        return self.converter.rate(source, target, day)


def convert_amount(amount: Decimal, rate: Decimal, currency: str) -> Decimal:
    """``amount`` x ``rate``, rounded half-up to ``currency``'s minor unit (line level)."""
    quantum = Decimal(1).scaleb(-minor_units(currency))
    return (amount * rate).quantize(quantum, rounding=ROUND_HALF_UP)


def convert(postings: list[Posting], base: str, rates: Any) -> tuple[list[Posting], dict[str, str]]:
    """Postings in other currencies, in ``base`` at each day's rate (rounded per posting).
    Returns the converted postings and the rates used (``{"EUR 2026-10-01": "0.85"}``).
    Raises ``MappingMissing`` (``fx_rate_missing``) when a day has no rate."""
    out: list[Posting] = []
    used: dict[str, str] = {}
    for p in postings:
        if p.currency == base:
            out.append(p)
            continue
        rate = rates.rate(p.currency, base, p.date)
        if rate is None:
            raise MappingMissing(
                _("There's no exchange rate from %(source)s to %(target)s for %(day)s yet.")
                % {"source": p.currency, "target": base, "day": p.date.isoformat()},
                "fx_rate_missing",
            )
        used[f"{p.currency} {p.date.isoformat()}"] = str(rate)
        out.append(
            Posting(
                p.date,
                base,
                p.account,
                convert_amount(p.debit, rate, base),
                convert_amount(p.credit, rate, base),
                p.description,
                p.reference,
                p.tax_code,
                convert_amount(p.tax, rate, base),
                p.tracking,
                p.source,
            )
        )
    return out, used


def activity_currencies(start: date, end: date, tz: str, scope: Scope = EVERYTHING) -> set[str]:
    """Currencies with sales-side activity in the period (a summary journal each)."""
    from tutortrack.billing.models import ClientLedgerEntry, CreditNote, Invoice
    from tutortrack.payments.models import Dispute, Payment, Refund

    since, until = local_date_range_to_utc(start, end, tz)
    found: set[str] = set()
    for qs in (
        scope.filter(Invoice.objects.filter(issue_date__gte=start, issue_date__lte=end)).exclude(
            status=Invoice.Status.DRAFT
        ),
        scope.filter(Invoice.objects.filter(voided_at__gte=since, voided_at__lt=until)),
        scope.filter(CreditNote.objects.filter(issued_at__gte=since, issued_at__lt=until)),
        scope.filter(Payment.objects.filter(received_at__gte=since, received_at__lt=until)),
        scope.filter(
            Refund.objects.filter(created_at__gte=since, created_at__lt=until),
            "payment__branch_id",
        ),
        scope.filter(
            Dispute.objects.filter(closed_at__gte=since, closed_at__lt=until),
            "payment__branch_id",
        ),
        ClientLedgerEntry.objects.filter(
            type=ClientLedgerEntry.Type.WRITE_OFF, occurred_at__gte=since, occurred_at__lt=until
        ),
    ):
        found.update(qs.values_list("currency", flat=True).distinct())
    return {c for c in found if c}
