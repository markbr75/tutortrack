"""Sending invoices by email (E10-T03), through communications (E13) so templates,
preferences, suppressions and the message log apply."""

from __future__ import annotations

from celery import shared_task
from django.conf import settings

from tutortrack.core.tasks import TenantTask


def pay_url(organisation: object, token: str) -> str:
    slug = getattr(organisation, "slug", "")
    return f"https://{slug}.{settings.TENANT_BASE_DOMAIN}/pay/{token}"


@shared_task(base=TenantTask, name="tutortrack.billing.tasks.send_invoice_email")
def send_invoice_email(*, organisation_id: str, invoice_id: str, resend: bool = False) -> bool:
    """Email the invoice with its PDF to the client's invoice contacts. True if sent."""
    from tutortrack.comms import services as comms
    from tutortrack.core.time import now

    from .models import Invoice

    invoice = Invoice.objects.select_related("client").filter(pk=invoice_id).first()
    if invoice is None or invoice.status in {Invoice.Status.DRAFT, Invoice.Status.VOID}:
        return False
    key = f"{invoice.pk}:{now().timestamp()}" if resend else str(invoice.pk)
    messages = comms.notify(
        "invoice_issued", invoice, key=key, immediate=True, only_channel="email"
    )
    return any(m.status == "sent" for m in messages)
