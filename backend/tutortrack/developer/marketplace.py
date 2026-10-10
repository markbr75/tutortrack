"""The in-app integrations marketplace (FR-27-5, E27-T08).

Native integrations are registered here or by their own app in ``<app>/marketplace.py``
(autodiscovered), each with a status callback run in the tenant context:

    from tutortrack.developer.marketplace import Integration, register

    register(Integration("google_calendar", "Google Calendar", "calendar", "...",
                         settings_path="/account/integrations", status=my_status))

Partner OAuth apps (Zapier, Make, and other published apps) are listed from
``OAuthApplication``; they show as connected when the organisation has an active grant.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.utils.module_loading import autodiscover_modules
from django.utils.translation import gettext_lazy as _

CATEGORIES = ("payments", "accounting", "calendar", "video", "messaging", "automation")


@dataclass(frozen=True)
class Integration:
    key: str
    name: str
    category: str
    description: str
    settings_path: str = ""
    # Returns connected | available | coming_soon. None: always "coming_soon".
    status: Callable[[], str] | None = None


_registry: dict[str, Integration] = {}


def register(integration: Integration) -> Integration:
    if integration.category not in CATEGORIES:
        raise ValueError(f"Unknown marketplace category {integration.category!r}")
    _registry[integration.key] = integration
    return integration


def _stripe_status() -> str:
    from tutortrack.payments.models import ProviderAccount

    active = ProviderAccount.objects.filter(
        provider="stripe", status=ProviderAccount.Status.ACTIVE
    ).exists()
    return "connected" if active else "available"


def _platform_provided() -> str:
    return "connected"  # sent through TutorTrack's own providers, nothing to connect


for _integration in (
    Integration("stripe", "Stripe", "payments",
                str(_("Card and wallet payments, autopay and payouts.")),
                settings_path="/settings/payments", status=_stripe_status),
    Integration("gocardless", "GoCardless", "payments",
                str(_("Direct Debit mandates and collections."))),
    Integration("xero", "Xero", "accounting",
                str(_("Sync invoices, payments and contacts to Xero."))),
    Integration("quickbooks", "QuickBooks Online", "accounting",
                str(_("Sync invoices, payments and customers to QuickBooks."))),
    Integration("google_calendar", "Google Calendar", "calendar",
                str(_("Two-way sync of lessons and busy times."))),
    Integration("outlook", "Microsoft 365 / Outlook", "calendar",
                str(_("Two-way sync of lessons and busy times."))),
    Integration("zoom", "Zoom", "video", str(_("Meeting links for online lessons."))),
    Integration("teams", "Microsoft Teams", "video",
                str(_("Meeting links for online lessons."))),
    Integration("lessonspace", "Lessonspace", "video",
                str(_("Online classroom spaces per lesson or job."))),
    Integration("email", str(_("Email")), "messaging",
                str(_("Transactional email from your organisation's address.")),
                settings_path="/settings/notifications", status=_platform_provided),
    Integration("sms", str(_("SMS")), "messaging",
                str(_("Text message reminders and replies.")),
                settings_path="/settings/notifications", status=_platform_provided),
):  # fmt: skip
    register(_integration)


def entries() -> list[dict[str, Any]]:
    from .models import OAuthGrant
    from .selectors import partner_applications

    autodiscover_modules("marketplace")
    out = []
    for integration in sorted(_registry.values(), key=lambda i: (i.category, i.name)):
        status = integration.status() if integration.status else "coming_soon"
        out.append(
            {
                "key": integration.key,
                "name": integration.name,
                "category": integration.category,
                "description": integration.description,
                "status": status,
                "settings_path": integration.settings_path,
                "kind": "native",
                "client_id": "",
                "homepage_url": "",
            }
        )
    connected = set(
        OAuthGrant.objects.filter(revoked_at__isnull=True).values_list("application_id", flat=True)
    )
    for app in partner_applications():
        out.append(
            {
                "key": app.partner_key or str(app.pk),
                "name": app.name,
                "category": "automation",
                "description": app.description,
                "status": "connected" if app.pk in connected else "available",
                "settings_path": "/developer/apps",
                "kind": "partner",
                "client_id": app.client_id,
                "homepage_url": app.homepage_url,
            }
        )
    return out
