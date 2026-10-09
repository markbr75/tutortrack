"""Client billing writes (E10): charges, invoices, credit notes, credit, payment requests and
invoice runs. Every money movement posts to the ledger (``ledger.post``) in the same
transaction, and every issued document is immutable (corrections are credit notes)."""

from __future__ import annotations

import secrets
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import QuerySet
from django.utils.translation import gettext as _

from tutortrack.catalogue.models import Product, TaxRate
from tutortrack.catalogue.rates import tax_on
from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money, sum_money
from tutortrack.core.sequences import next_number
from tutortrack.core.time import now
from tutortrack.people.models import Client, Student
from tutortrack.scheduling.models import Lesson, LessonAttendee
from tutortrack.tenancy.settings_service import get_setting

from . import events, ledger
from .models import (
    Charge,
    ClientLedgerEntry,
    CreditAllocation,
    CreditNote,
    CreditNoteLine,
    Invoice,
    InvoiceLine,
    InvoiceRun,
    PaymentRequest,
)

HUNDRED = Decimal(100)
LESSON_KINDS = (
    Charge.Kind.LESSON,
    Charge.Kind.ADVANCE,
    Charge.Kind.LATE_CANCELLATION,
    Charge.Kind.RECONCILIATION,
)


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def org_today() -> date:
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    return now().astimezone(ZoneInfo(org.timezone)).date()


# --- line amounts -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Amounts:
    net: Money
    tax: Money
    gross: Money


def amounts_for(price: Money, percent: Decimal, *, inclusive: bool, exempt: bool) -> Amounts:
    """Net/tax/gross for a line priced at ``price`` (FR-10-11), rounded half-up per line.
    Inclusive prices contain the tax; exclusive prices have it added. Tax-exempt clients
    pay the price with no tax."""
    price = price.round_to_minor()
    if exempt or not percent:
        return Amounts(price, Money.zero(price.currency), price)
    tax = tax_on(price, percent, inclusive)
    if inclusive:
        return Amounts(price - tax, tax, price)
    return Amounts(price, tax, price + tax)


def _inclusive() -> bool:
    return bool(get_setting("billing.prices_include_tax"))


# --- lesson charges (T02) -----------------------------------------------------------------------


def _attendee_price(attendee: LessonAttendee, percent: Decimal) -> Money:
    if attendee.charge_amount is None:
        return Money.zero(attendee.currency)
    return (attendee.charge_amount * percent / HUNDRED).round_to_minor()


def _desired_price(attendee: LessonAttendee, lesson: Lesson, advance: bool) -> Money:
    """What the attendee should be billed for this lesson right now."""
    from tutortrack.delivery.selectors import makeup_students

    zero = Money.zero(attendee.currency)
    if str(attendee.student_id) in makeup_students(lesson):
        return zero
    if lesson.status in {Lesson.Status.COMPLETED, Lesson.Status.CANCELLED}:
        if not attendee.chargeable:
            return zero
        return _attendee_price(attendee, attendee.charge_percent)
    if lesson.status == Lesson.Status.PLANNED and advance:
        return _attendee_price(attendee, HUNDRED)
    return zero


def _billed_price(charge: Charge) -> Money:
    return (charge.unit_price * charge.quantity).round_to_minor()


def _lesson_kind(lesson: Lesson, has_invoiced: bool, advance: bool) -> str:
    if has_invoiced:
        return Charge.Kind.RECONCILIATION
    if lesson.status == Lesson.Status.CANCELLED:
        return Charge.Kind.LATE_CANCELLATION
    if lesson.status == Lesson.Status.PLANNED and advance:
        return Charge.Kind.ADVANCE
    return Charge.Kind.LESSON


def _describe(kind: str, lesson: Lesson, student: Student) -> str:
    names: dict[str, str] = {
        Charge.Kind.LATE_CANCELLATION: _("Late cancellation fee"),
        Charge.Kind.RECONCILIATION: _("Adjustment"),
    }
    prefix = names.get(kind)
    title = lesson.title
    return f"{prefix} \N{EN DASH} {title}" if prefix else title


def sync_attendee_charge(
    attendee: LessonAttendee, *, advance: bool = False, user: Any = None
) -> Charge | None:
    """Make the attendee's charges match what they should pay (idempotent, FR-10-2).

    Uninvoiced charges are replaced by one charge for the difference between what should
    be billed and what is already invoiced. A negative difference after invoicing becomes
    a credit line on the next invoice (``reconciliation``)."""
    lesson = attendee.lesson
    charges = list(
        Charge.objects.select_for_update()
        .filter(lesson_attendee=attendee, kind__in=LESSON_KINDS)
        .exclude(status=Charge.Status.VOID)
    )
    pending = [c for c in charges if c.status == Charge.Status.UNINVOICED and c.invoice_id is None]
    locked = [c for c in charges if c not in pending]  # invoiced, or on a draft
    already_advanced = any(c.kind == Charge.Kind.ADVANCE for c in charges)
    desired = _desired_price(attendee, lesson, advance or already_advanced)
    billed = sum_money((_billed_price(c) for c in locked), desired.currency)
    delta = desired - billed
    if pending and len(pending) == 1 and _billed_price(pending[0]) == delta:
        return pending[0]
    for charge in pending:
        void_charge(charge, reason="replaced")
    if delta.is_zero():
        return None
    kind = _lesson_kind(lesson, bool(locked), advance or already_advanced)
    snapshot = attendee.charge_snapshot or {}
    percent = Decimal(str(snapshot.get("tax_percent", "0")))
    tax_rate_id = snapshot.get("tax_rate_id")
    client = attendee.client
    tutor = lesson.tutors.select_related("tutor").first()
    return _create_charge(
        client=client,
        student=attendee.student,
        job=lesson.job,
        lesson=lesson,
        lesson_attendee=attendee,
        kind=kind,
        source_key=f"attendee:{attendee.pk}:{len(locked)}",
        description=_describe(kind, lesson, attendee.student),
        day=lesson.start.astimezone(ZoneInfo(lesson.timezone)).date(),
        price=delta,
        quantity=Decimal(1),
        unit="lesson",
        tax_percent=percent,
        tax_rate_id=tax_rate_id,
        tutor=tutor.tutor if tutor else None,
        branch_id=lesson.branch_id,
        user=user,
    )


