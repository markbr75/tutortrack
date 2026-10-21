"""TutorTrack records → accounting documents (E23-T03/T04/T06).

Read-only over billing, payments and payroll (never writes their records). Each object
type declares what must be in the ledger first (``prerequisites``: contact before
invoice before payment) and builds a document from the record's *current* state, so the
same function serves event pushes, retries and backfills.

Object types: ``contact`` (client), ``supplier`` (tutor), ``invoice``, ``credit_note``,
``write_off`` (invoice id), ``payment``, ``refund``, ``provider_payout``, ``bill`` and
``bill_payment`` (payroll payout id), ``journal`` (a local date, summary mode); and two
containers that only fan out: ``pay_run`` and ``pay_statement``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import Sum
from django.utils.translation import gettext as _

from tutortrack.core.context import require_organisation_id
from tutortrack.core.money import Money

from . import journals
from .documents import (
    ContactDoc,
    CreditNoteDoc,
    Document,
    InvoiceDoc,
    JournalDoc,
    Line,
    PaymentDoc,
    PayoutDoc,
    ReallocationDoc,
    RefundDoc,
)
from .errors import MappingMissing, PrerequisiteMissing
from .mappings import Mappings
from .models import AccountingConnection, ExternalRecordLink
from .routing import Scope, routes_to, scope

Ref = tuple[str, str]
CONTAINERS = {"pay_run", "pay_statement"}
# Documents that never change once in the ledger: a synced link is final.
ISSUED_ONCE = {
    "credit_note",
    "write_off",
    "payment",
    "refund",
    "chargeback",
    "provider_payout",
    "bill_payment",
}
SALES_SIDE = {
    "contact",
    "invoice",
    "credit_note",
    "write_off",
    "payment",
    "refund",
    "reallocation",
    "chargeback",
}
OBJECT_TYPES = (
    "contact",
    "supplier",
    "invoice",
    "credit_note",
    "write_off",
    "payment",
    "refund",
    "provider_payout",
    "bill",
    "bill_payment",
    "journal",
    "package_revenue",
    "reallocation",
    "chargeback",
    *sorted(CONTAINERS),
)


class Skip(Exception):
    """This record doesn't go to the ledger (a draft, before the start date...)."""


@dataclass(frozen=True)
class Built:
    doc: Document
    label: str
    void: bool = False  # the record was voided: void it in the ledger
    attach_invoice: str = ""  # our invoice id whose PDF to attach after creating
    meta: dict[str, Any] = field(default_factory=dict)


class Context:
    def __init__(self, conn: AccountingConnection, maps: Mappings | None = None):
        from tutortrack.tenancy.models import Organisation

        self.conn = conn
        self.maps = maps or Mappings(conn.mapping_set, conn.chart)
        org = Organisation.objects.get(pk=require_organisation_id())
        self.tz = ZoneInfo(org.timezone)
        self.org = org
        self._links: dict[Ref, ExternalRecordLink | None] = {}
        self._scope: Scope | None = None

    @property
    def scope(self) -> Scope:
        """The branches this ledger takes (gap G5: per-branch ledgers)."""
        if self._scope is None:
            self._scope = scope(self.conn)
        return self._scope

    def link(self, object_type: str, object_id: Any) -> ExternalRecordLink | None:
        key = (object_type, str(object_id))
        if key not in self._links:
            self._links[key] = ExternalRecordLink.objects.filter(
                connection=self.conn, object_type=object_type, object_id=str(object_id)
            ).first()
        return self._links[key]

    def ext(self, object_type: str, object_id: Any) -> str:
        """The external id of a prerequisite, which must be synced by now."""
        found = self.link(object_type, object_id)
        if found is None or found.status != ExternalRecordLink.Status.SYNCED:
            raise PrerequisiteMissing(
                _("Waiting for the %(what)s to sync first.") % {"what": _type_label(object_type)}
            )
        return found.external_id

    def synced_ext(self, object_type: str, object_id: Any) -> str:
        """External id if synced, else "" (e.g. an invoice from before the start date)."""
        found = self.link(object_type, object_id)
        if found is None or found.status != ExternalRecordLink.Status.SYNCED:
            return ""
        return found.external_id

    def local(self, moment: datetime | None) -> date:
        from tutortrack.core.time import now

        return (moment or now()).astimezone(self.tz).date()

    def check_start(self, day: date) -> None:
        if self.conn.start_date and day < self.conn.start_date:
            raise Skip(_("Dated before the sync start date (use a backfill to include it)."))

    def check_individual(self) -> None:
        if self.conn.mode == AccountingConnection.Mode.SUMMARY:
            raise Skip(_("Posted in the daily summary journal instead."))


def _type_label(object_type: str) -> str:
    labels = {
        "contact": _("client"),
        "supplier": _("tutor"),
        "invoice": _("invoice"),
        "credit_note": _("credit note"),
        "payment": _("payment"),
        "refund": _("refund"),
        "bill": _("tutor bill"),
    }
    return labels.get(object_type, object_type.replace("_", " "))


def _d(money: Money | None) -> Decimal:
    return money.amount if money is not None else Decimal(0)


# --- prerequisites -------------------------------------------------------------------------------


