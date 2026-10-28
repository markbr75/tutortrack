"""Late fees and collections (E10-T14, FR-10-10).

The **Payment chasing** built-in workflow (E33 T04) decides when: its "Apply a late fee"
steps call ``apply_next_late_fee`` and "Open a collections case" calls ``open_collections``:

* **Late fees:** the branch's (or organisation's) ``LateFeeRule``: a fixed amount or a
  percentage of what is owed, once or monthly, capped; a ``late_fee`` charge added to the
  next invoice or invoiced at once. Idempotent per invoice and application
  (``late_fee:{invoice}:{n}``). Waiving one voids it (not invoiced yet) or credits it.
* **Collections:** after ``billing.collections_after_days`` the client is put "in
  collections": staff get a task and ``booking_block`` reports a soft (warn when
  scheduling) or hard (no portal booking) block until nothing is overdue.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import events
from .models import Charge, CollectionsCase, Invoice, LateFeeRule

HUNDRED = Decimal(100)
MONTH = 30
MAX_MONTHLY = 24


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


@transaction.atomic
def save_rule(rule: LateFeeRule | None, **values: Any) -> LateFeeRule:
    """Create or change a late fee rule. A new active rule replaces the branch's (or the
    organisation's) previous one."""

    def apply(target: LateFeeRule) -> None:
        for key, value in values.items():
            setattr(target, key, value)
        if target.kind == LateFeeRule.Kind.PERCENT and not (0 < target.percent <= HUNDRED):
            raise _invalid("percent", _("Give a percentage between 0 and 100."))
        if target.kind == LateFeeRule.Kind.FIXED and target.amount <= 0:
            raise _invalid("amount", _("Give the fee amount."))
        if target.cap is not None and target.cap <= 0:
            raise _invalid("cap", _("The cap must be more than zero."))
        if target.active:
            LateFeeRule.objects.filter(branch_id=target.branch_id, active=True).exclude(
                pk=target.pk
            ).update(active=False)
        target.save()

    if rule is None:
        rule = LateFeeRule()
        apply(rule)
        audit.record_create(rule)
        return rule
    with audit.track(rule, action="update"):
        apply(rule)
    return rule


def rule_for(branch_id: Any) -> LateFeeRule | None:
    rules = LateFeeRule.objects.filter(active=True)
    return rules.filter(branch_id=branch_id).first() or rules.filter(branch__isnull=True).first()


def _only_fees(invoice: Invoice) -> bool:
    kinds = set(Charge.objects.filter(invoice=invoice).values_list("kind", flat=True))
    return bool(kinds) and kinds <= {Charge.Kind.LATE_FEE}


def fee_offsets(rule: LateFeeRule) -> list[int]:
    count = 1 if rule.recurrence == LateFeeRule.Recurrence.ONCE else rule.max_applications
    count = max(1, min(count, MAX_MONTHLY))
    return [rule.days_overdue + MONTH * i for i in range(count)]


def _applied(invoice: Invoice) -> Money:
    rows = Charge.objects.filter(source_key__startswith=f"late_fee:{invoice.pk}:").exclude(
        status=Charge.Status.VOID
    )
    return sum((c.net for c in rows), Money.zero(invoice.currency))


@transaction.atomic
def apply_late_fee(invoice_id: Any, number: int) -> str:
    """Charge late fee ``number`` (1-based) on an overdue invoice: ``applied``,
    ``exists``, ``closed`` (paid meanwhile), ``capped``, ``no_rule`` or ``below_minimum``."""
    from . import services

    invoice = Invoice.objects.select_for_update().select_related("client").filter(pk=invoice_id)
    row = invoice.first()
    if row is None or not row.is_open:
        return "closed"
    key = f"late_fee:{row.pk}:{number}"
    if Charge.objects.filter(source_key=key).exists():
        return "exists"
    rule = rule_for(row.branch_id)
    if rule is None:
        return "no_rule"
    if row.balance_due.amount < rule.minimum_balance:
        return "below_minimum"
    currency = row.currency
    if rule.kind == LateFeeRule.Kind.PERCENT:
        fee = (row.balance_due * rule.percent / HUNDRED).round_to_minor()
    else:
        fee = Money(rule.amount, currency).round_to_minor()
    if rule.cap is not None:
        room = Money(rule.cap, currency) - _applied(row)
        fee = min(fee, room) if room.is_positive() else Money.zero(currency)
    if not fee.is_positive():
        return "capped"
    rate = rule.tax_rate
    charge = services._create_charge(
        client=row.client,
        kind=Charge.Kind.LATE_FEE,
        source_key=key,
        description=_("Late payment fee \N{EN DASH} %(number)s") % {"number": row.number},
        day=services.org_today(),
        price=fee,
        quantity=Decimal(1),
        unit="fee",
        tax_percent=rate.percent if rate else Decimal(0),
        tax_rate_id=rate.pk if rate else None,
        branch_id=row.branch_id,
        category="late_fee",
    )
    publish(
        events.LateFeeApplied(
            subject_id=row.pk,
            client_id=str(row.client_id),
            charge_id=str(charge.pk),
            amount=charge.gross.to_dict(),
            number=number,
        ),
        branch_id=row.branch_id,
    )
    if rule.mode == LateFeeRule.Mode.IMMEDIATE:
        for draft in services.build_drafts(Charge.objects.filter(pk=charge.pk), skip_small=False):
            services.issue_invoice(draft)
    return "applied"


