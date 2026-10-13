"""Applying stored GoCardless and PayPal webhook events (E11-T11/T12). Idempotent: rows are
marked processed, payments are unique per provider reference, and every step checks the
current state first (events may arrive twice or out of order)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from django.db import transaction

from tutortrack.billing.models import Invoice, PaymentRequest
from tutortrack.core.events import publish
from tutortrack.core.money import Money
from tutortrack.core.time import now

from . import events
from .models import (
    Payment,
    PaymentMethod,
    ProviderAccount,
    ProviderPayout,
    ProviderWebhookEvent,
)
from .providers import ProviderError, redirect_provider


def process(row: ProviderWebhookEvent) -> None:
    account = ProviderAccount.objects.filter(
        provider=row.provider, account_ref=row.account_ref
    ).first()
    with transaction.atomic():
        if account is not None:
            if row.provider == "gocardless":
                _gocardless(account, row.type, row.payload)
            else:
                _paypal(account, row.type, row.payload.get("resource") or {})
        ProviderWebhookEvent.objects.filter(pk=row.pk).update(processed_at=now())


# --- GoCardless ------------------------------------------------------------------------------


def _gocardless(account: ProviderAccount, kind: str, event: dict[str, Any]) -> None:
    from . import services

    links = event.get("links") or {}
    details = event.get("details") or {}
    if kind == "payments.confirmed":
        payment = Payment.objects.filter(
            provider="gocardless", provider_ref=links.get("payment")
        ).first()
        if payment is not None:
            services.confirm_pending(payment)
            services._signal_collection(payment, "confirmed")
    elif kind in {"payments.failed", "payments.cancelled", "payments.charged_back"}:
        payment = Payment.objects.filter(
            provider="gocardless", provider_ref=links.get("payment")
        ).first()
        if payment is None:
            return
        if payment.status == Payment.Status.PENDING:
            services.fail_pending(
                payment,
                code=str(details.get("cause") or kind.split(".")[1]),
                message=str(details.get("description") or ""),
            )
            services._signal_collection(payment, "failed")
        elif kind == "payments.charged_back" and payment.status == Payment.Status.SUCCEEDED:
            dispute = services.open_dispute(
                payment,
                ref=str(event.get("id")),
                amount=payment.amount,
                reason="charged_back",
                due=None,
            )
            services.close_dispute(dispute, won=False)  # Direct Debit indemnity claims are final
    elif kind.startswith("mandates."):
        _mandate(account, str(links.get("mandate") or ""), kind.split(".", 1)[1])
    elif kind == "payouts.paid":
        _payout(account, str(links.get("payout") or ""))
    elif kind == "billing_requests.fulfilled":
        _fulfilled(account, str(links.get("billing_request") or ""))


def _mandate(account: ProviderAccount, ref: str, action: str) -> None:
    method = PaymentMethod.objects.filter(account=account, provider_ref=ref).first()
    if method is None:
        return
    if action in {"active", "submitted", "created"}:
        if method.mandate_status != action:
            PaymentMethod.objects.filter(pk=method.pk).update(mandate_status=action)
            if action == "active":
                publish(
                    events.MandateActive(
                        subject_id=method.pk,
                        client_id=str(method.client_id),
                        provider=account.provider,
                        status=action,
                    )
                )
    elif action in {"cancelled", "failed", "expired", "blocked"}:
        if method.status == PaymentMethod.Status.REMOVED and method.mandate_status == action:
            return
        PaymentMethod.objects.filter(pk=method.pk).update(mandate_status=action)
        method.refresh_from_db()
        if method.status == PaymentMethod.Status.ACTIVE:
            from . import services

            services.remove_method(method)  # the provider already ended it
        publish(
            events.MandateCancelled(
                subject_id=method.pk,
                client_id=str(method.client_id),
                provider=account.provider,
                status=action,
            )
        )


def _payout(account: ProviderAccount, ref: str) -> None:
    if not ref or ProviderPayout.objects.filter(provider_ref=ref).exists():
        return
    try:
        info = redirect_provider(account.provider).payout(account.account_ref, ref)
    except ProviderError:
        raise
    # Fees arrive with the payout: record them on the payments so accounting posts gross
    # receipts, fees and net to bank (FR-11-10, E23).
    for payment_ref, fee in info.fees.items():
        payment = Payment.objects.filter(
            provider=account.provider, provider_ref=payment_ref
        ).first()
        if payment is not None and payment.fee is None:
            payment.fee, payment.net = fee, payment.amount - fee
            payment.save(update_fields=["fee_amount", "net_amount", "updated_at"])
    payout = ProviderPayout.objects.create(
        account=account,
        provider_ref=ref,
        currency=info.amount.currency,
        amount=info.amount,
        status=info.status,
        arrival_date=info.arrival_date if isinstance(info.arrival_date, date) else None,
    )
    publish(events.PayoutReceived(subject_id=payout.pk, amount=payout.amount.to_dict()))


def _target(metadata: dict[str, str]) -> Invoice | PaymentRequest | None:
    if metadata.get("invoice_id"):
        return Invoice.objects.select_related("client").filter(pk=metadata["invoice_id"]).first()
    if metadata.get("payment_request_id"):
        return (
            PaymentRequest.objects.select_related("client")
            .filter(pk=metadata["payment_request_id"])
            .first()
        )
    return None


def _fulfilled(account: ProviderAccount, request_ref: str) -> None:
    """A pay-page bank payment finished at GoCardless though the customer never came back
    to our page: record it as pending (the page would have done the same)."""
    from . import services

    try:
        intent = redirect_provider(account.provider).finish_payment(
            account.account_ref, request_ref, idempotency_key=f"finish-{request_ref}"
        )
    except ProviderError:
        return
    target = _target(intent.metadata)
    if target is None or not intent.payment or intent.amount is None:
        return
    services.record_pending(account, target, intent.payment, intent.amount)


# --- PayPal ----------------------------------------------------------------------------------


def _money(value: dict[str, Any]) -> Money:
    from decimal import Decimal

    return Money(Decimal(str(value["value"])), str(value["currency_code"]).upper())


def _paypal(account: ProviderAccount, kind: str, resource: dict[str, Any]) -> None:
    from . import services
    from .providers.paypal import decode_metadata

    if kind == "PAYMENT.CAPTURE.COMPLETED":
        ref = str(resource.get("id") or "")
        if Payment.objects.filter(provider="paypal", provider_ref=ref).exists():
            return
        metadata = decode_metadata(str(resource.get("custom_id") or ""))
        if _target(metadata) is None or not resource.get("amount"):
            return
        services.record_intent(
            account, ref, _money(resource["amount"]), metadata, method_type="paypal"
        )
    elif kind in {
        "PAYMENT.CAPTURE.REVERSED",
        "CUSTOMER.DISPUTE.CREATED",
        "CUSTOMER.DISPUTE.RESOLVED",
    }:
        capture = str(resource.get("id") or "")
        if kind != "PAYMENT.CAPTURE.REVERSED":
            disputed = (resource.get("disputed_transactions") or [{}])[0]
            capture = str(disputed.get("seller_transaction_id") or "")
        payment = Payment.objects.filter(provider="paypal", provider_ref=capture).first()
        if payment is None:
            return
        amount = (
            _money(resource["dispute_amount"])
            if resource.get("dispute_amount")
            else _money(resource["amount"])
            if resource.get("amount")
            else payment.amount
        )
        due = resource.get("seller_response_due_date")
        dispute = services.open_dispute(
            payment,
            ref=str(resource.get("dispute_id") or resource.get("id") or capture),
            amount=-amount if amount.is_negative() else amount,
            reason=str(resource.get("reason") or kind.lower())[:60],
            due=datetime.fromisoformat(due.replace("Z", "+00:00")) if due else None,
        )
        if kind == "PAYMENT.CAPTURE.REVERSED":
            services.close_dispute(dispute, won=False)
        elif kind == "CUSTOMER.DISPUTE.RESOLVED":  # may arrive before CREATED: opened above
            outcome = (resource.get("dispute_outcome") or {}).get("outcome_code", "")
            services.close_dispute(dispute, won=outcome == "RESOLVED_SELLER_FAVOUR")
            from .processes import dispute_workflow_id

            services._signal(dispute_workflow_id(dispute.organisation_id, dispute.pk), "closed")