def prerequisites(conn: AccountingConnection, object_type: str, object_id: str) -> list[Ref]:
    from tutortrack.billing.models import CreditNote, Invoice
    from tutortrack.payments.models import Payment, PaymentAllocation, Refund
    from tutortrack.payroll.models import Payout, PayStatement

    if object_type in ("invoice", "write_off"):
        invoice = Invoice.objects.filter(pk=object_id).first()
        if invoice is None:
            return []
        deps = [("contact", str(invoice.client_id))]
        return deps if object_type == "invoice" else [*deps, ("invoice", object_id)]
    if object_type == "credit_note":
        note = CreditNote.objects.filter(pk=object_id).first()
        if note is None:
            return []
        deps = [("contact", str(note.client_id)), ("invoice", str(note.invoice_id))]
        refund = Refund.objects.filter(credit_note=note).first()
        if refund is not None:  # the refund reopens the invoice; the note then credits it
            deps.append(("refund", str(refund.pk)))
        return deps
    if object_type in ("payment", "reallocation"):
        payment = Payment.objects.filter(pk=object_id).first()
        if payment is None:
            return []
        rows = PaymentAllocation.objects.filter(payment=payment, amount_amount__gt=0)
        # Only invoices that belong in this ledger (gap G5: per-branch ledgers).
        invoices = sorted(
            {
                str(invoice_id)
                for invoice_id, branch_id in rows.values_list("invoice_id", "invoice__branch_id")
                if routes_to(conn, branch_id)
            }
        )
        deps = [("contact", str(payment.client_id))]
        if object_type == "reallocation":
            deps.append(("payment", str(payment.pk)))
        return deps + [("invoice", i) for i in invoices]
    if object_type == "refund":
        refund = Refund.objects.select_related("payment").filter(pk=object_id).first()
        if refund is None:
            return []
        deps = [("contact", str(refund.payment.client_id)), ("payment", str(refund.payment_id))]
        return deps + _pending_reallocation(conn, refund.payment_id)
    if object_type == "chargeback":
        from tutortrack.payments.models import Dispute

        dispute = Dispute.objects.select_related("payment").filter(pk=object_id).first()
        if dispute is None:
            return []
        deps = [("contact", str(dispute.payment.client_id)), ("payment", str(dispute.payment_id))]
        return deps + _pending_reallocation(conn, dispute.payment_id)
    if object_type == "bill":
        payout = Payout.objects.filter(pk=object_id).first()
        return [("supplier", str(payout.tutor_id))] if payout is not None else []
    if object_type == "bill_payment":
        payout = Payout.objects.filter(pk=object_id).first()
        if payout is None:
            return []
        return [("supplier", str(payout.tutor_id)), ("bill", object_id)]
    if object_type == "pay_run":
        if not conn.sync_bills:
            return []
        return [
            ("bill", str(pk))
            for pk in Payout.objects.filter(pay_run_id=object_id).values_list("pk", flat=True)
        ]
    if object_type == "pay_statement":
        statement = PayStatement.objects.filter(pk=object_id).first()
        if statement is None or not conn.sync_bills:
            return []
        return [("bill", str(statement.payout_id))]
    return []


def _pending_reallocation(conn: AccountingConnection, payment_id: Any) -> list[Ref]:
    """A refund or chargeback waits for a reallocation of its payment that isn't in the
    ledger yet: it takes money back off the invoices the payment was moved to (gap G5)."""
    link = ExternalRecordLink.objects.filter(
        connection=conn, object_type="reallocation", object_id=str(payment_id)
    ).first()
    if link is None or link.status in (
        ExternalRecordLink.Status.SYNCED,
        ExternalRecordLink.Status.SKIPPED,
    ):
        return []
    return [("reallocation", str(payment_id))]


# --- builders ------------------------------------------------------------------------------------


def build(ctx: Context, object_type: str, object_id: str) -> Built:
    builder = BUILDERS.get(object_type)
    if builder is None:
        raise Skip(_("Nothing to sync for this kind of record."))
    return builder(ctx, object_id)


def _address(address: Any) -> dict[str, str]:
    if address is None:
        return {}
    return {
        "line1": address.line1,
        "line2": address.line2,
        "city": address.city,
        "region": address.region,
        "postcode": address.postcode,
        "country": address.country,
    }


def _contact(ctx: Context, object_id: str) -> Built:
    from tutortrack.people.models import Client

    client = Client.objects.select_related(
        "billing_contact", "primary_contact", "billing_address"
    ).get(pk=object_id)
    person = client.billing_contact or client.primary_contact
    doc = ContactDoc(
        kind="contact",
        ref=str(client.pk),
        name=client.display_name,
        email=getattr(person, "email", "") or "",
        phone=getattr(person, "phone", "") or "",
        address=_address(client.billing_address),
    )
    return Built(doc, client.display_name)


def _supplier(ctx: Context, object_id: str) -> Built:
    from tutortrack.payroll.models import TutorPayProfile
    from tutortrack.people.models import TutorProfile

    tutor = TutorProfile.objects.get(pk=object_id)
    profile = TutorPayProfile.objects.filter(tutor=tutor).first()
    name = (profile.payee_name if profile else "") or tutor.full_name
    doc = ContactDoc(
        kind="contact",
        ref=str(tutor.pk),
        name=name,
        email=tutor.email,
        phone=tutor.phone,
        supplier=True,
    )
    return Built(doc, name)


