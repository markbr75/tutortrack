"""Broadcasts (E13-T10) and saved segments: the service layer.

Lifecycle: ``draft`` → ``scheduled`` (``schedule``: the segment is snapshotted and
``broadcast.scheduled`` starts ``BroadcastWorkflow``) → ``sending`` (recipients resolved;
batches go out) ⇄ ``paused`` → ``sent``; ``cancelled`` at any point before the end.

Who receives it (``resolve_recipients``, once per broadcast):

* the segment's people, one row each; a repeated address is skipped (``duplicate``);
* no address for the channel → ``no_address``; suppressed (bounce, complaint, STOP) →
  ``suppressed``;
* **marketing** needs consent (E29 ``marketing_email`` for email, ``marketing_sms`` for
  texts and WhatsApp; the contact's "receives marketing" flag where the organisation
  has no such consent type) → ``no_consent``, and the person's marketing preference must
  allow the channel → ``opted_out`` (unsubscribe links turn email off there);
* WhatsApp also needs the person's opt-in (a preference naming WhatsApp) → ``no_opt_in``.

Each queued recipient becomes a ``Message`` (type ``broadcast_marketing`` or
``broadcast_operational``; related to the broadcast), so delivery, opens, clicks and
bounces come from the provider webhooks like any message. ``stats`` adds them up.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.core.workflows import signal, workflow_id
from tutortrack.tenancy.settings_service import get_setting

from . import events, render, segments
from .models import (
    Audience,
    Broadcast,
    BroadcastRecipient,
    Channel,
    CommunicationPreference,
    Message,
    Segment,
    WhatsAppTemplate,
)
from .registry import Recipient

PROCESS = "broadcast"
CHANNELS = (Channel.EMAIL, Channel.SMS, Channel.WHATSAPP)
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
CONSENT_CATEGORY: dict[str, str] = {
    Channel.EMAIL: "marketing_email",
    Channel.SMS: "marketing_sms",
    Channel.WHATSAPP: "marketing_sms",
}
EDITABLE = ("name", "channel", "purpose", "subject", "body", "audience", "definition")
OPEN = (Broadcast.Status.SCHEDULED, Broadcast.Status.SENDING, Broadcast.Status.PAUSED)
SAMPLE_CONTEXT = {"recipient": {"name": "Priya Patel", "first_name": "Priya"}}


def broadcast_workflow_id(org: object, broadcast_id: object) -> str:
    return workflow_id(PROCESS, org, broadcast_id)


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def type_key(broadcast: Broadcast) -> str:
    if broadcast.purpose == Broadcast.Purpose.MARKETING:
        return "broadcast_marketing"
    return "broadcast_operational"


# --- segments -----------------------------------------------------------------------------------


@transaction.atomic
def save_segment(
    segment: Segment | None = None,
    *,
    name: str,
    audience: str,
    definition: dict[str, Any],
    description: str = "",
    user: Any = None,
) -> Segment:
    definition = segments.clean(audience, definition)
    name = name.strip()
    if not name:
        raise _invalid("name", _("Give the segment a name."))
    clash = Segment.objects.filter(name=name)
    if segment is not None:
        clash = clash.exclude(pk=segment.pk)
    if clash.exists():
        raise _invalid("name", _("A segment with this name already exists."))
    if segment is None:
        segment = Segment.objects.create(
            name=name,
            audience=audience,
            definition=definition,
            description=description,
            created_by=user,
        )
        audit.record_create(segment)
        return segment
    with audit.track(segment, action="update"):
        segment.name, segment.audience = name, audience
        segment.definition, segment.description = definition, description
        segment.save()
    return segment


@transaction.atomic
def delete_segment(segment: Segment) -> None:
    audit.record(segment, "delete")
    segment.delete()


# --- drafts -------------------------------------------------------------------------------------


def _check_attachments(ids: Iterable[Any]) -> list[str]:
    from tutortrack.core.models import StoredFile

    wanted = [str(i) for i in ids]
    files = list(StoredFile.objects.filter(pk__in=wanted))
    if len(files) != len(set(wanted)):
        raise _invalid("attachment_ids", _("An attachment couldn't be found."))
    if sum(f.size_bytes for f in files) > MAX_ATTACHMENT_BYTES:
        raise _invalid("attachment_ids", _("Attachments can add up to 10 MB."))
    return [str(f.pk) for f in files]


def _validate(broadcast: Broadcast) -> None:
    if broadcast.channel not in CHANNELS:
        raise _invalid("channel", _("Broadcasts go by email, text or WhatsApp."))
    for name, source in (("subject", broadcast.subject), ("body", broadcast.body)):
        try:
            render.validate(source)
        except render.TemplateInvalid as exc:
            raise _invalid(name, _("The template has an error: %(e)s") % {"e": exc}) from exc
    if broadcast.attachment_ids and broadcast.channel != Channel.EMAIL:
        raise _invalid("attachment_ids", _("Only emails can have attachments."))
    if broadcast.whatsapp_template_id and broadcast.channel != Channel.WHATSAPP:
        broadcast.whatsapp_template = None


@transaction.atomic
def create_broadcast(*, user: Any = None, **values: Any) -> Broadcast:
    values = dict(values)
    if "attachment_ids" in values:
        values["attachment_ids"] = _check_attachments(values["attachment_ids"])
    segment = values.get("segment")
    if segment is not None and not values.get("definition"):
        values["audience"], values["definition"] = segment.audience, dict(segment.definition)
    values["definition"] = segments.clean(
        values.get("audience", Audience.CONTACTS), values.get("definition") or {}
    )
    broadcast = Broadcast(created_by=user, **values)
    _validate(broadcast)
    broadcast.save()
    audit.record_create(broadcast)
    _attach_files(broadcast)
    return broadcast


@transaction.atomic
def update_broadcast(broadcast: Broadcast, **values: Any) -> Broadcast:
    broadcast = Broadcast.objects.select_for_update().get(pk=broadcast.pk)
    if broadcast.status != Broadcast.Status.DRAFT:
        raise BusinessRuleViolation(_("Only drafts can be changed."))
    if "attachment_ids" in values:
        values["attachment_ids"] = _check_attachments(values["attachment_ids"])
    with audit.track(broadcast, action="update"):
        for name, value in values.items():
            setattr(broadcast, name, value)
        if "segment" in values and values["segment"] is not None and "definition" not in values:
            broadcast.audience = values["segment"].audience
            broadcast.definition = dict(values["segment"].definition)
        broadcast.definition = segments.clean(broadcast.audience, broadcast.definition)
        _validate(broadcast)
        broadcast.save()
    _attach_files(broadcast)
    return broadcast


def _attach_files(broadcast: Broadcast) -> None:
    from tutortrack.core.models import StoredFile
    from tutortrack.core.storage.services import attach

    for stored in StoredFile.objects.filter(pk__in=broadcast.attachment_ids or []):
        if stored.owner_object_id != str(broadcast.pk):
            attach(stored, broadcast)


@transaction.atomic
def delete_broadcast(broadcast: Broadcast) -> None:
    if broadcast.status != Broadcast.Status.DRAFT:
        raise BusinessRuleViolation(_("Only drafts can be deleted; cancel it instead."))
    audit.record(broadcast, "delete")
    broadcast.delete()


# --- content ------------------------------------------------------------------------------------


def _context(name: str, first_name: str) -> dict[str, Any]:
    from .catalogue import organisation

    return {"organisation": organisation(), "recipient": {"name": name, "first_name": first_name}}


def render_for(broadcast: Broadcast, name: str, first_name: str) -> tuple[str, str, dict[str, Any]]:
    """Subject, body and channel extras for one recipient."""
    context = _context(name, first_name)
    if broadcast.channel == Channel.WHATSAPP and broadcast.whatsapp_template_id:
        from .senders import render_whatsapp

        rendered = render_whatsapp(broadcast.whatsapp_template, context)  # type: ignore[arg-type]
        return "", rendered.body, rendered.meta
    tz = str(context["organisation"].get("timezone") or "")
    subject = render.render(broadcast.subject, context, timezone=tz)
    body = render.render(broadcast.body, context, timezone=tz)
    if broadcast.channel == Channel.SMS and broadcast.purpose == Broadcast.Purpose.MARKETING:
        body = f"{body}\n{_('Reply STOP to opt out')}"
    return subject, body, {}


def preview(broadcast: Broadcast) -> dict[str, Any]:
    try:
        subject, body, _meta = render_for(broadcast, "Priya Patel", "Priya")
    except render.TemplateInvalid as exc:
        raise _invalid("body", _("The template has an error: %(e)s") % {"e": exc}) from exc
    return {
        "subject": subject,
        "body": body,
        "segments": render.sms_segments(body) if broadcast.channel == Channel.SMS else 0,
    }


# --- recipients ---------------------------------------------------------------------------------


def _address(member: segments.SegmentMember, channel: str, country: str) -> str:
    from .channels import normalise_phone

    if channel == Channel.EMAIL:
        return member.email.strip().lower()
    return normalise_phone(member.phone, country) if member.phone else ""


def _consented(members: list[segments.SegmentMember], channel: str) -> set[tuple[str, str]]:
    """Members with marketing consent for ``channel`` (E29), checked in bulk."""
    from tutortrack.people.models import Contact
    from tutortrack.privacy.models import ConsentRecord, ConsentType

    category = CONSENT_CATEGORY[channel]
    types = {t.pk: t.version for t in ConsentType.objects.filter(category=category, is_active=True)}
    subjects: dict[tuple[str, str], tuple[str, str]] = {}  # (subject type, id) -> member key
    for m in members:
        if m.kind == "contact":
            subjects[("people.contact", m.id)] = (m.kind, m.id)
        elif m.user_id:
            subjects[("identity.user", m.user_id)] = (m.kind, m.id)
    out: set[tuple[str, str]] = set()
    if types:
        latest: dict[tuple[str, str, Any], Any] = {}
        ids = [s[1] for s in subjects]
        for start in range(0, len(ids), 1000):
            rows = ConsentRecord.objects.filter(
                consent_type_id__in=list(types),
                subject_id__in=ids[start : start + 1000],
                subject_type__in=["people.contact", "identity.user"],
            ).order_by("subject_type", "subject_id", "consent_type_id", "-recorded_at", "-id")
            for record in rows:
                latest.setdefault(
                    (record.subject_type, record.subject_id, record.consent_type_id), record
                )
        for (subject_type, subject_id, type_id), record in latest.items():
            if record.granted and record.version >= types[type_id]:
                member = subjects.get((subject_type, subject_id))
                if member:
                    out.add(member)
        return out
    # No consent type for this category: fall back to the contact's marketing flag.
    flagged = set(
        Contact.objects.filter(
            pk__in=[m.id for m in members if m.kind == "contact"], receives_marketing=True
        ).values_list("pk", flat=True)
    )
    return {("contact", str(pk)) for pk in flagged}


def _preferences(
    members: list[segments.SegmentMember], category: str
) -> dict[tuple[str, str], set[str]]:
    keys = {(m.kind, m.id) for m in members}
    out: dict[tuple[str, str], set[str]] = {}
    ids = [m.id for m in members]
    for start in range(0, len(ids), 1000):
        for row in CommunicationPreference.objects.filter(
            category=category, person_id__in=ids[start : start + 1000]
        ):
            if (row.person_type, row.person_id) in keys:
                out[(row.person_type, row.person_id)] = set(row.channels)
    return out


def evaluate(
    audience: str, definition: dict[str, Any], channel: str, purpose: str
) -> list[tuple[segments.SegmentMember, str, str]]:
    """``(member, address, skip reason or "")`` for everyone in the segment."""
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    from .services import suppressed

    members = segments.resolve(audience, definition)
    country = Organisation.objects.get(pk=require_organisation_id()).country
    marketing = purpose == Broadcast.Purpose.MARKETING
    consented = _consented(members, channel) if marketing else set()
    prefs = _preferences(members, "marketing" if marketing else "account")
    seen: set[str] = set()
    out = []
    for member in members:
        key = (member.kind, member.id)
        address = _address(member, channel, country)
        chosen = prefs.get(key)  # None: no preference recorded
        reason = ""
        if not address:
            reason = "no_address"
        elif address in seen:
            reason = "duplicate"
        elif suppressed(channel, address):
            reason = "suppressed"
        elif marketing and key not in consented:
            reason = "no_consent"
        elif channel == Channel.WHATSAPP and (chosen is None or channel not in chosen):
            reason = "no_opt_in"
        elif marketing and chosen is not None and channel not in chosen:
            reason = "opted_out"
        if address and not reason:
            seen.add(address)
        out.append((member, address, reason))
    return out


def preview_recipients(
    *, audience: str, definition: dict[str, Any], channel: str, purpose: str
) -> dict[str, Any]:
    """How many a broadcast would reach now, why others are skipped, and a sample."""
    rows = evaluate(audience, definition, channel, purpose)
    skipped = Counter(reason for _m, _a, reason in rows if reason)
    sendable = [(m, a) for m, a, reason in rows if not reason]
    return {
        "total": len(rows),
        "sendable": len(sendable),
        "skipped": dict(sorted(skipped.items())),
        "sample": [{"name": m.name, "address": a, "kind": m.kind} for m, a in sendable[:10]],
    }


# --- sending (driven by BroadcastWorkflow) ------------------------------------------------------


@transaction.atomic
def schedule(
    broadcast: Broadcast, *, scheduled_for: datetime | None, user: Any = None
) -> Broadcast:
    """Send now or at ``scheduled_for``: starts ``BroadcastWorkflow`` via
    ``broadcast.scheduled``."""
    broadcast = Broadcast.objects.select_for_update().get(pk=broadcast.pk)
    if broadcast.status != Broadcast.Status.DRAFT:
        raise BusinessRuleViolation(_("This broadcast has already been scheduled."))
    if broadcast.channel == Channel.EMAIL and not broadcast.subject.strip():
        raise _invalid("subject", _("Write a subject."))
    if broadcast.channel == Channel.WHATSAPP:
        template = broadcast.whatsapp_template
        if template is None or template.status != WhatsAppTemplate.Status.APPROVED:
            raise _invalid("whatsapp_template", _("WhatsApp broadcasts need an approved template."))
    elif not broadcast.body.strip():
        raise _invalid("body", _("Write the message."))
    if scheduled_for is not None and scheduled_for <= now():
        scheduled_for = None
    preview(broadcast)  # renders, or explains the template error
    with audit.track(broadcast, action="schedule"):
        if broadcast.segment_id and not broadcast.definition:
            broadcast.definition = dict(broadcast.segment.definition)  # type: ignore[union-attr]
        broadcast.status = Broadcast.Status.SCHEDULED
        broadcast.scheduled_for = scheduled_for
        broadcast.sent_by = user
        broadcast.save()
    publish(
        events.BroadcastScheduled(
            subject_id=broadcast.pk,
            channel=broadcast.channel,
            purpose=broadcast.purpose,
            scheduled_for=scheduled_for.isoformat() if scheduled_for else None,
        )
    )
    return broadcast


def _transition(
    broadcast: Broadcast, allowed: tuple[str, ...], status: str, action: str
) -> Broadcast:
    broadcast = Broadcast.objects.select_for_update().get(pk=broadcast.pk)
    if broadcast.status not in allowed:
        raise BusinessRuleViolation(_("You can't do that to this broadcast now."))
    with audit.track(broadcast, action=action):
        broadcast.status = status
        if status == Broadcast.Status.CANCELLED:
            broadcast.cancelled_at = now()
        broadcast.save()
    return broadcast


@transaction.atomic
def pause(broadcast: Broadcast) -> Broadcast:
    broadcast = _transition(
        broadcast,
        (Broadcast.Status.SCHEDULED, Broadcast.Status.SENDING),
        Broadcast.Status.PAUSED,
        "pause",
    )
    signal(broadcast_workflow_id(broadcast.organisation_id, broadcast.pk), "pause")
    return broadcast


@transaction.atomic
def resume(broadcast: Broadcast) -> Broadcast:
    target = Broadcast.Status.SENDING if broadcast.started_at else Broadcast.Status.SCHEDULED
    broadcast = _transition(broadcast, (Broadcast.Status.PAUSED,), target, "resume")
    signal(broadcast_workflow_id(broadcast.organisation_id, broadcast.pk), "resume")
    return broadcast


@transaction.atomic
def cancel(broadcast: Broadcast) -> Broadcast:
    broadcast = _transition(broadcast, OPEN, Broadcast.Status.CANCELLED, "cancel")
    BroadcastRecipient.objects.filter(
        broadcast=broadcast, status=BroadcastRecipient.Status.PENDING
    ).update(status=BroadcastRecipient.Status.SKIPPED, skip_reason="cancelled")
    publish(
        events.BroadcastCancelled(
            subject_id=broadcast.pk, channel=broadcast.channel, purpose=broadcast.purpose
        )
    )
    signal(broadcast_workflow_id(broadcast.organisation_id, broadcast.pk), "cancel")
    return broadcast


def state(broadcast_id: str) -> dict[str, Any]:
    """What the workflow needs to know (read once per step)."""
    broadcast = Broadcast.objects.filter(pk=broadcast_id).first()
    if broadcast is None:
        return {"status": "missing", "scheduled_for": "", "channel": ""}
    return {
        "status": broadcast.status,
        "scheduled_for": broadcast.scheduled_for.isoformat() if broadcast.scheduled_for else "",
        "channel": broadcast.channel,
        "batch_size": int(get_setting("comms.broadcast_batch_size")),
        "pause_seconds": int(get_setting("comms.broadcast_batch_pause_seconds")),
    }


@transaction.atomic
def resolve_recipients(broadcast_id: str) -> int:
    """Snapshot the segment into recipients (once) and start sending. Returns how many
    are waiting to be sent."""
    broadcast = Broadcast.objects.select_for_update().get(pk=broadcast_id)
    if broadcast.status in (Broadcast.Status.CANCELLED, Broadcast.Status.SENT):
        return 0
    if not broadcast.recipients.exists():
        rows = evaluate(
            broadcast.audience, broadcast.definition, broadcast.channel, broadcast.purpose
        )
        BroadcastRecipient.objects.bulk_create(
            [
                BroadcastRecipient(
                    broadcast=broadcast,
                    recipient_type=m.kind,
                    recipient_id=m.id,
                    name=m.name[:200],
                    address=address[:254],
                    status=(
                        BroadcastRecipient.Status.SKIPPED
                        if reason
                        else BroadcastRecipient.Status.PENDING
                    ),
                    skip_reason=reason,
                    organisation_id=broadcast.organisation_id,
                )
                for m, address, reason in rows
            ],
            ignore_conflicts=True,
        )
    if broadcast.status == Broadcast.Status.SCHEDULED:
        with audit.track(broadcast, action="start"):
            broadcast.status = Broadcast.Status.SENDING
            broadcast.started_at = broadcast.started_at or now()
            broadcast.save()
    return broadcast.recipients.filter(status=BroadcastRecipient.Status.PENDING).count()


def _recipient(row: BroadcastRecipient) -> Recipient:
    from tutortrack.people.models import Contact, TutorProfile

    first_name, user_id, target = row.name.split(" ")[0] if row.name else "", None, ("", "")
    if row.recipient_type == "contact":
        contact = Contact.objects.filter(pk=row.recipient_id).first()
        if contact is not None:
            first_name = contact.first_name
            target = ("people.client", str(contact.client_id))
    elif row.recipient_type == "tutor":
        tutor = TutorProfile.objects.filter(pk=row.recipient_id).first()
        if tutor is not None:
            first_name = tutor.display_name or tutor.first_name
            target = ("people.tutor", str(tutor.pk))
    return Recipient(
        kind=row.recipient_type,
        id=row.recipient_id,
        name=row.name,
        first_name=first_name,
        email=row.address if "@" in row.address else "",
        phone=row.address if "@" not in row.address else "",
        user_id=user_id,
        target=target,
    )


def send_batch(broadcast_id: str, batch: int) -> dict[str, int]:
    """Queue the next batch (each message is sent by the Celery send task after commit)."""
    with transaction.atomic():
        broadcast = Broadcast.objects.select_for_update().get(pk=broadcast_id)
        if broadcast.status != Broadcast.Status.SENDING:
            pending = broadcast.recipients.filter(status=BroadcastRecipient.Status.PENDING)
            return {"queued": 0, "remaining": pending.count(), "status": 0}
        size = int(get_setting("comms.broadcast_batch_size"))
        rows = list(
            broadcast.recipients.select_for_update(skip_locked=True)
            .filter(status=BroadcastRecipient.Status.PENDING)
            .order_by("id")[:size]
        )
        queued = 0
        kind = type_key(broadcast)
        for row in rows:
            recipient = _recipient(row)
            dedupe = f"broadcast:{broadcast.pk}:{row.recipient_type}:{row.recipient_id}"
            try:
                subject, body, meta = render_for(broadcast, recipient.name, recipient.first_name)
            except render.TemplateInvalid as exc:
                row.status, row.skip_reason = BroadcastRecipient.Status.FAILED, "template"
                row.save(update_fields=["status", "skip_reason", "updated_at"])
                audit.record(broadcast, "template_error", {"error": str(exc)[:200]})
                continue
            from .services import queue_message

            message = queue_message(
                type_key=kind,
                channel=broadcast.channel,
                recipient=recipient,
                subject=subject,
                body=body,
                dedupe_key=dedupe,
                related=("comms.broadcast", str(broadcast.pk)),
                meta=meta,
            )
            if message is None:
                message = Message.objects.filter(dedupe_key=dedupe).first()
            if message is None:
                row.status, row.skip_reason = BroadcastRecipient.Status.SKIPPED, "no_address"
            elif message.status == Message.Status.SUPPRESSED:
                row.status, row.skip_reason = BroadcastRecipient.Status.SKIPPED, "suppressed"
            else:
                row.status = BroadcastRecipient.Status.QUEUED
                queued += 1
            row.message, row.batch = message, batch
            row.save(update_fields=["status", "skip_reason", "message", "batch", "updated_at"])
        remaining = broadcast.recipients.filter(status=BroadcastRecipient.Status.PENDING).count()
    return {"queued": queued, "remaining": remaining, "status": 1}


def stats(broadcast: Broadcast) -> dict[str, int]:
    """Counts from the recipients and their messages' delivery tracking (live)."""
    recipients = Counter(
        broadcast.recipients.values_list("status", flat=True) if broadcast.pk else []
    )
    statuses = Counter(
        Message.objects.filter(
            related_type="comms.broadcast", related_id=str(broadcast.pk)
        ).values_list("status", flat=True)
    )
    from .models import MessageEvent

    unsubscribed = MessageEvent.objects.filter(
        message__related_type="comms.broadcast",
        message__related_id=str(broadcast.pk),
        type="unsubscribed",
    ).count()
    sent_states = ("sent", "delivered", "opened", "clicked")
    return {
        "recipients": sum(recipients.values()),
        "pending": recipients.get("pending", 0),
        "queued": recipients.get("queued", 0),
        "skipped": recipients.get("skipped", 0),
        "sent": sum(statuses.get(s, 0) for s in sent_states),
        "delivered": sum(statuses.get(s, 0) for s in ("delivered", "opened", "clicked")),
        "opened": sum(statuses.get(s, 0) for s in ("opened", "clicked")),
        "clicked": statuses.get("clicked", 0),
        "bounced": statuses.get("bounced", 0) + statuses.get("complained", 0),
        "failed": statuses.get("failed", 0) + recipients.get("failed", 0),
        "unsubscribed": unsubscribed,
    }


