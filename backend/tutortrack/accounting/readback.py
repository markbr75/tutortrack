"""Read-back of payments recorded directly in the ledger (FR-23-4, E23-T09).

Finance sometimes records a payment straight into the ledger (Xero, QuickBooks, Sage or
FreeAgent; a bank transfer reconciled from the feed). With ``import_payments`` on, the
daily run (and the "Check now" action) asks the ledger for the payments on each synced
invoice that TutorTrack still shows as owed. A payment TutorTrack didn't send and hasn't
seen before becomes an E11
manual payment through ``payments.services.record_manual_payment``, allocated to that
invoice. Its ``ExternalRecordLink`` is created already synced (with the ledger's id), so
the sync engine never pushes it back. Every outcome is written to ``LedgerPaymentImport``
(unique per ledger payment, so reading back is idempotent) and to the invoice's sync log.
Payments that don't fit (more than is owed, invoice void or paid, another currency) are
recorded as skipped with the reason, for finance to resolve.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.integrations import services as integrations
from tutortrack.integrations.providers import ProviderError

from . import events
from .errors import LABELS
from .models import AccountingConnection, AccountMapping, ExternalRecordLink, LedgerPaymentImport
from .models import SyncLogEntry as Log
from .providers import LedgerPayment, client_for

logger = structlog.get_logger(__name__)
Status = ExternalRecordLink.Status
LIMIT = 200
OPEN_INVOICE = ("issued", "partially_paid")


# Ledgers whose client can list an invoice's payments (Sage and FreeAgent: gap G5).
READ_BACK_PROVIDERS = frozenset({"xero", "quickbooks", "sage", "freeagent"})


def supported(provider: str) -> bool:
    return provider in READ_BACK_PROVIDERS


def our_payment_ids(conn: AccountingConnection) -> set[str]:
    """Ledger ids of everything TutorTrack itself posted as payments (including the parts
    of split payments and the replacement payments a refund creates in Xero)."""
    ids: set[str] = set()
    links = ExternalRecordLink.objects.filter(
        connection=conn, object_type__in=["payment", "refund", "chargeback", "reallocation"]
    ).values_list("external_id", "meta")
    for external_id, meta in links:
        if external_id:
            ids.add(external_id)
        for part in (meta or {}).get("parts") or []:
            if isinstance(part, str):  # FreeAgent: one explanation URL per allocation
                ids.add(part)
            elif len(part) > 1 and part[1]:
                ids.add(str(part[1]))
        ids.update(str(p) for p in (meta or {}).get("payments") or [] if p)
    return ids


def _method(conn: AccountingConnection, payment: LedgerPayment) -> str:
    """The payment method whose clearing account the money went into, else bank transfer."""
    from tutortrack.payments.models import Payment

    if payment.account:
        mapping = (
            AccountMapping.objects.filter(
                provider=conn.mapping_set,
                kind="clearing",
                external_id=payment.account,
                key__startswith="method:",
            )
            .order_by("key")
            .first()
        )
        if mapping is not None:
            method = mapping.key.split(":", 1)[1]
            if method in Payment.Method.values and method != Payment.Method.CARD:
                return method
    return str(Payment.Method.BANK_TRANSFER)


def read_back(conn: AccountingConnection, *, limit: int = LIMIT) -> dict[str, int]:
    """Check the ledger for payments on open synced invoices; import the new ones."""
    from tutortrack.billing.models import Invoice

    result = {"checked": 0, "imported": 0, "skipped": 0}
    if not conn.enabled or not conn.import_payments or conn.mode != conn.Mode.INDIVIDUAL:
        return result
    if not supported(conn.provider):
        return result
    try:
        creds = integrations.credentials(conn.connection)
    except ProviderError:
        return result
    client = client_for(conn.provider)
    ours = our_payment_ids(conn)
    seen = set(
        LedgerPaymentImport.objects.filter(connection=conn).values_list("external_id", flat=True)
    )
    open_ids = Invoice.objects.filter(status__in=OPEN_INVOICE).values_list("pk", flat=True)
    links = ExternalRecordLink.objects.filter(
        connection=conn,
        object_type="invoice",
        status=Status.SYNCED,
        object_id__in=[str(pk) for pk in open_ids],
    ).order_by("-synced_at")[:limit]
    for link in links:
        if not link.external_id or link.meta.get("voided"):
            continue
        try:
            found = client.invoice_payments(creds, link.external_id)
        except ProviderError as exc:
            logger.info("accounting.read_back_failed", link=str(link.pk), error=str(exc))
            continue
        result["checked"] += 1
        for payment in found:
            if payment.id in ours or payment.id in seen:
                continue
            outcome = import_payment(conn, link, payment)
            seen.add(payment.id)
            result[outcome] += 1
    AccountingConnection.objects.filter(pk=conn.pk).update(payments_checked_at=now())
    return result


def _day(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


@transaction.atomic
def import_payment(
    conn: AccountingConnection, link: ExternalRecordLink, payment: LedgerPayment
) -> str:
    """Record one ledger payment against the invoice (``imported``) or note why not
    (``skipped``). Idempotent on the ledger payment id."""
    from tutortrack.billing.models import Invoice
    from tutortrack.payments.services import record_manual_payment

    existing = LedgerPaymentImport.objects.filter(connection=conn, external_id=payment.id).first()
    if existing is not None:
        return str(existing.status)
    invoice = Invoice.objects.select_for_update().select_related("client").get(pk=link.object_id)
    provider = str(LABELS.get(conn.provider, conn.provider))
    try:
        amount = Money(Decimal(payment.amount), invoice.currency).round_to_minor()
    except (InvalidOperation, ValueError):
        amount = Money.zero(invoice.currency)
    paid_on = _day(payment.date)
    reason = ""
    if not amount.is_positive():
        reason = _("The ledger payment has no amount.")
    elif invoice.status not in OPEN_INVOICE:
        reason = _("The invoice is no longer open in TutorTrack.")
    elif amount > invoice.balance_due:
        reason = _("The payment (%(amount)s) is more than TutorTrack says is owed (%(due)s).") % {
            "amount": amount.amount,
            "due": invoice.balance_due.amount,
        }
    record = LedgerPaymentImport(
        connection=conn,
        provider=conn.provider,
        external_id=payment.id,
        invoice=invoice,
        currency=invoice.currency,
        paid_on=paid_on,
        reference=payment.reference[:255],
        status=LedgerPaymentImport.Status.SKIPPED
        if reason
        else LedgerPaymentImport.Status.IMPORTED,
        reason=reason[:300],
    )
    record.amount = amount
    if reason:
        record.save()
        audit.record_create(record)
        Log.objects.create(
            link=link,
            outcome=Log.Outcome.SKIPPED,
            message=(
                _("A payment recorded in %(provider)s wasn't imported: %(reason)s")
                % {"provider": provider, "reason": reason}
            )[:500],
        )
        return "skipped"
    received = datetime.combine(paid_on, time(12), tzinfo=UTC) if paid_on else None
    created = record_manual_payment(
        client=invoice.client,
        amount=amount,
        method=_method(conn, payment),
        received_at=received,
        reference=payment.reference or _("Recorded in %(provider)s") % {"provider": provider},
        notes=_("Recorded directly in %(provider)s and imported by TutorTrack (%(id)s).")
        % {"provider": provider, "id": payment.id},
        allocations=[(invoice, amount)],
    )
    # Already in the ledger: the sync engine must never push it back.
    ExternalRecordLink.objects.create(
        connection=conn,
        provider=conn.provider,
        object_type="payment",
        object_id=str(created.pk),
        label=(payment.reference or str(amount.amount))[:200],
        external_id=payment.id,
        status=Status.SYNCED,
        synced_at=now(),
        posted_date=paid_on,
        meta={"imported": True, "parts": [[link.external_id, payment.id, str(amount.amount)]]},
    )
    record.payment = created
    record.save()
    audit.record_create(record)
    Log.objects.create(
        link=link,
        outcome=Log.Outcome.IMPORTED,
        message=(
            _("Payment of %(amount)s recorded in %(provider)s on %(day)s imported into TutorTrack.")
            % {"amount": amount.amount, "provider": provider, "day": payment.date}
        )[:500],
    )
    publish(
        events.AccountingPaymentImported(
            subject_id=record.pk,
            provider=conn.provider,
            invoice_id=str(invoice.pk),
            payment_id=str(created.pk),
            external_id=payment.id,
            amount=amount.to_dict(),
        )
    )
    return "imported"


def run_now(conn: AccountingConnection) -> dict[str, Any]:
    """Finance's "Check now": the same read-back outside the daily run."""
    return read_back(conn)