def _create_charge(
    *,
    client: Client,
    kind: str,
    source_key: str,
    description: str,
    day: date,
    price: Money,
    quantity: Decimal,
    unit: str,
    tax_percent: Decimal,
    tax_rate_id: Any = None,
    branch_id: Any = None,
    user: Any = None,
    **links: Any,
) -> Charge:
    unit_price = price / quantity if quantity else price
    amounts = amounts_for(price, tax_percent, inclusive=_inclusive(), exempt=client.tax_exempt)
    charge = Charge.objects.create(
        client=client,
        branch_id=branch_id or client.branch_id,
        kind=kind,
        source_key=source_key,
        description=description[:300],
        date=day,
        currency=price.currency,
        quantity=quantity,
        unit=unit,
        unit_price=Money(unit_price.amount.quantize(Decimal("0.0001")), price.currency),
        tax_rate_id=tax_rate_id,
        tax_percent=Decimal(0) if client.tax_exempt else tax_percent,
        net=amounts.net,
        tax=amounts.tax,
        gross=amounts.gross,
        created_by=user,
        **links,
    )
    publish(
        events.ChargeCreated(
            subject_id=charge.pk,
            client_id=str(client.pk),
            kind=kind,
            gross=amounts.gross.to_dict(),
            lesson_id=str(charge.lesson_id) if charge.lesson_id else None,
        ),
        branch_id=charge.branch_id,
    )
    return charge


def void_charge(charge: Charge, *, reason: str = "") -> Charge:
    if charge.status != Charge.Status.UNINVOICED or charge.invoice_id:
        raise BusinessRuleViolation(_("Only charges that aren't on an invoice can be voided."))
    with audit.track(charge, action="void"):
        charge.status = Charge.Status.VOID
        charge.save(update_fields=["status", "updated_at"])
    publish(events.ChargeVoided(subject_id=charge.pk, client_id=str(charge.client_id)))
    return charge


def _is_prepaid(lesson: Lesson) -> bool:
    return bool(lesson.job_id and lesson.job and lesson.job.billing_method == "prepaid_credit")


def _is_advance(lesson: Lesson) -> bool:
    return bool(lesson.job_id and lesson.job and lesson.job.billing_method == "invoice_in_advance")


@transaction.atomic
def sync_lesson_charges(lesson_id: Any) -> list[Charge]:
    """Called for ``lesson.completed``, ``lesson.cancelled``, ``attendance.recorded``,
    ``lesson.updated`` and ``lesson.locked_edited``."""
    lesson = Lesson.objects.select_related("job", "service").filter(pk=lesson_id).first()
    if lesson is None:
        return []
    created = []
    for attendee in lesson.attendees.select_related("client", "student"):
        charge = sync_attendee_charge(attendee)
        if charge is not None:
            created.append(charge)
    if _is_prepaid(lesson):
        clients = {a.client for a in lesson.attendees.select_related("client")}
        for client in clients:
            after_prepaid_charge(client, lesson)
    return created


def after_prepaid_charge(client: Client, lesson: Lesson) -> None:
    """Prepaid draw-down: a receipt invoice per lesson, paid from credit (setting), and a
    top-up request when credit runs low."""
    if get_setting("billing.prepaid_invoice_each_lesson"):
        pending = Charge.objects.filter(
            client=client,
            lesson=lesson,
            status=Charge.Status.UNINVOICED,
            invoice__isnull=True,
        )
        if pending.exists():
            for invoice in build_drafts(pending, skip_small=False):
                issue_invoice(invoice, send=False)
    check_topup(client)


@transaction.atomic
def charge_in_advance(lessons: Iterable[Lesson]) -> list[Charge]:
    """Advance charges for scheduled lessons (FR-10-1 mode 2)."""
    out = []
    for lesson in lessons:
        for attendee in lesson.attendees.select_related("client", "student", "lesson"):
            charge = sync_attendee_charge(attendee, advance=True)
            if charge is not None:
                out.append(charge)
    return out


# --- ad hoc charges -----------------------------------------------------------------------------


@transaction.atomic
def create_ad_hoc_charge(
    *,
    client: Client,
    description: str,
    unit_price: Money,
    quantity: Decimal = Decimal(1),
    day: date | None = None,
    student: Student | None = None,
    job: Any = None,
    product: Product | None = None,
    tax_rate: TaxRate | None = None,
    category: str = "",
    tutor: Any = None,
    tutor_share: Money | None = None,
    user: Any = None,
) -> Charge:
    """One-off charges and (negative) discounts or goodwill credits (FR-10-2)."""
    if quantity <= 0:
        raise _invalid("quantity", _("Quantity must be more than zero."))
    if student is not None and student.client_id != client.pk:
        raise _invalid("student", _("That student isn't in this client's account."))
    rate = tax_rate or (product.tax_rate if product else None)
    price = (unit_price * quantity).round_to_minor()
    charge = _create_charge(
        client=client,
        kind=Charge.Kind.AD_HOC,
        source_key=f"ad_hoc:{secrets.token_hex(8)}",
        description=description,
        day=day or org_today(),
        price=price,
        quantity=quantity,
        unit="item",
        tax_percent=rate.percent if rate else Decimal(0),
        tax_rate_id=rate.pk if rate else None,
        student=student,
        job=job,
        product=product,
        category=category,
        tutor=tutor,
        tutor_share=tutor_share,
        user=user,
    )
    audit.record_create(charge)
    return charge


