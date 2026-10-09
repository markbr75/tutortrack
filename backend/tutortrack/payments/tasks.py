"""Webhook processing and receipts (E11-T01, T09)."""

from __future__ import annotations

from celery import shared_task

from tutortrack.core.tasks import TenantTask


@shared_task(
    base=TenantTask,
    name="tutortrack.payments.tasks.process_webhook",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=8,
)
def process_webhook(*, organisation_id: str, event_id: str) -> None:
    from django.db.models import F

    from . import services
    from .models import ProviderWebhookEvent

    row = ProviderWebhookEvent.objects.filter(pk=event_id).first()
    if row is None:
        return
    try:
        services.process_webhook_event(row)
    except Exception as exc:
        ProviderWebhookEvent.objects.filter(pk=row.pk).update(
            attempts=F("attempts") + 1, last_error=repr(exc)[:2000]
        )
        raise


@shared_task(base=TenantTask, name="tutortrack.payments.tasks.send_receipt")
def send_receipt(*, organisation_id: str, payment_id: str) -> bool:
    """Email a PDF receipt through communications (E13). True if sent."""
    from tutortrack.comms import services as comms
    from tutortrack.core.time import now

    from .models import Payment

    payment = Payment.objects.select_related("client").filter(pk=payment_id).first()
    if payment is None or payment.receipt_sent_at:
        return False
    messages = comms.notify("payment_received", payment, key=str(payment.pk), immediate=True)
    sent = any(m.status == "sent" for m in messages)
    if sent:
        Payment.objects.filter(pk=payment.pk).update(receipt_sent_at=now())
    return sent