def line_charge(line: Any) -> Any:
    """The charge behind an invoice line; a separately shown discount line (gap G3) posts
    like the lesson line it belongs to."""
    charge = getattr(line, "charge", None)
    if charge is None and getattr(line, "parent_id", None):
        charge = line.parent.charge
    return charge


def defers_packages() -> bool:
    from tutortrack.tenancy.settings_service import get_setting

    return bool(get_setting("accounting.package_deferred_revenue"))


def revenue_account(maps: Mappings, charge: Any) -> Any:
    """Where a sales line's net posts. With deferred package revenue (gap G3, FR-26-2) a
    package sale is a liability until lessons use the units (``package_postings``)."""
    if charge is not None and charge.kind == "package" and defers_packages():
        return maps.account("deferred_revenue", "package")
    keys, code = revenue_keys(charge)
    return maps.account("revenue", *keys, code=code)


def revenue_keys(charge: Any) -> tuple[list[str], str]:
    """Mapping keys for a charge's revenue account, most specific first, and the account
    code saved on its product or service."""
    keys: list[str] = []
    code = ""
    if charge is None:
        return keys, code
    if charge.product_id:
        keys.append(f"product_category:{charge.product.category}")
        code = charge.product.account_code
    service = None
    if charge.lesson_id:
        service = charge.lesson.service
    elif charge.job_id:
        service = charge.job.service
    if service is not None:
        if service.category_id:
            keys.append(f"service_category:{service.category_id}")
        code = code or service.revenue_account_code
    return keys, code


def sales_line(ctx: Context, line: Any, *, net: Decimal, tax: Decimal, branch_id: Any) -> Line:
    """One invoice (or credit note) line: account by service/product, tax by rate."""
    charge = line_charge(line)
    account = revenue_account(ctx.maps, charge)
    tax_code = ctx.maps.tax_code(charge.tax_rate_id if charge else None, line.tax_percent)
    quantity = line.quantity.normalize() if line.quantity != 1 else None
    description = line.description
    if quantity is not None and getattr(line, "unit_price", None) is not None:
        description = f"{description} ({quantity} x {line.unit_price.amount.normalize()})"
    return Line(
        description=description[:4000],
        account=account.id,
        account_code=account.code,
        net=net,
        tax=tax,
        tax_code=tax_code,
        tracking=ctx.maps.tracking_for(branch_id),
    )


def _rounding(ctx: Context, lines: list[Line], total: Decimal, branch_id: Any) -> list[Line]:
    gap = total - sum((x.gross for x in lines), Decimal(0))
    if not gap:
        return lines
    account = ctx.maps.account("rounding")
    return [
        *lines,
        Line(
            description=_("Rounding"),
            account=account.id,
            account_code=account.code,
            net=gap,
            tax_code=ctx.maps.tax_code(None),
            tracking=ctx.maps.tracking_for(branch_id),
        ),
    ]


def _invoice(ctx: Context, object_id: str) -> Built:
    from tutortrack.billing.models import CreditAllocation, Invoice

    invoice = Invoice.objects.select_related("client").get(pk=object_id)
    label = invoice.number or _("Draft invoice")
    if invoice.status == Invoice.Status.DRAFT:
        raise Skip(_("Drafts aren't synced."))
    ctx.check_individual()
    if invoice.status == Invoice.Status.VOID:
        if not ctx.synced_ext("invoice", invoice.pk):
            raise Skip(_("Voided before it was synced."))
        return Built(InvoiceDoc(kind="invoice", ref=str(invoice.pk), void=True), label, void=True)
    day = invoice.issue_date or ctx.local(invoice.issued_at)
    ctx.check_start(day)
    lines = [
        sales_line(ctx, line, net=line.net.amount, tax=line.tax.amount, branch_id=invoice.branch_id)
        for line in invoice.lines.select_related(
            "charge__product", "charge__lesson__service", "charge__job__service"
        )
    ]
    lines = _rounding(ctx, lines, invoice.total.amount, invoice.branch_id)
    credit = CreditAllocation.objects.filter(invoice=invoice).aggregate(t=Sum("amount_amount"))[
        "t"
    ] or Decimal(0)
    doc = InvoiceDoc(
        kind="invoice",
        ref=str(invoice.pk),
        date=day.isoformat(),
        currency=invoice.currency,
        number=invoice.number,
        contact=ctx.ext("contact", invoice.client_id),
        due_date=(invoice.due_date or day).isoformat(),
        reference=invoice.po_number,
        lines=tuple(lines),
        total=invoice.total.amount,
        credit_applied=credit,
    )
    return Built(doc, label, attach_invoice=str(invoice.pk) if ctx.conn.attach_pdf else "")