@transaction.atomic
def finish(broadcast_id: str) -> str:
    broadcast = Broadcast.objects.select_for_update().get(pk=broadcast_id)
    if broadcast.status == Broadcast.Status.CANCELLED:
        return "cancelled"
    if broadcast.status == Broadcast.Status.SENT:
        return "sent"
    numbers = stats(broadcast)
    with audit.track(broadcast, action="finish"):
        broadcast.status = Broadcast.Status.SENT
        broadcast.finished_at = now()
        broadcast.stats = numbers
        broadcast.save()
    publish(
        events.BroadcastSent(
            subject_id=broadcast.pk,
            channel=broadcast.channel,
            purpose=broadcast.purpose,
            recipients=numbers["recipients"],
            queued=numbers["queued"],
            skipped=numbers["skipped"],
        )
    )
    return "sent"


def quiet_wait_seconds(broadcast_id: str, *, at: datetime | None = None) -> int:
    """Texts and WhatsApp messages wait for the end of quiet hours (FR-13-4). ``at`` is
    the workflow's clock."""
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    from .services import _quiet_until

    broadcast = Broadcast.objects.filter(pk=broadcast_id).first()
    if broadcast is None or broadcast.channel == Channel.EMAIL:
        return 0
    moment = at or now()
    tz = Organisation.objects.get(pk=require_organisation_id()).timezone
    until = _quiet_until(moment, tz)
    return max(0, int((until - moment).total_seconds())) if until else 0
