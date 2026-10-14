"""Expiring-card notices (FR-11-2, gap G3).

On the first day of each month a fan-out Celery beat task (short and stateless) looks for
saved cards that expire at the end of that month and, with ``payments.card_expiry_notices``,
emails the client a link to add a new card (``card_expiring``) and publishes
``payment_method.expiring``. Each card and expiry is told once: the comms dedupe key and the
event's dedupe key are the card and its expiry, so a re-run sends nothing new. No marker
columns or sweepers are involved.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from tutortrack.comms.catalogue import SAMPLE_BASE, _billing_deliveries
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, register
from tutortrack.core.events import publish
from tutortrack.tenancy.settings_service import get_setting

from . import events
from .models import PaymentMethod

NOTIFICATION = "card_expiring"


def expiring(today: date) -> list[PaymentMethod]:
    """Saved cards whose expiry month is this month."""
    return list(
        PaymentMethod.objects.filter(
            type="card", exp_year=today.year, exp_month=today.month
        ).select_related("client")
    )


def _setup_url(method: PaymentMethod) -> str:
    from . import services

    try:
        return services.create_setup_link(method.client, days=30)
    except Exception:
        return ""


def notify_expiring(today: date) -> int:
    from tutortrack.comms.services import notify

    if not get_setting("payments.card_expiry_notices"):
        return 0
    told = 0
    for method in expiring(today):
        key = f"{method.pk}:{method.exp_year}-{method.exp_month:02d}"
        with transaction.atomic():
            publish(
                events.PaymentMethodExpiring(
                    subject_id=method.pk,
                    client_id=str(method.client_id),
                    exp_month=int(method.exp_month or 0),
                    exp_year=int(method.exp_year or 0),
                    is_default=method.is_default,
                ),
                branch_id=method.client.branch_id,
                dedupe_key=f"card-expiring:{key}",
            )
        messages = notify(NOTIFICATION, (method, _setup_url(method)), key=key, immediate=True)
        told += len(messages)
    return told


def _resolve(payload: Any) -> list[Delivery]:
    method, url = payload
    return _billing_deliveries(
        method.client,
        {
            "card": {
                "brand": method.brand.title() if method.brand else "",
                "last4": method.last4,
                "expiry": f"{int(method.exp_month or 0):02d}/{method.exp_year}",
                "autopay": bool(method.is_default and method.client.auto_pay),
                "setup_url": url,
            }
        },
    )


def load_method(pk: str) -> Any:
    return PaymentMethod.objects.select_related("client").filter(pk=pk).first()


register(
    NotificationType(
        key=NOTIFICATION,
        label=str(_("Saved card about to expire")),
        category="billing",
        audience="client",
        channels=("email",),
        default_channels=("email",),
        resolve=_resolve,
        load=load_method,
        related_type="payments.paymentmethod",
        variables=(
            "recipient.first_name",
            "card.brand",
            "card.last4",
            "card.expiry",
            "card.autopay",
            "card.setup_url",
        ),
        sample={
            **SAMPLE_BASE,
            "card": {
                "brand": "Visa",
                "last4": "4242",
                "expiry": "11/2026",
                "autopay": True,
                "setup_url": "https://example.test/pay/setup/x",
            },
        },
        transactional=True,
    )
)
DEFAULTS[(NOTIFICATION, "email")] = (
    "Your saved card ending {{ card.last4 }} expires soon",
    "Hello {{ recipient.first_name }},\n\nYour {{ card.brand }} card ending {{ card.last4 }} "
    "expires at the end of {{ card.expiry }}."
    "{% if card.autopay %} We use it to pay your invoices automatically.{% endif %}"
    "{% if card.setup_url %}\nPlease add your new card here: {{ card.setup_url }}{% endif %}"
    + SIGN,
)