def _credit_note(ctx: Context, object_id: str) -> Built:
    from tutortrack.billing.models import CreditAllocation, CreditNote

    note = CreditNote.objects.select_related("invoice").get(pk=object_id)
    ctx.check_individual()
    day = ctx.local(note.issued_at)
    ctx.check_start(day)
    invoice = note.invoice
    invoice_ext = ctx.synced_ext("invoice", invoice.pk)
    if not invoice_ext:
        raise Skip(_("Its invoice isn't in the ledger (issued before the sync start date)."))
    allocate = Decimal(0)
    if note.application == CreditNote.Application.INVOICE:
        # What credit notes have taken off the invoice, less what earlier ones took.
        credit = CreditAllocation.objects.filter(invoice=invoice).aggregate(t=Sum("amount_amount"))[
            "t"
        ] or Decimal(0)
        by_notes = invoice.amount_credited.amount - credit
        earlier = Decimal(0)
        for other in CreditNote.objects.filter(invoice=invoice).exclude(pk=note.pk):
            link = ctx.link("credit_note", other.pk)
            if link is not None and link.status == ExternalRecordLink.Status.SYNCED:
                earlier += Decimal(str(link.meta.get("allocated", "0")))
        allocate = max(min(note.total.amount, by_notes - earlier), Decimal(0))
    lines = []
    for line in note.lines.select_related(
        "invoice_line__charge__product",
        "invoice_line__charge__lesson__service",
        "invoice_line__charge__job__service",
    ):
        source: Any = line.invoice_line or line
        if line.invoice_line is None:
            source.tax_percent = Decimal(0)
            source.quantity = Decimal(1)
        built = sales_line(
            ctx, source, net=line.net.amount, tax=line.tax.amount, branch_id=note.branch_id
        )
        lines.append(Line(**{**built.__dict__, "description": line.description[:4000]}))
    lines = _rounding(ctx, lines, note.total.amount, note.branch_id)
    doc = CreditNoteDoc(
        kind="credit_note",
        ref=str(note.pk),
        date=day.isoformat(),
        currency=note.currency,
        number=note.number,
        contact=ctx.ext("contact", note.client_id),
        invoice=invoice_ext,
        allocate=allocate,
        lines=tuple(lines),
        total=note.total.amount,
        reason=note.reason,
    )
    return Built(doc, note.number, meta={"allocated": str(allocate)})


def _write_off(ctx: Context, object_id: str) -> Built:
    from tutortrack.billing.models import ClientLedgerEntry, Invoice

    invoice = Invoice.objects.get(pk=object_id)
    if invoice.status != Invoice.Status.WRITTEN_OFF:
        raise Skip(_("The invoice isn't written off."))
    ctx.check_individual()
    day = ctx.local(invoice.written_off_at)
    invoice_ext = ctx.synced_ext("invoice", invoice.pk)
    if not invoice_ext:
        raise Skip(_("Its invoice isn't in the ledger (issued before the sync start date)."))
    entry = ClientLedgerEntry.objects.filter(
        type=ClientLedgerEntry.Type.WRITE_OFF, ref_id=str(invoice.pk)
    ).first()
    amount = -entry.amount.amount if entry is not None else Decimal(0)
    if amount <= 0:
        raise Skip(_("Nothing was owed when it was written off."))
    account = ctx.maps.account("bad_debt")
    # With bad debt VAT relief (gap G5) the VAT in the amount written off is reclaimed: a
    # line per tax rate carries it, so the ledger's credit note reduces output VAT.
    lines = tuple(
        Line(
            description=_("Bad debt: %(number)s") % {"number": invoice.number},
            account=account.id,
            account_code=account.code,
            net=net,
            tax=tax,
            tax_code=tax_code,
            tracking=ctx.maps.tracking_for(invoice.branch_id),
        )
        for net, tax, tax_code in journals.write_off_parts(ctx.maps, invoice, amount)
    )
    doc = CreditNoteDoc(
        kind="write_off",
        ref=str(invoice.pk),
        date=day.isoformat(),
        currency=invoice.currency,
        number=f"WO-{invoice.number}"[:40],
        contact=ctx.ext("contact", invoice.client_id),
        invoice=invoice_ext,
        allocate=amount,
        lines=lines,
        total=amount,
        reason=invoice.write_off_reason,
    )
    return Built(doc, _("Write-off of %(number)s") % {"number": invoice.number})


def clearing_account(ctx: Any, payment: Any) -> Any:
    keys = [f"method:{payment.method}"]
    if payment.provider != "manual":
        keys.insert(0, f"provider:{payment.provider}")
    return ctx.maps.account("clearing", *keys)


def _payment(ctx: Context, object_id: str) -> Built:
    from tutortrack.payments.models import Payment, PaymentAllocation

    payment = Payment.objects.select_related("client").get(pk=object_id)
    if payment.status in (Payment.Status.PENDING, Payment.Status.FAILED):
        raise Skip(_("Only received payments are synced."))
    ctx.check_individual()
    day = ctx.local(payment.received_at)
    ctx.check_start(day)
    # What it pays now, before refunds and chargebacks (they post after it, reopening what
    # they took back): a reallocation made before it synced nets out (gap G5).
    paid: dict[str, Decimal] = defaultdict(Decimal)
    numbers: dict[str, str] = {}
    for row in PaymentAllocation.objects.filter(payment=payment).select_related("invoice"):
        external = ctx.synced_ext("invoice", row.invoice_id)
        if external:
            paid[external] += row.amount.amount
            numbers[external] = row.invoice.number
    for _type, _id, start, end, _amount in _takebacks(payment):
        for external, value in _taken(payment, start, end, ctx).items():
            paid[external] += value
    numbers = {k: v for k, v in numbers.items() if paid[k] > 0}
    allocations = tuple(sorted((k, v) for k, v in paid.items() if v > 0))
    allocated = sum((a for _i, a in allocations), Decimal(0))
    label_ref = payment.reference or payment.get_method_display()
    refs = ", ".join(sorted(numbers.values()))
    account = clearing_account(ctx, payment)
    doc = PaymentDoc(
        kind="payment",
        ref=str(payment.pk),
        date=day.isoformat(),
        currency=payment.currency,
        contact=ctx.ext("contact", payment.client_id),
        account=account.id,
        amount=payment.amount.amount,
        reference=f"{label_ref} {refs}".strip()[:255],
        allocations=allocations,
        unallocated=payment.amount.amount - allocated,
    )
    label = _("Payment %(amount)s · %(client)s") % {
        "amount": f"{payment.amount.amount} {payment.currency}",
        "client": payment.client.display_name,
    }
    # What the ledger holds of it, kept up to date by later refunds, chargebacks and
    # reallocations (gap G5).
    return Built(doc, label, meta={"ledger": _amounts(allocations), "total": str(doc.amount)})


