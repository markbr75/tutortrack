"""Mailchimp and Brevo unsubscribes flowing back (G4, FR-13-9).

People who unsubscribe in a Mailchimp or Brevo email (or whose address the service
cleans after hard bounces or spam reports) must not be re-subscribed by the next sync,
and the organisation's own records must say so. Two paths bring them back:

* **Webhooks** (``/api/v1/webhooks/marketing/<provider>/<token>``): neither service signs
  its webhooks, so the URL carries a token signed with our secret that names the
  organisation, the provider and the connection; a reconnected account gets a new URL.
  Events for another audience are ignored.
* **Read-back before a full sync** (``reconcile``): "Sync now" first asks the service who
  has left the audience.

What happens to a contact with that address:

* **Unsubscribed:** their E29 marketing email consent is withdrawn (a consent record,
  method ``import``, source ``<provider>:unsubscribe``) and their E13 ``marketing``
  preference loses email (so broadcasts skip them as ``opted_out``). Service emails
  (invoices, reminders) still reach them.
* **Spam report:** the same, plus an E13 email suppression of the address
  (``<provider>_spam``): the person complained, so nothing more is emailed to it.
* **Cleaned / hard bounce:** an E13 email suppression only (``<provider>_cleaned``): the
  address doesn't work; consent is left as it was.

Only contacts who are currently opted in are changed, so our own unsubscribes (people
without consent, sent there by the sync) never create records.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import HttpRequest

from tutortrack.core.context import require_organisation_id, tenant_context

from .models import Channel

logger = structlog.get_logger(__name__)
SALT = "comms.marketing-webhook"
UNSUBSCRIBED = "unsubscribed"
CLEANED = "cleaned"
SPAM = "spam"

# Provider event names → what happened.
MAILCHIMP_TYPES = {"unsubscribe": UNSUBSCRIBED, "cleaned": CLEANED}
BREVO_EVENTS = {
    "unsubscribed": UNSUBSCRIBED,
    "unsubscribe": UNSUBSCRIBED,
    "list_addition_unsubscribed": UNSUBSCRIBED,
    "hard_bounce": CLEANED,
    "hardbounce": CLEANED,
    "hardBounce": CLEANED,
    "invalid_email": CLEANED,
    "spam": SPAM,
    "complaint": SPAM,
}


def webhook_token(provider: str, connection_id: Any) -> str:
    data = {"o": str(require_organisation_id()), "p": provider, "c": str(connection_id)}
    return signing.dumps(data, salt=SALT)


def webhook_url(provider: str, connection_id: Any) -> str:
    token = webhook_token(provider, connection_id)
    return f"{settings.PLATFORM_BASE_URL}/api/v1/webhooks/marketing/{provider}/{token}"


def read_webhook_token(token: str) -> dict[str, str] | None:
    try:
        data = signing.loads(token, salt=SALT)
    except signing.BadSignature:
        return None
    if not isinstance(data, dict) or not {"o", "p", "c"} <= set(data):
        return None
    return {k: str(v) for k, v in data.items()}


def _events(provider: str, request: HttpRequest) -> list[tuple[str, str, str]] | None:
    """(email, what, audience id) from a webhook body; None if it can't be read."""
    if provider == "mailchimp":
        kind = MAILCHIMP_TYPES.get(str(request.POST.get("type") or ""))
        email = str(request.POST.get("data[email]") or "").strip().lower()
        audience = str(request.POST.get("data[list_id]") or "")
        if kind == CLEANED and request.POST.get("data[reason]") == "abuse":
            kind = SPAM
        return [(email, kind, audience)] if kind and email else []
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return None
    rows = body if isinstance(body, list) else [body]
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = BREVO_EVENTS.get(str(row.get("event") or ""))
        email = str(row.get("email") or "").strip().lower()
        lists = row.get("list_id") or row.get("listId") or []
        audience = ",".join(str(x) for x in (lists if isinstance(lists, list) else [lists]))
        if kind and email:
            out.append((email, kind, audience))
    return out


def handle_webhook(route: dict[str, str], request: HttpRequest) -> int | None:
    """Apply one webhook delivery. Returns how many contacts changed (None = bad body)."""
    events = _events(route["p"], request)
    if events is None:
        return None
    from tutortrack.integrations.models import IntegrationConnection

    with tenant_context(route["o"]):
        connection = IntegrationConnection.objects.filter(
            pk=route["c"], provider=route["p"]
        ).first()
        if connection is None:
            return 0  # disconnected: the old URL no longer does anything
        audience = str(connection.settings.get("audience_id") or "")
        changed = 0
        for email, kind, event_audience in events:
            if audience and event_audience and audience not in event_audience.split(","):
                continue
            with transaction.atomic():
                changed += apply(route["p"], email, kind)
        return changed


def apply(provider: str, email: str, kind: str) -> int:
    """Record that ``email`` left the provider's audience (see the module docstring)."""
    from tutortrack.people.models import Contact

    from . import marketing
    from .services import set_preference, suppress

    ids = [
        str(pk)
        for pk in Contact.objects.filter(email__iexact=email, archived_at__isnull=True).values_list(
            "pk", flat=True
        )
    ]
    opted_in = [c.contact_id for c in marketing.candidates(ids) if c.eligible] if ids else []
    if kind in {CLEANED, SPAM}:
        suppress(Channel.EMAIL, email, f"{provider}_{kind}")
    if kind == CLEANED:
        return len(ids)  # a dead address: suppressed, consent left as it was
    for contact_id in opted_in:
        _withdraw(contact_id, provider)
        current = _marketing_channels(contact_id)
        set_preference("contact", contact_id, "marketing", sorted(current - {"email"}))
    if opted_in:
        logger.info("comms.marketing_opt_out", provider=provider, kind=kind, contacts=len(opted_in))
    return len(opted_in)


def _marketing_channels(contact_id: str) -> set[str]:
    from .models import CommunicationPreference

    row = CommunicationPreference.objects.filter(
        person_type="contact", person_id=contact_id, category="marketing"
    ).first()
    if row is not None:
        return set(row.channels)
    return set(Channel.values) - {Channel.WHATSAPP}


def _withdraw(contact_id: str, provider: str) -> None:
    from tutortrack.privacy import services as privacy
    from tutortrack.privacy.models import ConsentType

    for key in ConsentType.objects.filter(category="marketing_email", is_active=True).values_list(
        "key", flat=True
    ):
        if privacy.is_granted("people.contact", contact_id, key):
            privacy.withdraw_consent(
                subject_type="people.contact",
                subject_id=contact_id,
                key=key,
                method="import",
                source=f"{provider}:unsubscribe",
            )


def reconcile(connection: Any) -> int:
    """Before a full sync: apply everyone who left the audience at the provider."""
    from tutortrack.integrations import services as integrations

    from .marketing_providers import client_for

    audience = str(connection.settings.get("audience_id") or "")
    if not audience:
        return 0
    rows = client_for(connection.provider).opted_out(integrations.credentials(connection), audience)
    changed = 0
    for email, status in rows:
        with transaction.atomic():
            changed += apply(
                connection.provider, email, CLEANED if status == CLEANED else UNSUBSCRIBED
            )
    return changed