# --- invoices: drafts (T03/T04) -----------------------------------------------------------------


def _group_key(charge: Charge) -> tuple[Any, ...]:
    client = charge.client
    if client.invoice_grouping == Client.InvoiceGrouping.STUDENT:
        return (client.pk, charge.currency, charge.student_id)
    if client.invoice_grouping == Client.InvoiceGrouping.JOB:
        return (client.pk, charge.currency, charge.job_id)
    return (client.pk, charge.currency)


def _tutor_name(charge: Charge) -> str:
    if not get_setting("billing.show_tutor_names") or charge.tutor is None:
        return ""
    return charge.tutor.full_name


def _recompute(invoice: Invoice) -> None:
    lines = list(invoice.lines.all())
    currency = invoice.currency
    invoice.subtotal = sum_money((line.net for line in lines), currency)
    invoice.tax_total = sum_money((line.tax for line in lines), currency)
    invoice.total = sum_money((line.gross for line in lines), currency)
    invoice.balance_due = invoice.total - invoice.amount_paid - invoice.amount_credited


def _add_lines(invoice: Invoice, charges: list[Charge], start: int = 0) -> None:
    charges.sort(key=lambda c: (c.student.full_name if c.student else "", c.date, c.created_at))
    for position, charge in enumerate(charges, start=start):
        InvoiceLine.objects.create(
            invoice=invoice,
            charge=charge,
            position=position,
            date=charge.date,
            description=charge.description,
            student_name=charge.student.full_name if charge.student else "",
            tutor_name=_tutor_name(charge),
            currency=charge.currency,
            quantity=charge.quantity,
            unit=charge.unit,
            unit_price=charge.unit_price,
            tax_percent=charge.tax_percent,
            net=charge.net,
            tax=charge.tax,
            gross=charge.gross,
        )
        charge.invoice = invoice
        charge.save(update_fields=["invoice", "updated_at"])


def build_drafts(
    charges: QuerySet[Charge],
    *,
    run: InvoiceRun | None = None,
    period: tuple[date, date] | None = None,
    skip_small: bool = True,
) -> list[Invoice]:
    """Group uninvoiced charges into draft invoices (per client and currency, or per
    student/job by the client's setting; siblings share one invoice). Charges are row-locked
    and skipped if another run holds them, so concurrent runs never double-invoice."""
    rows = list(
        charges.filter(status=Charge.Status.UNINVOICED, invoice__isnull=True)
        .select_for_update(skip_locked=True, of=("self",))
        .select_related("client", "student", "tutor")
        .order_by("client_id", "date", "created_at")
    )
    groups: dict[tuple[Any, ...], list[Charge]] = defaultdict(list)
    for charge in rows:
        groups[_group_key(charge)].append(charge)
    minimum = Decimal(int(get_setting("billing.minimum_invoice_amount")))
    skip_zero = bool(get_setting("billing.skip_zero_invoices"))
    drafts = []
    for key, items in groups.items():
        total = sum((c.gross.amount for c in items), Decimal(0))
        if total < 0 or (skip_zero and total == 0) or (skip_small and total < minimum):
            continue  # carried forward to the next invoice
        client = items[0].client
        dates = [c.date for c in items]
        invoice = Invoice.objects.create(
            client=client,
            branch_id=client.branch_id,
            currency=key[1],
            period_start=period[0] if period else min(dates),
            period_end=period[1] if period else max(dates),
            po_number=client.po_number,
            invoice_run=run,
        )
        _add_lines(invoice, items)
        _recompute(invoice)
        invoice.save()
        publish(
            events.InvoiceDrafted(
                subject_id=invoice.pk,
                client_id=str(client.pk),
                run_id=str(run.pk) if run else None,
            ),
            branch_id=invoice.branch_id,
        )
        drafts.append(invoice)
    return drafts


@transaction.atomic
def create_draft(client: Client, *, until: date | None = None, user: Any = None) -> Invoice:
    """An invoice now for the client's uninvoiced charges (FR-10-4 "create")."""
    charges = Charge.objects.filter(client=client)
    if until:
        charges = charges.filter(date__lte=until)
    drafts = build_drafts(charges, skip_small=False)
    if not drafts:
        raise BusinessRuleViolation(_("There's nothing to invoice for this client."))
    return drafts[0]


def _draft(invoice: Invoice) -> Invoice:
    locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if locked.status != Invoice.Status.DRAFT:
        raise BusinessRuleViolation(_("Issued invoices can't be changed; use a credit note."))
    return locked


@transaction.atomic
def update_draft(invoice: Invoice, **changes: Any) -> Invoice:
    invoice = _draft(invoice)
    with audit.track(invoice, action="update"):
        for key in ("po_number", "notes", "due_date"):
            if key in changes:
                setattr(invoice, key, changes[key])
        invoice.save()
    return invoice


@transaction.atomic
def add_line(invoice: Invoice, *, user: Any = None, **charge: Any) -> Invoice:
    """Add a one-off line to a draft (creates an ad hoc charge on it)."""
    invoice = _draft(invoice)
    new = create_ad_hoc_charge(client=invoice.client, user=user, **charge)
    if new.currency != invoice.currency:
        raise _invalid("unit_price", _("Use the invoice currency."))
    _add_lines(invoice, [new], start=invoice.lines.count())
    _recompute(invoice)
    invoice.save()
    return invoice