def _amounts(pairs: Any) -> dict[str, str]:
    return {str(target): str(amount) for target, amount in pairs if amount}


def _decimals(raw: dict[str, Any]) -> dict[str, Decimal]:
    return {str(k): Decimal(str(v)) for k, v in (raw or {}).items() if Decimal(str(v))}


def _parts(meta: dict[str, Any]) -> tuple[tuple[str, ...], ...]:
    """The provider's parts of a payment as tuples of strings (Xero: invoice, payment id,
    amount; FreeAgent keeps bare explanation URLs)."""
    out = []
    for part in meta.get("parts") or []:
        out.append((str(part),) if isinstance(part, str) else tuple(str(x) for x in part))
    return tuple(out)


def _taken(payment: Any, start: Any, end: Any, ctx: Context) -> dict[str, Decimal]:
    """Allocations a refund or chargeback took back off this ledger's invoices: the
    negative rows written while it was being recorded (``start``..``end``)."""
    from tutortrack.payments.models import PaymentAllocation

    taken: dict[str, Decimal] = defaultdict(Decimal)
    if start is None or end is None:
        return taken
    for row in PaymentAllocation.objects.filter(
        payment=payment, amount_amount__lt=0, created_at__gte=start, created_at__lte=end
    ):
        external = ctx.synced_ext("invoice", row.invoice_id)
        if external:
            taken[external] += -row.amount.amount
    return taken


def _takebacks(payment: Any) -> list[tuple[str, str, Any, Any, Decimal]]:
    """Refunds and lost disputes of a payment: (object type, id, start, end, amount)."""
    from tutortrack.payments.models import Dispute, Refund

    out: list[tuple[str, str, Any, Any, Decimal]] = [
        ("refund", str(r.pk), r.created_at, r.updated_at, r.amount.amount)
        for r in Refund.objects.filter(payment=payment, status=Refund.Status.SUCCEEDED)
    ]
    out += [
        ("chargeback", str(d.pk), d.closed_at, d.updated_at, d.amount.amount)
        for d in Dispute.objects.filter(payment=payment, status=Dispute.Status.LOST)
    ]
    return out


def ledger_state(ctx: Context, payment: Any) -> tuple[dict[str, Decimal], Decimal]:
    """What the ledger holds of a synced payment: its amount per invoice and its total
    (less refunds and chargebacks posted). Payment links synced before gap G5 have no
    record of it, so it is worked out from the allocations at the time."""
    from tutortrack.payments.models import PaymentAllocation

    link = ctx.link("payment", payment.pk)
    meta = link.meta if link is not None else {}
    if "ledger" in meta:
        return _decimals(meta["ledger"]), Decimal(str(meta.get("total", payment.amount.amount)))
    held: dict[str, Decimal] = defaultdict(Decimal)
    synced_at = link.synced_at if link is not None else None
    for row in PaymentAllocation.objects.filter(payment=payment, amount_amount__gt=0):
        if synced_at is not None and row.created_at > synced_at:
            continue
        external = ctx.synced_ext("invoice", row.invoice_id)
        if external:
            held[external] += row.amount.amount
    total = payment.amount.amount
    for object_type, object_id, start, end, amount in _takebacks(payment):
        done = ctx.link(object_type, object_id)
        if done is None or done.status != ExternalRecordLink.Status.SYNCED:
            continue
        total -= amount
        for external, value in _taken(payment, start, end, ctx).items():
            held[external] -= value
    return {k: v for k, v in held.items() if v > 0}, total


def _after(ledger: dict[str, Decimal], taken: dict[str, Decimal]) -> dict[str, str]:
    left = {k: v - taken.get(k, Decimal(0)) for k, v in ledger.items()}
    return {k: str(v) for k, v in left.items() if v > 0}


def _synced_payment(ctx: Context, payment: Any) -> ExternalRecordLink:
    payment_link = ctx.link("payment", payment.pk)
    if payment_link is None or payment_link.status != ExternalRecordLink.Status.SYNCED:
        if payment_link is not None and payment_link.status == ExternalRecordLink.Status.SKIPPED:
            raise Skip(_("Its payment isn't in the ledger."))
        ctx.ext("payment", payment.pk)  # raises "waiting"
    return payment_link  # type: ignore[return-value]