@transaction.atomic
def apply_next_late_fee(invoice_id: Any) -> str:
    """The Payment chasing workflow's "Apply a late fee" (E33 T04): the next application of
    the rule on this invoice, or why not (``only_fees``, or what ``apply_late_fee`` says).
    The workflow decides when; the rule decides how much."""
    invoice = Invoice.objects.filter(pk=invoice_id).first()
    if invoice is None or not invoice.is_open:
        return "closed"
    if _only_fees(invoice):
        return "only_fees"
    applied = Charge.objects.filter(source_key__startswith=f"late_fee:{invoice.pk}:").count()
    return apply_late_fee(invoice.pk, applied + 1)


@transaction.atomic
def waive_late_fee(charge: Charge, *, reason: str, user: Any = None) -> Charge:
    """Waive a late fee: void it if not invoiced, otherwise credit it (a credit note on its
    invoice line; issued invoices are never edited)."""
    from . import services

    charge = (
        Charge.objects.select_for_update(of=("self",)).select_related("invoice").get(pk=charge.pk)
    )
    if charge.kind != Charge.Kind.LATE_FEE:
        raise _invalid("charge", _("That isn't a late fee."))
    if charge.status == Charge.Status.VOID:
        raise BusinessRuleViolation(_("This fee was already waived."))
    if not reason.strip():
        raise _invalid("reason", _("Give a reason."))
    invoice = charge.invoice
    if invoice is not None and invoice.status == Invoice.Status.DRAFT:
        services.remove_line(invoice, charge.line)
        charge.refresh_from_db()
        invoice = None
    if invoice is None:
        services.void_charge(charge, reason="waived")
    else:
        line = charge.line
        left = line.gross - line.credited
        if not left.is_positive():
            raise BusinessRuleViolation(_("This fee was already credited."))
        services.create_credit_note(
            invoice,
            reason=reason,
            application="invoice" if invoice.is_open else "credit",
            lines=[{"line": line, "amount": left}],
            user=user,
        )
    audit.record(charge, "waive", {"reason": [None, reason[:200]]})
    publish(
        events.LateFeeWaived(
            subject_id=charge.pk,
            client_id=str(charge.client_id),
            reason=reason[:300],
            amount=charge.gross.to_dict(),
        ),
        branch_id=charge.branch_id,
    )
    return charge


# --- collections ----------------------------------------------------------------------------


@transaction.atomic
def open_collections(invoice_id: Any, *, dedupe_key: str | None = None) -> bool:
    """Put the client in collections for this overdue invoice: a staff task and a booking
    block (``billing.collections_block``)."""
    from tutortrack.crm import services as crm

    invoice = Invoice.objects.select_related("client").filter(pk=invoice_id).first()
    if invoice is None or not invoice.is_open:
        return False
    if CollectionsCase.objects.filter(invoice=invoice, status=CollectionsCase.Status.OPEN).exists():
        return False
    manager = invoice.client.account_manager
    task = crm.create_task(
        title=_("Chase overdue invoice %(number)s (%(client)s)")
        % {"number": invoice.number, "client": invoice.client.display_name},
        target_type="billing.invoice",
        target_id=str(invoice.pk),
        due_at=now() + timedelta(days=1),
        assignee_id=manager.user_id if manager is not None else None,
        priority="high",
    )
    case = CollectionsCase.objects.create(
        client=invoice.client,
        invoice=invoice,
        block=str(get_setting("billing.collections_block")),
        task_id=str(task.pk),
        opened_at=now(),
    )
    audit.record_create(case)
    publish(
        events.CollectionsOpened(
            subject_id=invoice.client_id,
            invoice_id=str(invoice.pk),
            case_id=str(case.pk),
            block=case.block,
            balance_due=invoice.balance_due.to_dict(),
        ),
        branch_id=invoice.branch_id,
        dedupe_key=dedupe_key,
    )
    return True


@transaction.atomic
def close_collections(invoice_id: Any, *, reason: str = "") -> int:
    """The invoice was paid, voided or written off: its collections case closes."""
    closed = 0
    for case in CollectionsCase.objects.select_for_update().filter(
        invoice_id=invoice_id, status=CollectionsCase.Status.OPEN
    ):
        with audit.track(case, action="close"):
            case.status = CollectionsCase.Status.CLOSED
            case.closed_at = now()
            case.close_reason = reason[:300]
            case.save()
        publish(
            events.CollectionsClosed(
                subject_id=case.client_id, invoice_id=str(invoice_id), case_id=str(case.pk)
            )
        )
        closed += 1
    return closed


@transaction.atomic
def close_case(case: CollectionsCase, *, reason: str, user: Any = None) -> CollectionsCase:
    """Staff take a client out of collections (e.g. a payment plan was agreed)."""
    if case.status != CollectionsCase.Status.OPEN:
        raise BusinessRuleViolation(_("This case is already closed."))
    close_collections(case.invoice_id, reason=reason or _("Closed by staff"))
    case.refresh_from_db()
    return case