@transaction.atomic
def remove_line(invoice: Invoice, line: InvoiceLine) -> Invoice:
    """Remove a line from a draft; its charge goes back to uninvoiced."""
    invoice = _draft(invoice)
    if line.invoice_id != invoice.pk:
        raise _invalid("line", _("That line isn't on this invoice."))
    if line.charge_id:
        Charge.objects.filter(pk=line.charge_id).update(invoice=None)
    line.delete()
    _recompute(invoice)
    invoice.save()
    return invoice


@transaction.atomic
def delete_draft(invoice: Invoice) -> None:
    invoice = _draft(invoice)
    Charge.objects.filter(invoice=invoice).update(invoice=None)
    audit.record(invoice, "delete")
    invoice.delete()


# --- invoices: issue and lifecycle (T03/T05) ----------------------------------------------------


def _snapshot(invoice: Invoice) -> dict[str, Any]:
    from tutortrack.tenancy.models import Organisation

    client = invoice.client
    contact = client.billing_contact or client.primary_contact
    address = client.billing_address
    org = Organisation.objects.get(pk=invoice.organisation_id)
    return {
        "client_name": client.display_name,
        "contact_name": contact.full_name if contact else "",
        "email": contact.email if contact else "",
        "address": [
            line
            for line in (
                getattr(address, "line1", ""),
                getattr(address, "line2", ""),
                getattr(address, "city", ""),
                getattr(address, "postcode", ""),
            )
            if line
        ],
        "organisation": org.name,
        "payment_instructions": get_setting("billing.payment_instructions"),
        "footer": get_setting("billing.invoice_footer"),
    }


def _lock_lessons(invoice: Invoice, state: str) -> None:
    from tutortrack.scheduling import services as scheduling

    lesson_ids = Charge.objects.filter(invoice=invoice, lesson__isnull=False).values_list(
        "lesson_id", flat=True
    )
    # Lessons invoiced in advance stay editable until delivered: changes reconcile.
    lessons = Lesson.objects.filter(pk__in=list(lesson_ids)).exclude(status=Lesson.Status.PLANNED)
    if state == Lesson.Lock.UNLOCKED:
        still = Charge.objects.filter(
            lesson__in=lessons, status=Charge.Status.INVOICED, invoice__status__in=Invoice.OPEN
        ).values_list("lesson_id", flat=True)
        lessons = lessons.exclude(pk__in=list(still))
    scheduling.set_lock(list(lessons), state)


@transaction.atomic
def issue_invoice(invoice: Invoice, *, user: Any = None, send: bool | None = None) -> Invoice:
    """Number, post to the ledger, lock the lessons and (setting) apply credit."""
    invoice = _draft(invoice)
    if not invoice.lines.exists():
        raise BusinessRuleViolation(_("Add at least one line before issuing."))
    _recompute(invoice)
    if invoice.total.is_negative():
        raise BusinessRuleViolation(_("An invoice can't total less than zero; credit instead."))
    today = org_today()
    with audit.track(invoice, action="issue"):
        invoice.number = next_number(
            "invoice", prefix=str(get_setting("billing.invoice_prefix")), padding=6
        )
        invoice.status = Invoice.Status.ISSUED
        invoice.issue_date = today
        invoice.issued_at = now()
        invoice.due_date = invoice.due_date or today + timedelta(
            days=invoice.client.payment_terms_days
        )
        invoice.billing_snapshot = _snapshot(invoice)
        invoice.pay_token = secrets.token_urlsafe(32)
        invoice.save()
    Charge.objects.filter(invoice=invoice).update(status=Charge.Status.INVOICED)
    ledger.post(
        invoice.client,
        ClientLedgerEntry.Type.INVOICE,
        invoice.total,
        ref=invoice,
        description=_("Invoice %(number)s") % {"number": invoice.number},
        user=user,
    )
    _lock_lessons(invoice, Lesson.Lock.INVOICED)
    publish(
        events.InvoiceIssued(
            subject_id=invoice.pk,
            client_id=str(invoice.client_id),
            number=invoice.number,
            total=invoice.total.to_dict(),
            balance_due=invoice.balance_due.to_dict(),
            due_date=invoice.due_date.isoformat(),
        ),
        branch_id=invoice.branch_id,
    )
    if get_setting("billing.auto_apply_credit"):
        apply_credit(invoice, user=user, quiet=True)
        invoice.refresh_from_db()
    if invoice.total.is_zero():
        _settle(invoice)
    if send if send is not None else get_setting("billing.auto_send"):
        invoice_id, org_id = invoice.pk, invoice.organisation_id
        transaction.on_commit(lambda: _send_later(org_id, invoice_id))
    return invoice


def _send_later(organisation_id: Any, invoice_id: Any) -> None:
    from .tasks import send_invoice_email

    send_invoice_email.delay(organisation_id=str(organisation_id), invoice_id=str(invoice_id))


def _settle(invoice: Invoice) -> None:
    """Recompute what is owed and the status after a payment, credit or credit note."""
    previous = invoice.status
    invoice.balance_due = invoice.total - invoice.amount_paid - invoice.amount_credited
    if invoice.balance_due.amount <= 0:
        invoice.status = Invoice.Status.PAID
        invoice.paid_at = invoice.paid_at or now()
    elif (invoice.amount_paid + invoice.amount_credited).is_positive():
        invoice.status = Invoice.Status.PARTIALLY_PAID
    else:
        invoice.status = Invoice.Status.ISSUED
    invoice.save(
        update_fields=["balance_due_amount", "status", "paid_at", "amount_paid_amount",
                       "amount_credited_amount", "updated_at"]
    )  # fmt: skip
    if invoice.status == previous:
        return
    if invoice.status == Invoice.Status.PAID:
        publish(
            events.InvoicePaid(subject_id=invoice.pk, client_id=str(invoice.client_id)),
            branch_id=invoice.branch_id,
        )
    elif invoice.status == Invoice.Status.PARTIALLY_PAID:
        publish(
            events.InvoicePartiallyPaid(
                subject_id=invoice.pk,
                client_id=str(invoice.client_id),
                balance_due=invoice.balance_due.to_dict(),
            ),
            branch_id=invoice.branch_id,
        )