def _takeback(
    ctx: Context,
    payment: Any,
    *,
    ref: str,
    amount: Decimal,
    start: Any,
    end: Any,
    reference: str,
) -> tuple[RefundDoc, dict[str, Any]]:
    """Money going back out of a synced payment (a refund or a lost dispute): reopens what
    it took off invoices, the rest comes out of the client's credit."""
    payment_link = _synced_payment(ctx, payment)
    taken = _taken(payment, start, end, ctx)
    from_invoices = tuple(sorted(taken.items()))
    from_credit = amount - sum((a for _i, a in from_invoices), Decimal(0))
    ledger, total = ledger_state(ctx, payment)
    doc = RefundDoc(
        kind="refund",
        ref=ref,
        date=ctx.local(start).isoformat(),
        currency=payment.currency,
        contact=ctx.ext("contact", payment.client_id),
        account=clearing_account(ctx, payment).id,
        payment=payment_link.external_id,
        amount=amount,
        reference=reference.strip()[:255],
        from_invoices=from_invoices,
        from_credit=from_credit,
        parts=_parts(payment_link.meta),
    )
    # The payment's ledger state once this is posted (``services`` writes it back).
    meta = {
        "payment": str(payment.pk),
        "ledger_after": _after(ledger, taken),
        "total_after": str(total - amount),
    }
    return doc, meta


def _refund(ctx: Context, object_id: str) -> Built:
    from tutortrack.payments.models import Refund

    refund = Refund.objects.select_related("payment__client").get(pk=object_id)
    if refund.status != Refund.Status.SUCCEEDED:
        raise Skip(_("Only completed refunds are synced."))
    ctx.check_individual()
    payment = refund.payment
    doc, meta = _takeback(
        ctx,
        payment,
        ref=str(refund.pk),
        amount=refund.amount.amount,
        start=refund.created_at,
        end=refund.updated_at,
        reference=f"Refund {payment.reference or ''} {refund.reason}",
    )
    label = _("Refund %(amount)s · %(client)s") % {
        "amount": f"{refund.amount.amount} {refund.currency}",
        "client": payment.client.display_name,
    }
    return Built(doc, label, meta=meta)


def _chargeback(ctx: Context, object_id: str) -> Built:
    """A lost dispute (gap G5, FR-11-8): the provider took the money back, so the ledger
    gets it like a refund from the payment, reopening the invoices it had paid."""
    from tutortrack.payments.models import Dispute

    dispute = Dispute.objects.select_related("payment__client").get(pk=object_id)
    if dispute.status != Dispute.Status.LOST:
        raise Skip(_("Only lost disputes take money back."))
    ctx.check_individual()
    payment = dispute.payment
    doc, meta = _takeback(
        ctx,
        payment,
        ref=f"chargeback-{dispute.pk}",
        amount=dispute.amount.amount,
        start=dispute.closed_at,
        end=dispute.updated_at,
        reference=f"Chargeback {payment.reference or ''} {dispute.reason}",
    )
    label = _("Chargeback %(amount)s · %(client)s") % {
        "amount": f"{dispute.amount.amount} {dispute.currency}",
        "client": payment.client.display_name,
    }
    return Built(doc, label, meta=meta)


def _reallocation(ctx: Context, object_id: str) -> Built:
    """A synced payment moved between invoices in TutorTrack (gap G5, FR-11-6): the ledger
    payment is moved to match. What it should hold is the payment's allocations now, plus
    whatever refunds or chargebacks not yet in the ledger took off (they post next)."""
    from tutortrack.payments.models import Payment, PaymentAllocation

    payment = Payment.objects.select_related("client").get(pk=object_id)
    ctx.check_individual()
    link = ctx.link("payment", payment.pk)
    if link is None or link.status != ExternalRecordLink.Status.SYNCED:
        raise Skip(_("Its payment isn't in the ledger yet; it goes with its allocations then."))
    want: dict[str, Decimal] = defaultdict(Decimal)
    rows = PaymentAllocation.objects.filter(payment=payment)
    for row in rows:
        external = ctx.synced_ext("invoice", row.invoice_id)
        if external:
            want[external] += row.amount.amount
    for object_type, object_id_, start, end, _amount in _takebacks(payment):
        done = ctx.link(object_type, object_id_)
        if done is not None and done.status in (
            ExternalRecordLink.Status.SYNCED,
            ExternalRecordLink.Status.SKIPPED,
        ):
            continue
        for external, value in _taken(payment, start, end, ctx).items():
            want[external] += value
    held, total = ledger_state(ctx, payment)
    allocations = tuple(sorted((k, v) for k, v in want.items() if v > 0))
    previous = tuple(sorted(held.items()))
    if allocations == previous:
        raise Skip(_("The ledger already shows these allocations."))
    if sum((a for _k, a in allocations), Decimal(0)) > total:
        raise Skip(_("The allocations are more than the ledger holds of the payment."))
    latest = rows.order_by("-created_at").values_list("created_at", flat=True).first()
    doc = ReallocationDoc(
        kind="reallocation",
        ref=str(payment.pk),
        date=ctx.local(latest).isoformat(),
        currency=payment.currency,
        contact=ctx.ext("contact", payment.client_id),
        account=clearing_account(ctx, payment).id,
        payment=link.external_id,
        paid_on=ctx.local(payment.received_at).isoformat(),
        reference=(payment.reference or payment.get_method_display())[:255],
        total=total,
        allocations=allocations,
        previous=previous,
        parts=_parts(link.meta),
    )
    label = _("Reallocation of %(amount)s · %(client)s") % {
        "amount": f"{payment.amount.amount} {payment.currency}",
        "client": payment.client.display_name,
    }
    return Built(
        doc,
        label,
        meta={"payment": str(payment.pk), "ledger_after": _amounts(allocations)},
    )


