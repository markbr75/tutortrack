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

CATEGORIES = (
    "payments", "accounting", "payroll", "calendar", "video", "messaging", "marketing",
    "banking", "screening", "automation",
)  # fmt: skip


@dataclass(frozen=True)
class Integration:
    key: str
    name: str
    category: str
    description: str
    settings_path: str = ""
    # Returns connected | needs_attention | available | coming_soon. None: "coming_soon".
    status: Callable[[], str] | None = None
    # Optional one-line detail for the card, e.g. "3 people connected" (G6).
    detail: Callable[[], str] | None = None


_registry: dict[str, Integration] = {}


def register(integration: Integration) -> Integration:
    if integration.category not in CATEGORIES:
        raise ValueError(f"Unknown marketplace category {integration.category!r}")
    _registry[integration.key] = integration
    return integration


def _provider_status(provider: str) -> Callable[[], str]:
    def status() -> str:
        from tutortrack.payments.models import ProviderAccount

        active = ProviderAccount.objects.filter(
            provider=provider, status=ProviderAccount.Status.ACTIVE
        ).exists()
        return "connected" if active else "available"

    return status


_stripe_status = _provider_status("stripe")


def _platform_provided() -> str:
    return "connected"  # sent through TutorTrack's own providers, nothing to connect


# --- E22/E23/E13/E11/E12/E18 connections (G6): live status from IntegrationConnection -----------


def _connections(providers: tuple[str, ...]) -> Any:
    from tutortrack.integrations.models import IntegrationConnection

    return IntegrationConnection.objects.filter(provider__in=providers).exclude(
        status=IntegrationConnection.Status.DISCONNECTED
    )


def _connection_status(*providers: str) -> Callable[[], str]:
    """``connected`` while any active connection exists (an organisation's account or any
    person's own); ``needs_attention`` when the only ones are in error or need
    reconnecting; otherwise ``available``."""

    def status() -> str:
        from tutortrack.integrations.models import IntegrationConnection

        found = set(_connections(providers).values_list("status", flat=True))
        if IntegrationConnection.Status.ACTIVE in found:
            return "connected"
        return "needs_attention" if found else "available"

    return status


def _people_connected(*providers: str) -> Callable[[], str]:
    def detail() -> str:
        from tutortrack.integrations.models import IntegrationConnection

        rows = _connections(providers).filter(status=IntegrationConnection.Status.ACTIVE)
        people = rows.filter(level=IntegrationConnection.Level.USER).values("user").distinct()
        count = people.count()
        if rows.filter(level=IntegrationConnection.Level.ORGANISATION).exists():
            return str(_("Connected for the organisation"))
        if not count:
            return ""
        from django.utils.translation import ngettext

        return ngettext("%(count)s person connected", "%(count)s people connected", count) % {
            "count": count
        }

    return detail


def _whatsapp_status() -> str:
    from tutortrack.comms.models import Channel, PhoneNumber

    has = PhoneNumber.objects.filter(channel=Channel.WHATSAPP).exists()
    return "connected" if has else "available"


for _integration in (
    Integration("stripe", "Stripe", "payments",
                str(_("Card and wallet payments, autopay and payouts.")),
                settings_path="/settings/payments", status=_stripe_status),
    Integration("gocardless", "GoCardless", "payments",
                str(_("Direct Debit mandates and collections.")),
                settings_path="/settings/payments", status=_provider_status("gocardless")),
    Integration("paypal", "PayPal", "payments",
                str(_("Pay invoices with PayPal on the payment page.")),
                settings_path="/settings/payments", status=_provider_status("paypal")),
    Integration("xero", "Xero", "accounting",
                str(_("Sync invoices, payments and contacts to Xero.")),
                settings_path="/settings/accounting", status=_connection_status("xero")),
    Integration("quickbooks", "QuickBooks Online", "accounting",
                str(_("Sync invoices, payments and customers to QuickBooks.")),
                settings_path="/settings/accounting", status=_connection_status("quickbooks")),
    Integration("sage", "Sage Business Cloud Accounting", "accounting",
                str(_("Sync invoices, payments and contacts to Sage.")),
                settings_path="/settings/accounting", status=_connection_status("sage")),
    Integration("freeagent", "FreeAgent", "accounting",
                str(_("Sync invoices, payments and contacts to FreeAgent.")),
                settings_path="/settings/accounting", status=_connection_status("freeagent")),
    Integration("xero_payroll", "Xero Payroll", "payroll",
                str(_("Send employed tutors' timesheets to Xero Payroll.")),
                settings_path="/settings/accounting/payroll",
                status=_connection_status("xero_payroll")),
    Integration("wise", "Wise Business", "payroll",
                str(_("Pay tutors by bank transfer in their own currency.")),
                settings_path="/settings/integrations", status=_connection_status("wise")),
    Integration("google_calendar", "Google Calendar", "calendar",
                str(_("Two-way sync of lessons and busy times.")),
                settings_path="/account", status=_connection_status("google"),
                detail=_people_connected("google")),
    Integration("outlook", "Microsoft 365 / Outlook", "calendar",
                str(_("Two-way sync of lessons and busy times.")),
                settings_path="/account", status=_connection_status("microsoft"),
                detail=_people_connected("microsoft")),
    Integration("caldav", "Apple iCloud (CalDAV)", "calendar",
                str(_("Two-way sync with iCloud and other CalDAV calendars.")),
                settings_path="/account", status=_connection_status("caldav"),
                detail=_people_connected("caldav")),
    Integration("zoom", "Zoom", "video", str(_("Meeting links for online lessons.")),
                settings_path="/settings/integrations", status=_connection_status("zoom"),
                detail=_people_connected("zoom")),
    Integration("google_meet", "Google Meet", "video",
                str(_("Meeting links for online lessons (with Google Calendar).")),
                settings_path="/account", status=_connection_status("google"),
                detail=_people_connected("google")),
    Integration("teams", "Microsoft Teams", "video",
                str(_("Meeting links for online lessons.")),
                settings_path="/account", status=_connection_status("microsoft"),
                detail=_people_connected("microsoft")),
    Integration("lessonspace", "Lessonspace", "video",
                str(_("Online classroom spaces per lesson or job.")),
                settings_path="/settings/integrations", status=_connection_status("lessonspace")),
    Integration("whatsapp", "WhatsApp", "messaging",
                str(_("Approved message templates and replies on WhatsApp.")),
                settings_path="/settings/messaging", status=_whatsapp_status),
    Integration("mailchimp", "Mailchimp", "marketing",
                str(_("Keep your mailing list in step with families who opted in.")),
                settings_path="/settings/messaging", status=_connection_status("mailchimp")),
    Integration("brevo", "Brevo", "marketing",
                str(_("Keep your mailing list in step with families who opted in.")),
                settings_path="/settings/messaging", status=_connection_status("brevo")),
    Integration("open_banking", str(_("Open Banking bank feed")), "banking",
                str(_("Import bank transactions and match payments automatically.")),
                settings_path="/settings/payments", status=_connection_status("open_banking")),
    Integration("ucheck", "uCheck (DBS checks)", "screening",
                str(_("Order and track DBS checks for tutors.")),
                settings_path="/compliance", status=_connection_status("ucheck")),
    Integration("checkr", "Checkr", "screening",
                str(_("Order and track US background checks for tutors.")),
                settings_path="/compliance", status=_connection_status("checkr")),
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
                "detail": integration.detail() if integration.detail else "",
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
                "detail": "",
                "settings_path": "/developer/apps",
                "kind": "partner",
                "client_id": app.client_id,
                "homepage_url": app.homepage_url,
            }
        )
    return out