def _open(invoice: Invoice) -> Invoice:
    locked = Invoice.objects.select_for_update().select_related("client").get(pk=invoice.pk)
    if not locked.is_open:
        raise BusinessRuleViolation(_("This invoice isn't open."))
    return locked


@transaction.atomic
def apply_credit(
    invoice: Invoice, *, amount: Money | None = None, user: Any = None, quiet: bool = False
) -> Money:
    """Use the client's available credit on an invoice (oldest credit first; it is a pool)."""
    invoice = Invoice.objects.select_for_update().select_related("client").get(pk=invoice.pk)
    zero = Money.zero(invoice.currency)
    if not invoice.is_open:
        if quiet:
            return zero
        raise BusinessRuleViolation(_("This invoice isn't open."))
    available = ledger.balances(invoice.client, invoice.currency).available_credit
    use = min(available, invoice.balance_due)
    if amount is not None:
        if amount.is_negative() or amount > use:
            raise _invalid("amount", _("That's more than the available credit or balance."))
        use = amount
    if use.is_zero() or use.is_negative():
        if quiet:
            return zero
        raise BusinessRuleViolation(_("This client has no credit to use."))
    CreditAllocation.objects.create(
        invoice=invoice, currency=invoice.currency, amount=use, created_by=user
    )
    invoice.amount_credited = invoice.amount_credited + use
    audit.record(invoice, "apply_credit", {"amount": [None, str(use.amount)]})
    _settle(invoice)
    return use


@transaction.atomic
def allocate_payment(invoice: Invoice, amount: Money, *, user: Any = None) -> Invoice:
    """E11: record that ``amount`` of a payment (already posted to the ledger) pays this
    invoice."""
    invoice = _open(invoice)
    if amount.currency != invoice.currency or not amount.is_positive():
        raise _invalid("amount", _("Allocate a positive amount in the invoice currency."))
    if amount > invoice.balance_due:
        raise _invalid("amount", _("That's more than is owed on this invoice."))
    invoice.amount_paid = invoice.amount_paid + amount
    _settle(invoice)
    return invoice