def _provider_payout(ctx: Context, object_id: str) -> Built:
    from tutortrack.payments.models import Payment, ProviderPayout

    payout = ProviderPayout.objects.select_related("account").get(pk=object_id)
    day = payout.arrival_date or ctx.local(payout.created_at)
    ctx.check_start(day)
    covered: set[str] = set()
    for link in ExternalRecordLink.objects.filter(
        connection=ctx.conn, object_type="provider_payout"
    ).exclude(object_id=str(payout.pk)):
        covered.update(link.meta.get("payments", []))
    payments = [
        p
        for p in Payment.objects.filter(
            account=payout.account,
            currency=payout.currency,
            fee_amount__isnull=False,
            received_at__lte=payout.created_at,
        ).order_by("received_at")
        if str(p.pk) not in covered
    ]
    fees = sum((_d(p.fee) for p in payments), Decimal(0))
    provider = payout.account.provider
    doc = PayoutDoc(
        kind="provider_payout",
        ref=str(payout.pk),
        date=day.isoformat(),
        currency=payout.currency,
        reference=payout.provider_ref,
        clearing_account=ctx.maps.account("clearing", f"provider:{provider}").id,
        bank_account=ctx.maps.account("bank").id,
        fee_account=ctx.maps.account("fees").id if fees else "",
        net=payout.amount.amount,
        fees=fees,
        fee_tax_code=ctx.maps.tax_code(None) if fees else "",
    )
    label = _("Payout %(ref)s") % {"ref": payout.provider_ref}
    return Built(doc, label, meta={"payments": sorted(str(p.pk) for p in payments)})


def _bill_payout(ctx: Context, object_id: str) -> Any:
    from tutortrack.payroll.models import Payout
    from tutortrack.people.models import TutorProfile

    if not ctx.conn.sync_bills:
        raise Skip(_("Tutor bills aren't synced (see the sync options)."))
    payout = Payout.objects.select_related("tutor", "pay_run").get(pk=object_id)
    if payout.tutor.employment_type == TutorProfile.Employment.EMPLOYEE:
        raise Skip(_("Employees are paid through payroll, not bills."))
    if payout.status in (Payout.Status.FAILED, Payout.Status.CARRIED):
        raise Skip(_("This payout failed or was carried forward."))
    return payout


def _bill(ctx: Context, object_id: str) -> Built:
    from tutortrack.payroll.models import PayItem, PayStatement

    payout = _bill_payout(ctx, object_id)
    pay_run = payout.pay_run
    day = ctx.local(pay_run.approved_at)
    ctx.check_start(day)
    statement = PayStatement.objects.filter(payout=payout).first()
    tutor_cost = ctx.maps.account("tutor_cost")
    groups: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    for item in PayItem.objects.filter(payout=payout).select_related("expense__category"):
        account = tutor_cost
        if item.expense_id and item.expense is not None:
            category = item.expense.category
            account = (
                ctx.maps.find("expense", f"expense_category:{category.pk}")
                or (ctx.maps.by_code.get(category.account_code) if category.account_code else None)
                or ctx.maps.find("expense")
                or tutor_cost
            )
        groups[(account.id, account.code, item.get_kind_display())] += item.amount.amount
    vat = statement.vat.amount if statement is not None else Decimal(0)
    tax_code = ""
    if vat:
        mapped = ctx.maps.find("purchase_tax")
        if mapped is None:
            raise MappingMissing(
                _("Choose the tax code for VAT on tutors' self-billing invoices."),
                "tax_mapping_missing",
            )
        tax_code = mapped.id
    else:
        tax_code = ctx.maps.tax_code(None)
    nets = list(groups.values())
    taxes = (
        [m.amount for m in Money(vat, payout.currency).allocate(nets)]
        if vat and sum(nets, Decimal(0))
        else [Decimal(0)] * len(nets)
    )
    lines = tuple(
        Line(
            description=f"{label} · {pay_run.number}",
            account=account_id,
            account_code=code,
            net=net,
            tax=tax,
            tax_code=tax_code,
            tracking=ctx.maps.tracking_for(pay_run.branch_id),
        )
        for ((account_id, code, label), net), tax in zip(groups.items(), taxes, strict=True)
    )
    number = (
        statement.number if statement is not None else f"{pay_run.number}-{payout.tutor.pk}"[:40]
    )
    doc = InvoiceDoc(
        kind="bill",
        ref=str(payout.pk),
        date=day.isoformat(),
        currency=payout.currency,
        number=number,
        contact=ctx.ext("supplier", payout.tutor_id),
        due_date=day.isoformat(),
        reference=pay_run.number,
        lines=lines,
        total=payout.amount.amount + vat,
        bill=True,
    )
    return Built(doc, f"{number} · {payout.tutor.full_name}")


