"""Bank reconciliation (E11-T13, FR-11-5): statement imports and Open Banking feeds fill a
queue of bank transactions; each money-in line gets suggested matches, and staff confirm
(or ignore) them. Confirming records the payment through the normal payment services, so
ledgers, invoices and accounting sync follow.

Suggestions, best first (score):

* an open invoice whose number appears in the reference or description (100 when the
  amount equals what is owed, otherwise 80);
* an open payment request by number (95 / 75);
* a provider payout of exactly this amount arriving within 3 days (90): the bank side of
  a Stripe or GoCardless payout;
* a bank-transfer payment already recorded for this amount within 3 days (70);
* a client whose open invoices include exactly this amount (60, 80 if their name is in
  the text).
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.billing.models import Invoice, PaymentRequest
from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import events
from .models import (
    BankStatementImport,
    BankTransaction,
    Payment,
    ProviderPayout,
    ReconciliationMatch,
)
from .statements import Parsed, Row, fill_ids

WINDOW = timedelta(days=3)
MAX_SUGGESTIONS = 3
Kind = ReconciliationMatch.Kind


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _org_currency() -> str:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    return str(Organisation.objects.get(pk=require_organisation_id()).default_currency)


# --- import ------------------------------------------------------------------------------------


@transaction.atomic
def import_rows(
    parsed: Parsed,
    *,
    source: str,
    filename: str = "",
    currency: str = "",
    connection_id: str = "",
    user: Any = None,
) -> BankStatementImport:
    """Store new lines (lines already imported, by bank id or hash, are skipped) and
    suggest matches for the money coming in."""
    fill_ids(parsed.rows)
    currency = (currency or parsed.currency or _org_currency()).upper()
    statement = BankStatementImport.objects.create(
        source=source,
        filename=filename[:255],
        account_name=parsed.account_name[:120],
        currency=currency,
        connection_id=connection_id,
        imported_by=user,
    )
    known = set(
        BankTransaction.objects.filter(
            external_id__in=[r.external_id for r in parsed.rows]
        ).values_list("external_id", flat=True)
    )
    created = suggested = 0
    for row in parsed.rows:
        if row.external_id in known:
            continue
        known.add(row.external_id)
        txn = _create(statement, row, currency)
        created += 1
        if suggest(txn):
            suggested += 1
    auto = _auto_confirm(statement, user)
    statement.stats = {
        "rows": len(parsed.rows),
        "new": created,
        "duplicates": len(parsed.rows) - created,
        "suggested": suggested,
        "auto_matched": auto,
    }
    statement.save(update_fields=["stats", "updated_at"])
    audit.record_create(statement)
    publish(
        events.BankStatementImported(
            subject_id=statement.pk, source=source, stats=dict(statement.stats)
        )
    )
    return statement


def _create(statement: BankStatementImport, row: Row, currency: str) -> BankTransaction:
    code = (row.currency or currency).upper()
    return BankTransaction.objects.create(
        statement=statement,
        external_id=row.external_id[:128],
        booked_on=row.booked_on,
        currency=code,
        amount=Money(row.amount, code).round_to_minor(),
        description=row.description[:500],
        reference=row.reference[:200],
        counterparty=row.counterparty[:200],
    )


def _auto_confirm(statement: BankStatementImport, user: Any) -> int:
    if not get_setting("payments.bank_auto_match"):
        return 0
    done = 0
    for txn in statement.transactions.filter(status=BankTransaction.Status.SUGGESTED):
        best = txn.matches.filter(status=ReconciliationMatch.Status.SUGGESTED).first()
        if best is not None and best.score >= 100:
            confirm(txn, best, user=user)
            done += 1
    return done


# --- matching ----------------------------------------------------------------------------------


def suggest(txn: BankTransaction) -> list[ReconciliationMatch]:
    """(Re)build the suggestions for a money-in line."""
    txn.matches.filter(status=ReconciliationMatch.Status.SUGGESTED).delete()
    if not txn.amount.is_positive() or txn.status in {
        BankTransaction.Status.MATCHED,
        BankTransaction.Status.IGNORED,
    }:
        return []
    text = " ".join((txn.description, txn.reference, txn.counterparty))
    flat = _norm(text)
    found: list[dict[str, Any]] = []
    amount = txn.amount
    invoices = Invoice.objects.filter(
        currency=txn.currency, status__in=Invoice.OPEN
    ).select_related("client")
    for invoice in invoices:
        if invoice.number and _norm(invoice.number) in flat:
            exact = invoice.balance_due == amount
            found.append(
                {
                    "kind": Kind.INVOICE,
                    "invoice": invoice,
                    "client": invoice.client,
                    "score": 100 if exact else 80,
                    "reason": _("Invoice %(n)s in the reference") % {"n": invoice.number},
                }
            )
    for request in PaymentRequest.objects.filter(
        currency=txn.currency, status=PaymentRequest.Status.OPEN
    ).select_related("client"):
        if _norm(request.number) in flat:
            due = request.amount - request.amount_paid
            found.append(
                {
                    "kind": Kind.PAYMENT_REQUEST,
                    "payment_request": request,
                    "client": request.client,
                    "score": 95 if due == amount else 75,
                    "reason": _("Request %(n)s in the reference") % {"n": request.number},
                }
            )
    matched_payouts = BankTransaction.objects.exclude(payout=None).values("payout_id")
    for payout in ProviderPayout.objects.filter(
        currency=txn.currency,
        amount_amount=amount.amount,
        arrival_date__gte=txn.booked_on - WINDOW,
        arrival_date__lte=txn.booked_on + WINDOW,
    ).exclude(pk__in=matched_payouts):
        found.append(
            {
                "kind": Kind.PAYOUT,
                "payout": payout,
                "score": 90,
                "reason": _("Payout %(ref)s") % {"ref": payout.provider_ref},
            }
        )
    linked = BankTransaction.objects.exclude(payment=None).values("payment_id")
    for payment in (
        Payment.objects.filter(
            currency=txn.currency,
            amount_amount=amount.amount,
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.SUCCEEDED,
            received_at__date__gte=txn.booked_on - WINDOW,
            received_at__date__lte=txn.booked_on + WINDOW,
        )
        .exclude(pk__in=linked)
        .select_related("client")
    ):
        found.append(
            {
                "kind": Kind.PAYMENT,
                "payment": payment,
                "client": payment.client,
                "score": 70,
                "reason": _("Payment already recorded"),
            }
        )
    if not any(f["kind"] == Kind.INVOICE for f in found):
        by_amount = [i for i in invoices if i.balance_due == amount]
        clients = {i.client_id: i.client for i in by_amount}
        for client in clients.values():
            named = any(
                len(w) > 2 and w in flat for w in (_norm(p) for p in client.display_name.split())
            )
            found.append(
                {
                    "kind": Kind.CLIENT,
                    "client": client,
                    "score": 80 if named else 60,
                    "reason": _("Same amount as an open invoice"),
                }
            )
    found.sort(key=lambda f: -f["score"])
    rows = [
        ReconciliationMatch.objects.create(
            transaction=txn,
            kind=f["kind"],
            invoice=f.get("invoice"),
            payment_request=f.get("payment_request"),
            client=f.get("client"),
            payment=f.get("payment"),
            payout=f.get("payout"),
            score=f["score"],
            reason=str(f["reason"])[:200],
        )
        for f in found[:MAX_SUGGESTIONS]
    ]
    status = BankTransaction.Status.SUGGESTED if rows else BankTransaction.Status.UNMATCHED
    if txn.status != status:
        txn.status = status
        txn.save(update_fields=["status", "updated_at"])
    return rows


def _open(txn: BankTransaction) -> BankTransaction:
    txn = BankTransaction.objects.select_for_update().get(pk=txn.pk)
    if txn.status in {BankTransaction.Status.MATCHED, BankTransaction.Status.IGNORED}:
        raise BusinessRuleViolation(_("This line is already dealt with."))
    return txn


def _matched(txn: BankTransaction, kind: str, user: Any, payment: Payment | None = None) -> None:
    txn.status = BankTransaction.Status.MATCHED
    txn.matched_at = now()
    txn.matched_by = user
    txn.save()
    audit.record(txn, "match", {"kind": [None, kind]})
    publish(
        events.BankTransactionMatched(
            subject_id=txn.pk,
            kind=kind,
            amount=txn.amount.to_dict(),
            payment_id=str(payment.pk) if payment else None,
        )
    )


def _received(txn: BankTransaction) -> Any:
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    return datetime.combine(txn.booked_on, time(12, 0), tzinfo=ZoneInfo("UTC"))


@transaction.atomic
def confirm(
    txn: BankTransaction,
    match: ReconciliationMatch | None = None,
    *,
    client: Any = None,
    invoice: Invoice | None = None,
    user: Any = None,
) -> BankTransaction:
    """Confirm a suggestion (or a client/invoice staff chose): records the bank transfer
    and allocates it (or links the payment or payout already recorded)."""
    from . import services

    txn = _open(txn)
    if match is not None and match.transaction_id != txn.pk:
        raise _invalid("match", _("That match is for another line."))
    if not txn.amount.is_positive():
        raise _invalid("match", _("Only money coming in can be matched."))
    kind = match.kind if match is not None else (Kind.INVOICE if invoice else Kind.CLIENT)
    target_invoice = match.invoice if match is not None else invoice
    target_client = (match.client if match is not None else client) or (
        target_invoice.client if target_invoice else None
    )
    payment = None
    reference = (txn.reference or txn.description)[:120]
    if kind == Kind.PAYOUT and match is not None:
        txn.payout = match.payout
    elif kind == Kind.PAYMENT and match is not None:
        payment = match.payment
        txn.payment = payment
    elif kind == Kind.PAYMENT_REQUEST and match is not None:
        request = PaymentRequest.objects.get(pk=match.payment_request_id)
        payment = services.record_manual_payment(
            client=request.client,
            amount=txn.amount,
            method=Payment.Method.BANK_TRANSFER,
            received_at=_received(txn),
            reference=reference,
            payment_request=request,
            user=user,
        )
        txn.payment = payment
    else:
        if target_client is None:
            raise _invalid("client", _("Choose the client who paid."))
        allocations = None
        if target_invoice is not None and target_invoice.is_open:
            if target_invoice.client_id != target_client.pk:
                raise _invalid("invoice", _("That invoice is for another client."))
            allocations = [(target_invoice, min(txn.amount, target_invoice.balance_due))]
        payment = services.record_manual_payment(
            client=target_client,
            amount=txn.amount,
            method=Payment.Method.BANK_TRANSFER,
            received_at=_received(txn),
            reference=reference,
            allocations=allocations,
            user=user,
        )
        txn.payment = payment
    if match is not None:
        match.status = ReconciliationMatch.Status.CONFIRMED
        match.save(update_fields=["status", "updated_at"])
        txn.matches.exclude(pk=match.pk).update(status=ReconciliationMatch.Status.REJECTED)
    _matched(txn, kind, user, payment)
    return txn


@transaction.atomic
def confirm_split(
    txn: BankTransaction, parts: list[dict[str, Any]], *, payer_name: str = "", user: Any = None
) -> BankTransaction:
    """One bank receipt for several clients (E11-T14): a split payment."""
    from . import services

    txn = _open(txn)
    group = services.record_split_payment(
        payer_name=payer_name or txn.counterparty or txn.description[:200] or _("Bank transfer"),
        amount=txn.amount,
        method=Payment.Method.BANK_TRANSFER,
        parts=parts,
        received_at=_received(txn),
        reference=(txn.reference or txn.description)[:120],
        user=user,
    )
    txn.payment_group = group
    txn.matches.update(status=ReconciliationMatch.Status.REJECTED)
    _matched(txn, "split", user)
    return txn


@transaction.atomic
def ignore(txn: BankTransaction, *, user: Any = None) -> BankTransaction:
    txn = _open(txn)
    txn.status = BankTransaction.Status.IGNORED
    txn.matched_by = user
    txn.matched_at = now()
    txn.save()
    txn.matches.update(status=ReconciliationMatch.Status.REJECTED)
    audit.record(txn, "ignore")
    return txn


@transaction.atomic
def reopen(txn: BankTransaction, *, user: Any = None) -> BankTransaction:
    """Put an ignored line back in the queue (matched lines stay: refund or reallocate the
    payment instead)."""
    txn = BankTransaction.objects.select_for_update().get(pk=txn.pk)
    if txn.status != BankTransaction.Status.IGNORED:
        raise BusinessRuleViolation(_("Only ignored lines can be reopened."))
    txn.status = BankTransaction.Status.UNMATCHED
    txn.save(update_fields=["status", "updated_at"])
    suggest(txn)
    return txn


# --- Open Banking feeds -------------------------------------------------------------------------


def sync_feed(connection_id: Any, *, user: Any = None) -> BankStatementImport | None:
    """Pull new transactions from an Open Banking connection (E22 integration framework)."""
    from tutortrack.integrations import providers as registry
    from tutortrack.integrations import services as integrations
    from tutortrack.integrations.models import IntegrationConnection

    from .bank_feeds import CAPABILITY

    connection = IntegrationConnection.objects.filter(pk=connection_id).first()
    if connection is None or not connection.is_live:
        return None
    since = (
        (connection.last_sync_at - timedelta(days=3)).date() if connection.last_sync_at else None
    )
    try:
        client = registry.client(connection.provider, CAPABILITY)
        parsed = client.transactions(integrations.credentials(connection), since=since)
    except registry.ProviderError as exc:
        integrations.record_failure(connection, exc)
        raise
    statement = import_rows(
        parsed,
        source=BankStatementImport.Source.OPEN_BANKING,
        connection_id=str(connection.pk),
        filename=connection.account_name,
        user=user,
    )
    integrations.record_success(connection, synced=True)
    return statement


def money_in_total(rows: list[Row]) -> Decimal:
    return sum((r.amount for r in rows if r.amount > 0), Decimal(0))