@transaction.atomic
def unallocate_payment(invoice: Invoice, amount: Money) -> Invoice:
    """E11 refunds/disputes: reopen what a payment had paid."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if amount > invoice.amount_paid:
        raise _invalid("amount", _("That's more than was paid on this invoice."))
    invoice.amount_paid = invoice.amount_paid - amount
    invoice.paid_at = None
    _settle(invoice)
    return invoice


@transaction.atomic
def void_invoice(invoice: Invoice, *, reason: str, user: Any = None) -> Invoice:
    """Only invoices without payments or credit notes. Posts a reversing entry and returns
    the charges to uninvoiced so they can be corrected and re-invoiced."""
    invoice = _open(invoice)
    if invoice.amount_paid.is_positive():
        raise BusinessRuleViolation(
            _("Refund the payments before voiding, or issue a credit note.")
        )
    if invoice.credit_notes.exists():
        raise BusinessRuleViolation(_("This invoice has credit notes; credit the rest instead."))
    if not reason.strip():
        raise _invalid("reason", _("Give a reason."))
    with audit.track(invoice, action="void"):
        invoice.status = Invoice.Status.VOID
        invoice.voided_at = now()
        invoice.void_reason = reason[:300]
        invoice.balance_due = Money.zero(invoice.currency)
        invoice.save()
    ledger.post(
        invoice.client,
        ClientLedgerEntry.Type.INVOICE_VOID,
        -invoice.total,
        ref=invoice,
        description=_("Invoice %(number)s voided") % {"number": invoice.number},
        user=user,
    )
    charges = list(Charge.objects.filter(invoice=invoice))
    _lock_lessons(invoice, Lesson.Lock.UNLOCKED)
    for charge in charges:
        charge.status = Charge.Status.UNINVOICED
        charge.invoice = None
        charge.save(update_fields=["status", "invoice", "updated_at"])
    InvoiceLine.objects.filter(invoice=invoice).update(charge=None)
    publish(
        events.InvoiceVoided(
            subject_id=invoice.pk, client_id=str(invoice.client_id), reason=reason
        ),
        branch_id=invoice.branch_id,
    )
    return invoice


@transaction.atomic
def write_off(invoice: Invoice, *, reason: str, user: Any = None) -> Invoice:
    invoice = _open(invoice)
    if not reason.strip():
        raise _invalid("reason", _("Give a reason."))
    amount = invoice.balance_due
    with audit.track(invoice, action="write_off"):
        invoice.status = Invoice.Status.WRITTEN_OFF
        invoice.written_off_at = now()
        invoice.write_off_reason = reason[:300]
        invoice.balance_due = Money.zero(invoice.currency)
        invoice.save()
    ledger.post(
        invoice.client,
        ClientLedgerEntry.Type.WRITE_OFF,
        -amount,
        ref=invoice,
        description=_("Invoice %(number)s written off") % {"number": invoice.number},
        user=user,
    )
    publish(
        events.InvoiceWrittenOff(
            subject_id=invoice.pk,
            client_id=str(invoice.client_id),
            reason=reason,
            amount=amount.to_dict(),
        ),
        branch_id=invoice.branch_id,
    )
    return invoice


@transaction.atomic
def create_credit_note(
    invoice: Invoice,
    *,
    reason: str,
    application: str = CreditNote.Application.INVOICE,
    lines: list[dict[str, Any]] | None = None,
    user: Any = None,
) -> CreditNote:
    """FR-10-5. ``lines`` = ``[{"line": InvoiceLine, "amount": Money}]`` (gross); omitted,
    everything not yet credited is credited."""
    invoice = Invoice.objects.select_for_update().select_related("client").get(pk=invoice.pk)
    if invoice.status in {Invoice.Status.DRAFT, Invoice.Status.VOID}:
        raise BusinessRuleViolation(_("Only issued invoices can be credited."))
    if application not in CreditNote.Application.values:
        raise _invalid("application", _("Choose how to use the credit."))
    if not reason.strip():
        raise _invalid("reason", _("Give a reason."))
    all_lines = {str(line.pk): line for line in invoice.lines.select_for_update()}
    wanted = lines or [
        {"line": line, "amount": line.gross - line.credited} for line in all_lines.values()
    ]
    parts = []
    for row in wanted:
        line = all_lines.get(str(row["line"].pk))
        if line is None:
            raise _invalid("lines", _("That line isn't on this invoice."))
        amount: Money = row["amount"].round_to_minor()
        remaining = line.gross - line.credited
        if amount.is_zero():
            continue
        if amount.is_negative() or amount > remaining:
            raise _invalid("lines", _("You can credit at most what's left on each line."))
        tax = (
            Money.zero(invoice.currency)
            if line.gross.is_zero()
            else (line.tax * amount.ratio(line.gross)).round_to_minor()
        )
        parts.append((line, amount - tax, tax, amount))
    if not parts:
        raise _invalid("lines", _("Choose what to credit."))
    currency = invoice.currency
    net = sum_money((p[1] for p in parts), currency)
    tax = sum_money((p[2] for p in parts), currency)
    total = sum_money((p[3] for p in parts), currency)
    note = CreditNote.objects.create(
        number=next_number("credit_note", prefix=str(get_setting("billing.credit_note_prefix"))),
        invoice=invoice,
        client=invoice.client,
        branch_id=invoice.branch_id,
        currency=currency,
        reason=reason[:300],
        application=application,
        net=net,
        tax=tax,
        total=total,
        issued_at=now(),
        created_by=user,
    )
    for line, line_net, line_tax, gross in parts:
        CreditNoteLine.objects.create(
            credit_note=note,
            invoice_line=line,
            description=line.description,
            currency=currency,
            net=line_net,
            tax=line_tax,
            gross=gross,
        )
        line.credited = line.credited + gross
        line.save(update_fields=["credited_amount", "updated_at"])
    audit.record_create(note)
    ledger.post(
        invoice.client,
        ClientLedgerEntry.Type.CREDIT_NOTE,
        -total,
        ref=note,
        description=_("Credit note %(number)s") % {"number": note.number},
        user=user,
    )
    if application == CreditNote.Application.INVOICE and invoice.is_open:
        invoice.amount_credited = invoice.amount_credited + min(total, invoice.balance_due)
        _settle(invoice)
    publish(
        events.CreditNoteIssued(
            subject_id=note.pk,
            client_id=str(invoice.client_id),
            invoice_id=str(invoice.pk),
            total=total.to_dict(),
            application=application,
        ),
        branch_id=note.branch_id,
    )
    return note


@transaction.atomic
def mark_sent(invoice: Invoice, *, to: list[str]) -> Invoice:
    Invoice.objects.filter(pk=invoice.pk).update(sent_at=now())
    publish(
        events.InvoiceSent(subject_id=invoice.pk, client_id=str(invoice.client_id), to=to),
        branch_id=invoice.branch_id,
    )
    invoice.refresh_from_db()
    return invoice


# --- reminders (T09; called by the dunning workflow) --------------------------------------------


@transaction.atomic
def send_reminder(invoice_id: Any, offset: int, *, dedupe_key: str | None = None) -> bool:
    invoice = Invoice.objects.filter(pk=invoice_id).first()
    if invoice is None or not invoice.is_open:
        return False
    publish(
        events.InvoiceReminder(
            subject_id=invoice.pk,
            client_id=str(invoice.client_id),
            offset_days=offset,
            balance_due=invoice.balance_due.to_dict(),
        ),
        branch_id=invoice.branch_id,
        dedupe_key=dedupe_key,
    )
    if offset > 0:
        publish(
            events.InvoiceOverdue(subject_id=invoice.pk, client_id=str(invoice.client_id)),
            branch_id=invoice.branch_id,
            dedupe_key=f"overdue:{invoice.pk}",
        )
    return True


# --- payment requests (T06) ---------------------------------------------------------------------


@transaction.atomic
def create_payment_request(
    *,
    client: Client,
    amount: Money,
    description: str = "",
    due_date: date | None = None,
    source: str = PaymentRequest.Source.MANUAL,
    user: Any = None,
) -> PaymentRequest:
    if not amount.is_positive():
        raise _invalid("amount", _("Ask for more than zero."))
    request = PaymentRequest.objects.create(
        number=next_number(
            "payment_request", prefix=str(get_setting("billing.payment_request_prefix"))
        ),
        client=client,
        branch_id=client.branch_id,
        currency=amount.currency,
        amount=amount.round_to_minor(),
        description=description or _("Credit top-up"),
        due_date=due_date,
        source=source,
        pay_token=secrets.token_urlsafe(32),
    )
    audit.record_create(request)
    publish(
        events.PaymentRequestCreated(
            subject_id=request.pk,
            client_id=str(client.pk),
            amount=request.amount.to_dict(),
            source=source,
        ),
        branch_id=request.branch_id,
    )
    return request


@transaction.atomic
def bulk_payment_requests(
    clients: Iterable[Client],
    *,
    below: Money | None = None,
    amount: Money | None = None,
    top_up_to: Money | None = None,
    description: str = "",
    user: Any = None,
) -> list[PaymentRequest]:
    """FR-10-6 bulk: clients whose projected balance is below ``below`` get a request for
    ``amount``, or enough to bring them back to ``top_up_to``."""
    out = []
    for client in clients:
        currency = (amount or top_up_to or below or Money.zero(client.currency)).currency
        if currency != client.currency:
            continue
        projected = ledger.balances(client, currency).projected
        if below is not None and projected >= below:
            continue
        ask = amount if amount is not None else (top_up_to - projected if top_up_to else None)
        if ask is None or not ask.is_positive():
            continue
        out.append(
            create_payment_request(
                client=client,
                amount=ask,
                description=description,
                source=PaymentRequest.Source.BULK,
                user=user,
            )
        )
    return out


def check_topup(client: Client) -> PaymentRequest | None:
    """Automatic top-up request when a prepaid client's credit runs low (setting)."""
    threshold = int(get_setting("billing.topup_threshold"))
    if not threshold:
        return None
    balances = ledger.balances(client)
    available = balances.available_credit - balances.uninvoiced
    if available.amount >= threshold:
        return None
    if PaymentRequest.objects.filter(
        client=client, status=PaymentRequest.Status.OPEN, source=PaymentRequest.Source.THRESHOLD
    ).exists():
        return None
    publish(events.ClientBalanceLow(subject_id=client.pk, available=available.to_dict()))
    return create_payment_request(
        client=client,
        amount=Money(Decimal(int(get_setting("billing.topup_amount"))), client.currency),
        source=PaymentRequest.Source.THRESHOLD,
    )