def _bill_payment(ctx: Context, object_id: str) -> Built:
    from tutortrack.payroll.models import Payout

    payout = _bill_payout(ctx, object_id)
    if payout.status != Payout.Status.PAID:
        raise Skip(_("Not paid yet."))
    day = ctx.local(payout.paid_at)
    ctx.check_start(day)
    bill = ctx.link("bill", payout.pk)
    if bill is not None and bill.status == ExternalRecordLink.Status.SKIPPED:
        raise Skip(_("Its bill isn't in the ledger."))
    bill_ext = ctx.ext("bill", payout.pk)
    account = ctx.maps.find("bank", "tutor_payouts") or ctx.maps.account("bank")
    doc = PaymentDoc(
        kind="bill_payment",
        ref=str(payout.pk),
        date=day.isoformat(),
        currency=payout.currency,
        contact=ctx.ext("supplier", payout.tutor_id),
        account=account.id,
        amount=payout.amount.amount,
        reference=(payout.reference or payout.pay_run.number)[:255],
        allocations=((bill_ext, payout.amount.amount),),
        bill=True,
    )
    return Built(doc, _("Payout to %(name)s") % {"name": payout.tutor.full_name})


def journal_id(day: date, currency: str = "") -> str:
    """A summary journal's id: the day (base currency), or ``<day>:<currency>`` for the
    same day's records in another currency (gap G5)."""
    return f"{day.isoformat()}:{currency}" if currency else day.isoformat()


def _journal(ctx: Context, object_id: str) -> Built:
    if ctx.conn.mode != AccountingConnection.Mode.SUMMARY:
        raise Skip(_("Summary journals are off."))
    raw_day, _sep, other = object_id.partition(":")
    day = date.fromisoformat(raw_day)
    ctx.check_start(day)
    base = ctx.conn.base_currency or ctx.org.default_currency
    currency = other or base
    postings = journals.sales_postings(
        ctx.maps, day, day, str(ctx.tz), currency=currency, scope=ctx.scope
    )
    rates: dict[str, str] = {}
    if currency != base:
        # Ledgers take manual journals in their base currency only: convert at the day's
        # rate, line by line (half-up), and post any difference to currency conversion.
        postings, rates = journals.convert(postings, base, journals.RateSource())
    lines = journals.summarise(postings)
    if not lines:
        raise Skip(_("Nothing happened that day."))
    lines = journals.balance(ctx.maps, lines, kind="fx" if rates else "rounding")
    if rates:
        rate = next(iter(rates.values()))
        narration = _("TutorTrack daily summary %(day)s (%(currency)s at %(rate)s %(base)s)") % {
            "day": raw_day,
            "currency": currency,
            "rate": rate,
            "base": base,
        }
    else:
        narration = _("TutorTrack daily summary %(day)s (%(currency)s)") % {
            "day": raw_day,
            "currency": currency,
        }
    doc = JournalDoc(
        kind="journal",
        ref=object_id,
        date=raw_day,
        currency=base,
        narration=narration,
        lines=tuple(lines),
    )
    label = (
        _("Summary journal %(day)s (%(currency)s)") % {"day": raw_day, "currency": currency}
        if other
        else _("Summary journal %(day)s") % {"day": raw_day}
    )
    return Built(doc, label, meta={"currency": currency, "rates": rates} if rates else {})


def _package_revenue(ctx: Context, object_id: str) -> Built:
    """Individual mode: the day's deferred package revenue released as one manual journal
    (summary mode carries the same lines in the daily summary journal)."""
    if ctx.conn.mode == AccountingConnection.Mode.SUMMARY:
        raise Skip(_("Posted in the daily summary journal instead."))
    if not defers_packages():
        raise Skip(_("Package revenue isn't deferred."))
    day = date.fromisoformat(object_id)
    ctx.check_start(day)
    currency = ctx.conn.base_currency or ctx.org.default_currency
    postings = journals.package_postings(
        ctx.maps, day, day, str(ctx.tz), currency=currency, scope=ctx.scope
    )
    lines = journals.summarise(postings)
    if not lines:
        raise Skip(_("No package units were used that day."))
    doc = JournalDoc(
        kind="journal",
        ref=f"package-revenue-{object_id}",
        date=object_id,
        currency=currency,
        narration=_("TutorTrack package revenue %(day)s (%(currency)s)")
        % {"day": object_id, "currency": currency},
        lines=tuple(lines),
    )
    return Built(doc, _("Package revenue %(day)s") % {"day": object_id})


BUILDERS = {
    "package_revenue": _package_revenue,
    "reallocation": _reallocation,
    "chargeback": _chargeback,
    "contact": _contact,
    "supplier": _supplier,
    "invoice": _invoice,
    "credit_note": _credit_note,
    "write_off": _write_off,
    "payment": _payment,
    "refund": _refund,
    "provider_payout": _provider_payout,
    "bill": _bill,
    "bill_payment": _bill_payment,
    "journal": _journal,
}


def label_for(object_type: str, object_id: str) -> str:
    """A short label for links that never got built (skipped containers, errors)."""
    return f"{_type_label(object_type).capitalize()} {object_id[:8]}"
