"""One-off messages to chosen people (E05 bulk "send message", FR-05-12).

The same rules as a broadcast apply, person by person: no address → skipped; suppressed
addresses (bounces, complaints, STOP) → not sent; **marketing** needs consent (E29, or the
contact's "receives marketing" flag without a consent type) and the person's marketing
preference must allow the channel. Service messages go to everyone with an address. The
message uses the broadcast message types, so delivery tracking and unsubscribe links work
as for any broadcast."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

from . import render
from .models import Channel, Message
from .registry import Recipient
from .segments import SegmentMember

CHANNELS = (Channel.EMAIL, Channel.SMS)
PURPOSES = ("service", "marketing")


def clean(params: dict[str, Any]) -> dict[str, str]:
    """Validate the message of a bulk send (raises with field errors)."""
    channel = str(params.get("channel") or Channel.EMAIL)
    purpose = str(params.get("purpose") or "service")
    subject = str(params.get("subject") or "").strip()
    body = str(params.get("body") or "").strip()
    errors: dict[str, list[str]] = {}
    if channel not in CHANNELS:
        errors["channel"] = [_("Send by email or text message.")]
    if purpose not in PURPOSES:
        errors["purpose"] = [_("Choose service or marketing.")]
    if channel == Channel.EMAIL and not subject:
        errors["subject"] = [_("Add a subject.")]
    if not body:
        errors["body"] = [_("Write the message.")]
    for name, value in (("subject", subject), ("body", body)):
        try:
            render.validate(value)
        except render.TemplateInvalid as exc:
            errors.setdefault(name, []).append(str(exc))
    if errors:
        first = next(iter(errors.values()))[0]
        raise BusinessRuleViolation(first, extra={"errors": errors})
    return {"channel": channel, "purpose": purpose, "subject": subject, "body": body}


def members_for(entity_type: str, record_id: str) -> list[SegmentMember]:
    """Who a message "to this record" reaches: a contact or tutor themselves; for a client,
    its primary (else billing, else first) contact; for a student, their family's."""
    from tutortrack.people.models import Client, Contact, Student, TutorProfile

    contact = None
    if entity_type == "people.contact":
        contact = Contact.objects.filter(pk=record_id, archived_at__isnull=True).first()
    elif entity_type in {"people.client", "people.student"}:
        client = (
            Client.objects.filter(pk=record_id).first()
            if entity_type == "people.client"
            else getattr(Student.objects.filter(pk=record_id).first(), "client", None)
        )
        if client is not None:
            contact = (
                client.primary_contact
                or client.billing_contact
                or client.contacts.filter(archived_at__isnull=True).first()
            )
    elif entity_type == "people.tutor":
        tutor = TutorProfile.objects.filter(pk=record_id).select_related("membership").first()
        if tutor is None:
            return []
        membership = tutor.membership
        return [
            SegmentMember(
                kind="tutor",
                id=str(tutor.pk),
                name=tutor.full_name,
                first_name=tutor.display_name or tutor.first_name,
                email=tutor.email,
                phone=tutor.phone,
                user_id=str(membership.user_id) if membership else None,
                target=("people.tutor", str(tutor.pk)),
            )
        ]
    if contact is None:
        return []
    return [
        SegmentMember(
            kind="contact",
            id=str(contact.pk),
            name=contact.full_name,
            first_name=contact.first_name,
            email=contact.email,
            phone=contact.mobile or contact.phone,
            user_id=str(contact.user_id) if contact.user_id else None,
            target=("people.client", str(contact.client_id)),
        )
    ]


def send(
    entity_type: str, record_id: str, message: dict[str, str], *, key: str
) -> tuple[int, list[str]]:
    """Queue the message for the record's person. Returns (queued, skip reasons)."""
    from tutortrack.tenancy.models import Organisation

    from .broadcasts import _address, _consented, _preferences
    from .broadcasts import _context as _recipient_context
    from .services import queue_message, suppressed

    members = members_for(entity_type, record_id)
    if not members:
        return 0, ["no_recipient"]
    channel, marketing = message["channel"], message["purpose"] == "marketing"
    from tutortrack.core.context import require_organisation_id

    country = Organisation.objects.get(pk=require_organisation_id()).country
    consented = _consented(members, channel) if marketing else set()
    prefs = _preferences(members, "marketing" if marketing else "account")
    queued, skipped = 0, []
    for member in members:
        address = _address(member, channel, country)
        chosen = prefs.get((member.kind, member.id))
        reason = ""
        if not address:
            reason = "no_address"
        elif suppressed(channel, address):
            reason = "suppressed"
        elif marketing and (member.kind, member.id) not in consented:
            reason = "no_consent"
        elif marketing and chosen is not None and channel not in chosen:
            reason = "opted_out"
        if reason:
            skipped.append(reason)
            continue
        context = _recipient_context(member.name, member.first_name)
        tz = str(context["organisation"].get("timezone") or "")
        body = render.render(message["body"], context, timezone=tz)
        if channel == Channel.SMS and marketing:
            body = f"{body}\n{_('Reply STOP to opt out')}"
        sent = queue_message(
            type_key="broadcast_marketing" if marketing else "broadcast_operational",
            channel=channel,
            recipient=Recipient(
                kind=member.kind,
                id=member.id,
                name=member.name,
                first_name=member.first_name,
                email=member.email,
                phone=member.phone,
                user_id=member.user_id,
                target=member.target,
            ),
            subject=render.render(message["subject"], context, timezone=tz),
            body=body,
            dedupe_key=f"bulk:{key}:{member.kind}:{member.id}",
            related=("crm.bulkjob", key),
            category="marketing" if marketing else "service",
        )
        if sent is not None and sent.status == Message.Status.QUEUED:
            queued += 1
        else:
            skipped.append("suppressed" if sent is not None else "duplicate")
    return queued, skipped
