"""Staff email when a webhook endpoint is switched off after failing continuously (FR-27-3).
Registered with the comms notification registry so organisations can edit the template."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms import defaults
from tutortrack.comms.catalogue import SAMPLE_BASE, organisation, staff_with, tenant_link
from tutortrack.comms.registry import Delivery, NotificationType, register

ENDPOINT_DISABLED = "webhook_endpoint_disabled"
LINK = "/developer/webhooks"


def _load(pk: str) -> Any:
    from .models import WebhookEndpoint

    return WebhookEndpoint.objects.filter(pk=pk).first()


def _resolve(endpoint: Any) -> list[Delivery]:
    base = {
        "organisation": organisation(),
        "endpoint": {
            "url": endpoint.url,
            "description": endpoint.description,
            "failing_since": endpoint.failing_since.isoformat() if endpoint.failing_since else "",
            "link": tenant_link(LINK),
        },
    }
    return [
        Delivery(r, {**base, "recipient": {"name": r.name, "first_name": r.first_name}})
        for r in staff_with("developer.webhook.manage")
    ]


register(
    NotificationType(
        key=ENDPOINT_DISABLED,
        label=str(_("Webhook endpoint disabled")),
        category="staff",
        audience="staff",
        channels=("email",),
        default_channels=("email",),
        resolve=_resolve,
        load=_load,
        related_type="developer.webhookendpoint",
        variables=(
            "recipient.first_name",
            "endpoint.url",
            "endpoint.description",
            "endpoint.failing_since",
            "endpoint.link",
        ),
        sample={
            **SAMPLE_BASE,
            "endpoint": {
                "url": "https://hooks.example.com/tutortrack",
                "description": "CRM sync",
                "failing_since": "2026-10-01T09:00:00+00:00",
                "link": "https://example.com/developer/webhooks",
            },
        },
        transactional=True,
        link=lambda endpoint: LINK,
    )
)

defaults.DEFAULTS[(ENDPOINT_DISABLED, "email")] = (
    "Webhook endpoint disabled: {{ endpoint.url }}",
    "Hello {{ recipient.first_name }},\n\nWe stopped sending events to {{ endpoint.url }} "
    "because every delivery has failed since {{ endpoint.failing_since }}. Events that happen "
    "while it is disabled are not sent.\n\nFix the receiver, then re-enable the endpoint "
    "and redeliver what it missed: {{ endpoint.link }}" + defaults.SIGN,
)
