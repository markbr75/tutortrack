"""Sending invoices and payment requests by email (E10-T03; templated messages, SMS and
preferences arrive with E13)."""

from __future__ import annotations

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import translation
from django.utils.translation import gettext as _

from tutortrack.core.tasks import TenantTask


def pay_url(organisation: object, token: str) -> str:
    slug = getattr(organisation, "slug", "")
    return f"https://{slug}.{settings.TENANT_BASE_DOMAIN}/pay/{token}"


@shared_task(base=TenantTask, name="tutortrack.billing.tasks.send_invoice_email")
def send_invoice_email(*, organisation_id: str, invoice_id: str) -> bool:
    from tutortrack.tenancy.models import Organisation

    from . import pdf, services
    from .models import Invoice

    invoice = Invoice.objects.select_related("client").filter(pk=invoice_id).first()
    if invoice is None or invoice.status in {Invoice.Status.DRAFT, Invoice.Status.VOID}:
        return False
    to = (invoice.billing_snapshot or {}).get("email") or ""
    if not to:
        return False
    org = Organisation.objects.get(pk=organisation_id)
    with translation.override(org.locale):
        body = _(
            "Hello,\n\nPlease find invoice %(number)s from %(org)s attached.\n"
            "Amount due: %(due)s by %(date)s.\nPay online: %(url)s\n"
        ) % {
            "number": invoice.number,
            "org": org.name,
            "due": invoice.balance_due.format(org.locale.replace("-", "_")),
            "date": invoice.due_date.isoformat() if invoice.due_date else "",
            "url": pay_url(org, invoice.pay_token),
        }
        message = EmailMessage(
            subject=_("Invoice %(number)s from %(org)s")
            % {
                "number": invoice.number,
                "org": org.name,
            },
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to],
        )
    message.attach(f"{invoice.number}.pdf", pdf.invoice_pdf(invoice), "application/pdf")
    message.send()
    services.mark_sent(invoice, to=[to])
    return True