@transaction.atomic
def cancel_payment_request(request: PaymentRequest, *, user: Any = None) -> PaymentRequest:
    request = PaymentRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != PaymentRequest.Status.OPEN or request.amount_paid.is_positive():
        raise BusinessRuleViolation(_("Only unpaid requests can be cancelled."))
    with audit.track(request, action="cancel"):
        request.status = PaymentRequest.Status.CANCELLED
        request.cancelled_at = now()
        request.save(update_fields=["status", "cancelled_at", "updated_at"])
    publish(
        events.PaymentRequestCancelled(subject_id=request.pk, client_id=str(request.client_id)),
        branch_id=request.branch_id,
    )
    return request


@transaction.atomic
def pay_payment_request(
    request: PaymentRequest, amount: Money, *, user: Any = None, occurred_at: datetime | None = None
) -> PaymentRequest:
    """E11: a payment against a request becomes client credit (``payment_request_payment``),
    which is then used on open invoices (setting)."""
    request = PaymentRequest.objects.select_for_update().select_related("client").get(pk=request.pk)
    if request.status != PaymentRequest.Status.OPEN:
        raise BusinessRuleViolation(_("This request isn't open."))
    if amount.currency != request.currency or not amount.is_positive():
        raise _invalid("amount", _("Pay a positive amount in the request currency."))
    ledger.post(
        request.client,
        ClientLedgerEntry.Type.PAYMENT_REQUEST_PAYMENT,
        -amount,
        ref=request,
        description=_("Payment for %(number)s") % {"number": request.number},
        occurred_at=occurred_at,
        user=user,
    )
    request.amount_paid = request.amount_paid + amount
    if request.amount_paid >= request.amount:
        request.status = PaymentRequest.Status.PAID
        request.paid_at = now()
    request.save(update_fields=["amount_paid_amount", "status", "paid_at", "updated_at"])
    publish(
        events.PaymentRequestPaid(
            subject_id=request.pk, client_id=str(request.client_id), amount=amount.to_dict()
        ),
        branch_id=request.branch_id,
    )
    if get_setting("billing.auto_apply_credit"):
        apply_credit_to_open_invoices(request.client, request.currency, user=user)
    return request


def apply_credit_to_open_invoices(client: Client, currency: str, *, user: Any = None) -> None:
    for invoice in Invoice.objects.filter(
        client=client, currency=currency, status__in=Invoice.OPEN
    ).order_by("due_date", "issue_date"):
        if apply_credit(invoice, user=user, quiet=True).is_zero():
            break


@transaction.atomic
def mark_request_sent(request: PaymentRequest) -> PaymentRequest:
    PaymentRequest.objects.filter(pk=request.pk).update(sent_at=now())
    publish(
        events.PaymentRequestSent(subject_id=request.pk, client_id=str(request.client_id)),
        branch_id=request.branch_id,
    )
    request.refresh_from_db()
    return request


# --- ledger adjustments -------------------------------------------------------------------------


@transaction.atomic
def adjust_ledger(client: Client, amount: Money, *, reason: str, user: Any = None) -> Any:
    """Manual adjustment (``billing.ledger.adjust``): positive adds to what is owed."""
    if amount.is_zero() or not reason.strip():
        raise _invalid("amount", _("Give an amount and a reason."))
    entry = ledger.post(
        client, ClientLedgerEntry.Type.ADJUSTMENT, amount.round_to_minor(),
        description=reason, user=user,
    )  # fmt: skip
    audit.record(client, "ledger_adjustment", {"amount": [None, str(amount.amount)]})
    return entry


# --- invoice runs (T04, T07) --------------------------------------------------------------------


def _run_charges(run: InvoiceRun) -> QuerySet[Charge]:
    from tutortrack.delivery.selectors import lessons_with_open_reports

    charges = Charge.objects.filter(
        branch_id=run.branch_id,
        status=Charge.Status.UNINVOICED,
        invoice__isnull=True,
        date__lte=run.period_end,
    )
    if run.filters.get("client"):
        charges = charges.filter(client_id=run.filters["client"])
    if run.mode == InvoiceRun.Mode.ADVANCE:
        advance_clients = charges.filter(kind=Charge.Kind.ADVANCE).values("client_id")
        charges = Charge.objects.filter(
            client_id__in=advance_clients,
            status=Charge.Status.UNINVOICED,
            invoice__isnull=True,
            date__lte=run.period_end,
        )
    if get_setting("delivery.hold_invoice_without_report"):
        lesson_ids = list(charges.filter(lesson__isnull=False).values_list("lesson_id", flat=True))
        held = lessons_with_open_reports(lesson_ids)
        charges = charges.exclude(lesson_id__in=held)
    return charges


