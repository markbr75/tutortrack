"""Mailchimp/Brevo audience sync (E13-T12, FR-13-9): the service layer.

Contacts with marketing email consent (E29, or the "receives marketing" flag where the
organisation has no marketing consent type) and an email that isn't suppressed or
unsubscribed from marketing are upserted into the chosen audience with their family's
tags; everyone else is unsubscribed there. A consent change or contact update queues a
one-contact sync (Celery, short and stateless); "Sync now" re-sends everyone in pages.
Connecting, checking and disconnecting use the E22 integration framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core.context import require_organisation_id
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.integrations import selectors as integration_selectors
from tutortrack.integrations import services as integrations
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import AuthError, ProviderError

from .marketing_providers import PROVIDERS, Audience, Member, SyncResult, client_for

PAGE = 200


def connections() -> list[IntegrationConnection]:
    return list(
        integration_selectors.live(
            IntegrationConnection.objects.filter(user__isnull=True, provider__in=PROVIDERS)
        )
    )


def connection_for(provider: str) -> IntegrationConnection | None:
    if provider not in PROVIDERS:
        return None
    return integration_selectors.org_connection(provider)


def audiences(connection: IntegrationConnection) -> list[Audience]:
    try:
        found = client_for(connection.provider).audiences(integrations.credentials(connection))
    except ProviderError as exc:
        integrations.record_failure(connection, exc)
        raise BusinessRuleViolation(str(exc)) from exc
    integrations.record_success(connection)
    return found


def choose_audience(connection: IntegrationConnection, audience_id: str) -> IntegrationConnection:
    known = {a.id: a for a in audiences(connection)}
    if audience_id not in known:
        message = _("Choose one of the account's audiences.")
        raise BusinessRuleViolation(message, extra={"errors": {"audience_id": [message]}})
    return integrations.update_settings(
        connection, audience_id=audience_id, audience_name=known[audience_id].name
    )


# --- who is synced ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    contact_id: str
    email: str
    member: Member
    eligible: bool


def candidates(contact_ids: list[str] | None = None) -> list[Candidate]:
    from tutortrack.crm.models import Tag, TaggedItem
    from tutortrack.people.models import Contact

    from .broadcasts import _consented, _preferences
    from .models import Channel
    from .segments import SegmentMember
    from .services import suppressed

    qs = Contact.objects.filter(archived_at__isnull=True).exclude(email="")
    if contact_ids is not None:
        qs = qs.filter(pk__in=contact_ids)
    contacts = list(qs.select_related("client").order_by("pk"))
    members = [
        SegmentMember(
            "contact",
            str(c.pk),
            c.full_name,
            c.first_name,
            c.email,
            "",
            None,
            ("people.client", str(c.client_id)),
        )
        for c in contacts
    ]
    consented = _consented(members, Channel.EMAIL)
    prefs = _preferences(members, "marketing")
    client_ids = {str(c.client_id) for c in contacts}
    names = dict(Tag.objects.values_list("pk", "name"))
    tags: dict[str, set[str]] = {}
    for item in TaggedItem.objects.filter(target_type="people.client", target_id__in=client_ids):
        tags.setdefault(item.target_id, set()).add(names.get(item.tag_id, ""))
    out = []
    for c in contacts:
        key = ("contact", str(c.pk))
        chosen = prefs.get(key)
        eligible = (
            key in consented
            and (chosen is None or Channel.EMAIL in chosen)
            and not suppressed(Channel.EMAIL, c.email)
        )
        client_tags = {t for t in tags.get(str(c.client_id), set()) if t}
        client_tags.add(f"status:{c.client.status}")
        out.append(
            Candidate(
                str(c.pk),
                c.email.lower(),
                Member(c.email.lower(), c.first_name, c.last_name, tuple(sorted(client_tags))),
                eligible,
            )
        )
    return out


def _push(
    connection: IntegrationConnection, rows: list[Candidate], *, unsubscribe: bool
) -> SyncResult:
    audience_id = str(connection.settings.get("audience_id") or "")
    creds = integrations.credentials(connection)
    client = client_for(connection.provider)
    total = SyncResult()
    keep = [r.member for r in rows if r.eligible]
    if keep:
        result = client.upsert(creds, audience_id, keep)
        total.upserted += result.upserted
        total.errors += result.errors
    drop = [r.email for r in rows if not r.eligible]
    if drop and unsubscribe:
        result = client.unsubscribe(creds, audience_id, drop)
        total.unsubscribed += result.unsubscribed
        total.errors += result.errors
    return total


def sync_contact(contact_id: str) -> int:
    """One contact into every connected audience (after a consent change or edit)."""
    done = 0
    rows = candidates([contact_id])
    for connection in connections():
        if not connection.settings.get("audience_id"):
            continue
        try:
            _push(connection, rows, unsubscribe=True)
        except ProviderError as exc:
            integrations.record_failure(connection, exc)
            if not isinstance(exc, AuthError) and getattr(exc, "retryable", True):
                raise
            continue
        integrations.record_success(connection, synced=True)
        done += 1
    return done


def sync_all(connection: IntegrationConnection) -> dict[str, Any]:
    """Every contact, in pages (consented ones upserted, the rest unsubscribed)."""
    if not connection.settings.get("audience_id"):
        raise BusinessRuleViolation(_("Choose an audience first."))
    rows = candidates()
    total = SyncResult()
    try:
        for start in range(0, len(rows), PAGE):
            result = _push(connection, rows[start : start + PAGE], unsubscribe=True)
            total.upserted += result.upserted
            total.unsubscribed += result.unsubscribed
            total.errors += result.errors
    except ProviderError as exc:
        integrations.record_failure(connection, exc)
        raise BusinessRuleViolation(str(exc)) from exc
    integrations.record_success(connection, synced=True)
    return {
        "upserted": total.upserted,
        "unsubscribed": total.unsubscribed,
        "failed": len(total.errors),
    }


def queue_contact_sync(contact_id: str) -> None:
    """After commit, if an audience is connected (cheap check first)."""
    if not contact_id or not any(c.settings.get("audience_id") for c in connections()):
        return
    from .tasks import sync_marketing_contact

    org = str(require_organisation_id())
    transaction.on_commit(
        lambda: sync_marketing_contact.delay(organisation_id=org, contact_id=contact_id)
    )
