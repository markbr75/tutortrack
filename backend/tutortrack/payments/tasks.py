"""Webhook processing and receipts (E11-T01, T09)."""

from __future__ import annotations

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import translation
from django.utils.translation import gettext as _

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
    from tutortrack.core.time import now
    from tutortrack.tenancy.models import Organisation

    from . import pdf
    from .models import Payment

    payment = Payment.objects.select_related("client").filter(pk=payment_id).first()
    if payment is None or payment.receipt_sent_at:
        return False
    client = payment.client
    contact = client.billing_contact or client.primary_contact
    if contact is None or not contact.email:
        return False
    org = Organisation.objects.get(pk=organisation_id)
    with translation.override(org.locale):
        message = EmailMessage(
            subject=_("Payment received \N{EN DASH} thank you"),
            body=_("Hello,\n\nWe received your payment of %(amount)s. Your receipt is attached.\n")
            % {"amount": payment.amount.format(org.locale.replace("-", "_"))},
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[contact.email],
        )
    message.attach(f"receipt-{payment.pk}.pdf", pdf.receipt_pdf(payment), "application/pdf")
    message.send()
    Payment.objects.filter(pk=payment.pk).update(receipt_sent_at=now())
    return True
