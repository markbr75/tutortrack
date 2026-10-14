"""Senders and channel set-up (E13-T12): custom sending domains, the organisation's own
numbers, WhatsApp templates, reply addresses and the platform-level inbound routes.

Writes here are services (audited, events published inside the transaction).

* **Reply addresses:** with ``COMMS["REPLY_DOMAIN"]`` set, a thread's emails carry
  ``reply+<subdomain>.<thread>.<signature>@<domain>`` as Reply-To, and other emails
  (without an explicit ``comms.reply_to``) ``inbox+<subdomain>@<domain>``. The signature
  is an HMAC, so nobody can post into a thread by guessing its id.
* **Numbers:** texts and WhatsApp messages go from the organisation's default number, or
  the platform's shared sender. Replies find the organisation through ``InboundRoute``:
  its own number, or the organisation that last messaged that phone from the shared
  sender (within ``COMMS["SMS_REPLY_ROUTE_DAYS"]``).
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit, entitlements
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import events, render
from .channels import ChannelError
from .models import Channel, InboundRoute, PhoneNumber, SenderDomain, WhatsAppTemplate


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def _organisation() -> Any:
    from tutortrack.tenancy.models import Organisation

    return Organisation.objects.get(pk=require_organisation_id())


# --- reply addresses ----------------------------------------------------------------------------


def reply_domain() -> str:
    return str(settings.COMMS["REPLY_DOMAIN"] or "")


def _signature(slug: str, thread_hex: str) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode(), f"thread-reply:{slug}:{thread_hex}".encode(), hashlib.sha256
    ).hexdigest()
    return digest[:12]


def thread_reply_address(thread: Any) -> str:
    domain = reply_domain()
    if not domain:
        return ""
    slug = _organisation().slug
    thread_hex = thread.pk.hex
    return f"reply+{slug}.{thread_hex}.{_signature(slug, thread_hex)}@{domain}"


def inbox_address() -> str:
    domain = reply_domain()
    return f"inbox+{_organisation().slug}@{domain}" if domain else ""


@dataclass(frozen=True)
class MailboxRoute:
    slug: str
    thread_hex: str = ""  # empty: a new conversation to the organisation's inbox


def parse_mailbox_hash(value: str) -> MailboxRoute | None:
    """``<slug>`` or ``<slug>.<thread hex>.<signature>`` (the part after ``+``)."""
    value = value.strip().lower()
    parts = value.split(".")
    if len(parts) == 1 and re.fullmatch(r"[a-z0-9-]{1,63}", value):
        return MailboxRoute(value)
    if len(parts) == 3 and re.fullmatch(r"[0-9a-f]{32}", parts[1]):
        slug, thread_hex, signature = parts
        if hmac.compare_digest(_signature(slug, thread_hex), signature):
            return MailboxRoute(slug, thread_hex)
    return None


def reply_to_for(message: Any) -> str:
    """Reply-To for an outgoing email: the thread's address, else the organisation's
    choice, else its inbox address (when inbound email is set up), else none."""
    if getattr(message, "thread_id", None) and reply_domain():
        return thread_reply_address(message.thread)
    explicit = str(get_setting("comms.reply_to") or "")
    return explicit or inbox_address()


# --- custom sending domains ---------------------------------------------------------------------

DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
LOCAL_RE = re.compile(r"^[a-z0-9]([a-z0-9._-]{0,62}[a-z0-9])?$")


def from_address() -> str:
    """The verified default sending address, if the organisation has one."""
    row = SenderDomain.objects.filter(status=SenderDomain.Status.VERIFIED, is_default=True).first()
    return row.from_address if row is not None else ""


def _clean_domain(domain: str) -> str:
    domain = domain.strip().lower().rstrip(".")
    if not DOMAIN_RE.match(domain):
        raise _invalid("domain", _("Enter a domain like brightminds.co.uk."))
    platform = {settings.TENANT_BASE_DOMAIN.lower(), reply_domain().lower()} - {""}
    if any(domain == p or domain.endswith("." + p) for p in platform):
        raise _invalid("domain", _("Use your own domain."))
    return domain


def _clean_local(local_part: str) -> str:
    local_part = local_part.strip().lower()
    if not LOCAL_RE.match(local_part):
        raise _invalid("local_part", _("Enter the part before the @, e.g. hello."))
    return local_part


@transaction.atomic
def add_sender_domain(*, domain: str, local_part: str = "hello") -> SenderDomain:
    from . import providers

    entitlements.require("custom_domain")
    domain = _clean_domain(domain)
    local_part = _clean_local(local_part)
    if SenderDomain.objects.filter(domain=domain).exists():
        raise _invalid("domain", _("You've already added this domain."))
    try:
        state = providers.sender_domain_provider().create(domain)
    except ChannelError as exc:
        raise _invalid("domain", str(exc)) from exc
    row = SenderDomain.objects.create(
        domain=domain,
        local_part=local_part,
        provider_ref=state.ref,
        dns_records=[r.as_dict() for r in [*state.records, *providers.advisory_records(domain)]],
        is_default=not SenderDomain.objects.exists(),
    )
    audit.record_create(row)
    return row


@transaction.atomic
def check_sender_domain(row: SenderDomain) -> SenderDomain:
    """Ask the provider to check the DNS records now (the wizard's "Check" button)."""
    from . import providers

    row = SenderDomain.objects.select_for_update().get(pk=row.pk)
    was_verified = row.status == SenderDomain.Status.VERIFIED
    with audit.track(row, action="check"):
        try:
            state = providers.sender_domain_provider().verify(row.provider_ref, row.domain)
        except ChannelError as exc:
            row.error = str(exc)[:300]
        else:
            advisory = [r for r in row.dns_records if r.get("purpose") in {"spf", "dmarc"}]
            row.dns_records = [*(r.as_dict() for r in state.records), *advisory]
            row.status = (
                SenderDomain.Status.VERIFIED if state.verified else SenderDomain.Status.FAILED
            )
            row.error = "" if state.verified else _("The DNS records aren't showing yet.")
            if state.verified and not was_verified:
                row.verified_at = now()
        row.last_checked_at = now()
        row.save()
    if row.status == SenderDomain.Status.VERIFIED and not was_verified:
        publish(events.SenderDomainVerified(subject_id=row.pk, domain=row.domain))
    return row


@transaction.atomic
def update_sender_domain(
    row: SenderDomain, *, local_part: str | None = None, is_default: bool | None = None
) -> SenderDomain:
    with audit.track(row, action="update"):
        if local_part is not None:
            row.local_part = _clean_local(local_part)
        if is_default:
            if row.status != SenderDomain.Status.VERIFIED:
                raise _invalid("is_default", _("Verify the domain before sending from it."))
            SenderDomain.objects.exclude(pk=row.pk).update(is_default=False)
            row.is_default = True
        elif is_default is False:
            row.is_default = False
        row.save()
    return row


@transaction.atomic
def remove_sender_domain(row: SenderDomain) -> None:
    from . import providers

    with contextlib.suppress(ChannelError):  # best effort: it stays unused at the provider
        providers.sender_domain_provider().delete(row.provider_ref)
    audit.record(row, "delete")
    row.delete()


# --- numbers and inbound routes -----------------------------------------------------------------

E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def sender_number(channel: str) -> str:
    """The organisation's number for ``channel`` (default first), or "" (shared sender)."""
    row = (
        PhoneNumber.objects.filter(channel=channel, active=True)
        .order_by("-is_default", "created_at")
        .first()
    )
    return row.number if row is not None else ""


@transaction.atomic
def add_phone_number(
    *, channel: str, number: str, label: str = "", branch: Any = None, is_default: bool = False
) -> PhoneNumber:
    if channel not in {Channel.SMS, Channel.WHATSAPP}:
        raise _invalid("channel", _("Numbers are for text messages or WhatsApp."))
    number = "".join(c for c in number if c.isdigit() or c == "+")
    if not E164.match(number):
        raise _invalid("number", _("Enter the number in international format, e.g. +447700900123."))
    taken = InboundRoute.objects.filter(
        channel=channel, kind=InboundRoute.Kind.NUMBER, address=number
    ).first()
    if taken is not None:
        raise _invalid("number", _("This number is already in use."))
    if is_default or not PhoneNumber.objects.filter(channel=channel).exists():
        PhoneNumber.objects.filter(channel=channel).update(is_default=False)
        is_default = True
    row = PhoneNumber.objects.create(
        channel=channel, number=number, label=label[:100], branch=branch, is_default=is_default
    )
    InboundRoute.objects.create(
        channel=channel,
        kind=InboundRoute.Kind.NUMBER,
        address=number,
        organisation_id=require_organisation_id(),
    )
    audit.record_create(row)
    return row


@transaction.atomic
def remove_phone_number(row: PhoneNumber) -> None:
    InboundRoute.objects.filter(
        channel=row.channel,
        kind=InboundRoute.Kind.NUMBER,
        address=row.number,
        organisation_id=row.organisation_id,
    ).delete()
    audit.record(row, "delete")
    row.delete()


def remember_reply_route(channel: str, phone: str) -> None:
    """We messaged ``phone`` from the shared sender: its replies come to us."""
    InboundRoute.objects.update_or_create(
        channel=channel,
        kind=InboundRoute.Kind.REPLY,
        address=phone,
        defaults={"organisation_id": require_organisation_id()},
    )


def route_inbound(channel: str, *, to: str, sender: str) -> Any:
    """The organisation an inbound text/WhatsApp message belongs to (platform-level)."""
    own = InboundRoute.objects.filter(
        channel=channel, kind=InboundRoute.Kind.NUMBER, address=to
    ).first()
    if own is not None:
        return own.organisation_id
    since = now() - timedelta(days=int(settings.COMMS["SMS_REPLY_ROUTE_DAYS"]))
    reply = InboundRoute.objects.filter(
        channel=channel, kind=InboundRoute.Kind.REPLY, address=sender, updated_at__gte=since
    ).first()
    return reply.organisation_id if reply is not None else None


# --- WhatsApp templates -------------------------------------------------------------------------

PLACEHOLDER = re.compile(r"\{\{\s*(\d+)\s*\}\}")


@dataclass(frozen=True)
class RenderedWhatsApp:
    body: str  # the template with its values (for the message log)
    meta: dict[str, Any]


def _check_template(body: str, variables: list[str]) -> None:
    numbers = sorted({int(n) for n in PLACEHOLDER.findall(body)})
    if numbers != list(range(1, len(numbers) + 1)):
        raise _invalid("body", _("Number the placeholders {{1}}, {{2}}... without gaps."))
    if len(variables) != len(numbers):
        raise _invalid("variables", _("Give one value for each placeholder."))
    for source in variables:
        try:
            render.validate(source)
        except render.TemplateInvalid as exc:
            raise _invalid("variables", _("The template has an error: %(e)s") % {"e": exc}) from exc


@transaction.atomic
def save_whatsapp_template(row: WhatsAppTemplate | None = None, **values: Any) -> WhatsAppTemplate:
    current = row or WhatsAppTemplate()
    body = str(values.get("body", current.body))
    variables = list(values.get("variables", current.variables or []))
    _check_template(body, variables)
    type_key = str(values.get("type_key", current.type_key) or "")
    if type_key:
        from . import registry

        try:
            registry.get(type_key)
        except KeyError:
            raise _invalid("type_key", _("Unknown notification.")) from None
    with audit.track(current, action="update" if row else "create"):
        for name, value in values.items():
            setattr(current, name, value)
        current.save()
    if row is None:
        audit.record_create(current)
    return current


def render_whatsapp(template: WhatsAppTemplate, context: dict[str, Any]) -> RenderedWhatsApp:
    tz = str((context.get("organisation") or {}).get("timezone") or "")
    values: dict[str, str] = {}
    for index, source in enumerate(template.variables or [], start=1):
        try:
            values[str(index)] = render.render(str(source), context, timezone=tz)[:1000]
        except render.TemplateInvalid:
            values[str(index)] = ""
    body = PLACEHOLDER.sub(lambda m: values.get(m.group(1), ""), template.body)
    return RenderedWhatsApp(
        body, {"content_sid": template.content_sid, "variables": values, "template": template.name}
    )


def render_whatsapp_for_type(type_key: str, context: dict[str, Any]) -> RenderedWhatsApp | None:
    template = WhatsAppTemplate.objects.filter(
        type_key=type_key, status=WhatsAppTemplate.Status.APPROVED
    ).first()
    return render_whatsapp(template, context) if template is not None else None