def _advance_lessons(run: InvoiceRun) -> QuerySet[Lesson]:
    tz = ZoneInfo(str(run.branch.timezone))
    start = datetime.combine(run.period_start, datetime.min.time(), tzinfo=tz)
    end = datetime.combine(run.period_end + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    lessons = Lesson.objects.filter(
        branch_id=run.branch_id,
        status=Lesson.Status.PLANNED,
        start__gte=start,
        start__lt=end,
        job__billing_method="invoice_in_advance",
    )
    if run.filters.get("client"):
        lessons = lessons.filter(attendees__client_id=run.filters["client"]).distinct()
    return lessons


@transaction.atomic
def create_run(
    *,
    period_start: date,
    period_end: date,
    mode: str = InvoiceRun.Mode.ARREARS,
    branch: Any = None,
    client: Client | None = None,
    user: Any = None,
    start_workflow: bool = True,
) -> tuple[InvoiceRun, bool]:
    """Idempotent per branch, period and mode: running it again returns the same run."""
    from tutortrack.tenancy.selectors import default_branch_id

    if period_end < period_start:
        raise _invalid("period_end", _("The period ends before it starts."))
    branch_id = branch.pk if branch is not None else default_branch_id(require_organisation_id())
    run, created = InvoiceRun.objects.get_or_create(
        branch_id=branch_id,
        period_start=period_start,
        period_end=period_end,
        mode=mode,
        defaults={"filters": {"client": str(client.pk)} if client else {}, "requested_by": user},
    )
    if created and start_workflow:
        from tutortrack.core.workflows import start

        from .processes import InvoiceRunInput, InvoiceRunWorkflow, run_workflow_id

        run.workflow_id = run_workflow_id(run.organisation_id, run.pk)
        run.save(update_fields=["workflow_id", "updated_at"])
        start(
            InvoiceRunWorkflow,
            InvoiceRunInput(organisation_id=str(run.organisation_id), run_id=str(run.pk)),
            id=run.workflow_id,
            subject=("invoice_run", str(run.pk)),
            branch_id=run.branch_id,
        )
    return run, created


@transaction.atomic
def collect_run(run_id: Any) -> dict[str, Any]:
    """Step 1: (advance mode) charge scheduled lessons, then draft invoices."""
    run = InvoiceRun.objects.select_for_update().select_related("branch").get(pk=run_id)
    if run.status != InvoiceRun.Status.COLLECTING:
        return dict(run.stats)
    if run.mode == InvoiceRun.Mode.ADVANCE:
        charge_in_advance(_advance_lessons(run))
    drafts = build_drafts(_run_charges(run), run=run, period=(run.period_start, run.period_end))
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for invoice in drafts:
        totals[invoice.currency] += invoice.total.amount
    review_days = int(get_setting("billing.review_days", branch=run.branch))
    run.status = InvoiceRun.Status.REVIEW
    run.review_until = now() + timedelta(days=review_days)
    run.stats = {
        "drafts": len(drafts),
        "totals": {k: str(v) for k, v in totals.items()},
        "auto_issue": bool(get_setting("billing.auto_issue", branch=run.branch)),
        "review_days": review_days,
    }
    run.save(update_fields=["status", "review_until", "stats", "updated_at"])
    return dict(run.stats)


@transaction.atomic
def approve_run(run: InvoiceRun, *, user: Any = None) -> InvoiceRun:
    run = InvoiceRun.objects.select_for_update().get(pk=run.pk)
    if run.status != InvoiceRun.Status.REVIEW:
        raise BusinessRuleViolation(_("This run isn't waiting for review."))
    with audit.track(run, action="approve"):
        run.approved_at = now()
        run.save(update_fields=["approved_at", "updated_at"])
    if run.workflow_id:
        from tutortrack.core.workflows import signal

        signal(run.workflow_id, "approve")
    return run


def issue_run(run_id: Any) -> dict[str, Any]:
    """Final step: issue the run's remaining drafts, each in its own transaction."""
    with transaction.atomic():
        run = InvoiceRun.objects.select_for_update().get(pk=run_id)
        if run.status == InvoiceRun.Status.COMPLETED:
            return dict(run.stats)
        run.status = InvoiceRun.Status.ISSUING
        run.save(update_fields=["status", "updated_at"])
    issued = failed = 0
    for invoice in Invoice.objects.filter(invoice_run_id=run_id, status=Invoice.Status.DRAFT):
        try:
            with transaction.atomic():
                issue_invoice(invoice)
            issued += 1
        except BusinessRuleViolation:
            failed += 1
    with transaction.atomic():
        run = InvoiceRun.objects.select_for_update().get(pk=run_id)
        run.status = InvoiceRun.Status.COMPLETED
        run.stats = {**run.stats, "issued": issued, "failed": failed}
        run.save(update_fields=["status", "stats", "updated_at"])
    return dict(run.stats)


def scheduled_period(cadence: str, today: date) -> tuple[date, date]:
    """The period a scheduled run covers: last week (Monday to Sunday) or last calendar month."""
    if cadence == "weekly":
        end = today - timedelta(days=today.weekday() + 1)
        return end - timedelta(days=6), end
    first = today.replace(day=1)
    end = first - timedelta(days=1)
    return end.replace(day=1), end
