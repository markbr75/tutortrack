"""Communications writes (E13): settings, templates, the notification pipeline, sending,
preferences, suppressions and in-app notifications.

Pipeline (FR-13-4): ``notify(type, subject)`` → the organisation's setting (enabled,
channels) → recipients from the type → each channel the recipient can receive, allowed by
their preferences and not suppressed → render (override or default template) → a
``Message`` with a dedupe key (retries and redelivered events never double-send) → sent by
a task (texts deferred out of quiet hours).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit, branding
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import channels, defaults, events, hooks, registry, render
from .models import (
    Channel,
    CommunicationPreference,
    InAppNotification,
    Message,
    MessageEvent,
    MessageTemplate,
    OrgNotificationSetting,
    PushSubscription,
    SmsOptOut,
    Suppression,
)
from .registry import Delivery, NotificationType


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


# --- settings (T01) -----------------------------------------------------------------------------


@dataclass(frozen=True)
class EffectiveSetting:
    type: NotificationType
    enabled: bool
    channels: tuple[str, ...]
    timing: tuple[int, ...]
    customised: bool


def effective(type_key: str) -> EffectiveSetting:
    t = registry.get(type_key)
    row = OrgNotificationSetting.objects.filter(type_key=type_key).first()
    if row is None:
        return EffectiveSetting(t, t.default_enabled, t.default_channels, t.default_timing, False)
    return EffectiveSetting(
        t,
        row.enabled,
        tuple(c for c in row.channels if c in t.channels),
        tuple(int(m) for m in row.timing) or t.default_timing,
        True,
    )


@transaction.atomic
def update_setting(
    type_key: str, *, enabled: bool, channels: list[str], timing: list[int] | None = None
) -> EffectiveSetting:
    t = registry.get(type_key)
    unknown = set(channels) - set(t.channels)
    if unknown:
        raise _invalid(
            "channels",
            _("This notification can't be sent by %(c)s.") % {"c": ", ".join(sorted(unknown))},
        )
    if timing is not None:
        if not t.default_timing:
            raise _invalid("timing", _("This notification has no timing."))
        if not 1 <= len(timing) <= 3 or any(not 5 <= m <= 14 * 24 * 60 for m in timing):
            raise _invalid("timing", _("Choose up to 3 times between 5 minutes and 14 days."))
    row, _created = OrgNotificationSetting.objects.get_or_create(type_key=type_key)
    with audit.track(row, action="update"):
        row.enabled = enabled
        row.channels = sorted(set(channels))
        if timing is not None:
            row.timing = sorted(set(timing), reverse=True)
        row.save()
    return effective(type_key)


# --- templates (T02) ----------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateSource:
    subject: str
    body: str
    customised: bool
    version: int


def template_for(type_key: str, channel: str, locale: str = "en-GB") -> TemplateSource | None:
    row = MessageTemplate.objects.filter(type_key=type_key, channel=channel, is_active=True).first()
    if row is not None:
        return TemplateSource(row.subject, row.body, True, row.version)
    default = defaults.default_template(type_key, channel)
    if default is None:
        return None
    return TemplateSource(default[0], default[1], False, 0)


@transaction.atomic
def save_template(
    type_key: str, channel: str, *, subject: str, body: str, user: Any = None
) -> MessageTemplate:
    t = registry.get(type_key)
    if channel not in t.channels:
        raise _invalid("channel", _("This notification can't be sent by that channel."))
    for name, source in (("subject", subject), ("body", body)):
        try:
            render.validate(source)
        except render.TemplateInvalid as exc:
            raise _invalid(name, _("The template has an error: %(e)s") % {"e": exc}) from exc
    if not body.strip():
        raise _invalid("body", _("Write the message."))
    current = MessageTemplate.objects.filter(
        type_key=type_key, channel=channel, is_active=True
    ).first()
    version = 1
    if current is not None:
        version = current.version + 1
        MessageTemplate.objects.filter(pk=current.pk).update(is_active=False)
    else:
        last = MessageTemplate.objects.filter(type_key=type_key, channel=channel).first()
        version = last.version + 1 if last else 1
    row = MessageTemplate.objects.create(
        type_key=type_key, channel=channel, subject=subject, body=body, version=version,
        created_by=user,
    )  # fmt: skip
    audit.record_create(row)
    return row


@transaction.atomic
def revert_template(type_key: str, channel: str) -> None:
    """Back to the platform default (earlier versions stay for the record)."""
    MessageTemplate.objects.filter(type_key=type_key, channel=channel, is_active=True).update(
        is_active=False
    )


def render_message(
    type_key: str,
    channel: str,
    context: dict[str, Any],
    *,
    subject: str | None = None,
    body: str | None = None,
) -> tuple[str, str]:
    source = template_for(type_key, channel)
    subject_src = subject if subject is not None else (source.subject if source else "")
    body_src = body if body is not None else (source.body if source else "")
    tz = str((context.get("lesson") or {}).get("timezone") or
             (context.get("organisation") or {}).get("timezone") or "")  # fmt: skip
    return (
        render.render(subject_src, context, timezone=tz),
        render.render(body_src, context, timezone=tz),
    )


def preview(
    type_key: str, channel: str, *, subject: str | None = None, body: str | None = None
) -> tuple[str, str]:
    t = registry.get(type_key)
    try:
        return render_message(type_key, channel, dict(t.sample), subject=subject, body=body)
    except render.TemplateInvalid as exc:
        raise _invalid("body", _("The template has an error: %(e)s") % {"e": exc}) from exc


# --- preferences and suppressions (T07) ---------------------------------------------------------


def allowed_channels(recipient: registry.Recipient, category: str) -> set[str] | None:
    """Channels the person accepts for a category (None = no preference: all)."""
    row = CommunicationPreference.objects.filter(
        person_type=recipient.kind, person_id=recipient.id, category=category
    ).first()
    return None if row is None else set(row.channels)


@transaction.atomic
def set_preference(person_type: str, person_id: str, category: str, channels: list[str]) -> Any:
    if category not in registry.CATEGORIES:
        raise _invalid("category", _("Unknown category."))
    if set(channels) - set(Channel.values):
        raise _invalid("channels", _("Unknown channel."))
    row, _created = CommunicationPreference.objects.update_or_create(
        person_type=person_type,
        person_id=str(person_id),
        category=category,
        defaults={"channels": sorted(set(channels))},
    )
    return row


def suppressed(channel: str, address: str) -> bool:
    if channel == Channel.SMS and SmsOptOut.objects.filter(phone=address).exists():
        return True
    if (
        channel == Channel.WHATSAPP
        and SmsOptOut.objects.filter(phone=f"whatsapp:{address}").exists()
    ):
        return True  # STOP sent to the WhatsApp sender
    return Suppression.objects.filter(channel=channel, address=address.lower()).exists()


def suppress(channel: str, address: str, reason: str) -> None:
    Suppression.objects.get_or_create(
        channel=channel, address=address.lower(), defaults={"reason": reason[:40]}
    )


UNSUBSCRIBE_SALT = "comms.unsubscribe"


def unsubscribe_token(recipient: registry.Recipient, category: str, message_id: str = "") -> str:
    data = {
        "o": str(require_organisation_id()),
        "k": recipient.kind,
        "i": recipient.id,
        "c": category,
    }
    if message_id:
        data["m"] = message_id  # broadcasts count unsubscribes per message
    return signing.dumps(data, salt=UNSUBSCRIBE_SALT)


def read_unsubscribe(token: str) -> dict[str, str] | None:
    try:
        data = signing.loads(token, salt=UNSUBSCRIBE_SALT, max_age=60 * 60 * 24 * 365)
    except signing.BadSignature:
        return None
    return data if isinstance(data, dict) else None


def unsubscribe(data: dict[str, str]) -> None:
    """One-click unsubscribe: no more email for that category (RFC 8058)."""
    current = CommunicationPreference.objects.filter(
        person_type=data["k"], person_id=data["i"], category=data["c"]
    ).first()
    # No preference yet: every channel except WhatsApp, which needs an explicit opt-in.
    channels_left = set(current.channels) if current else set(Channel.values) - {Channel.WHATSAPP}
    channels_left.discard(Channel.EMAIL)
    set_preference(data["k"], data["i"], data["c"], sorted(channels_left))
    message = Message.objects.filter(pk=data["m"]).first() if data.get("m") else None
    if message is not None and not message.events.filter(type="unsubscribed").exists():
        _event(message, "unsubscribed", {"category": data["c"]})


# --- the pipeline (T05) -------------------------------------------------------------------------


def _quiet_until(moment: datetime, tz: str) -> datetime | None:
    """When a text may go out if ``moment`` is in quiet hours (None = now is fine)."""
    try:
        start = time.fromisoformat(str(get_setting("comms.quiet_hours_start")))
        end = time.fromisoformat(str(get_setting("comms.quiet_hours_end")))
    except ValueError:
        return None
    local = moment.astimezone(ZoneInfo(tz))
    t = local.time()
    quiet = (start <= t or t < end) if start > end else (start <= t < end)
    if not quiet:
        return None
    day = local.date() if t < end else local.date() + timedelta(days=1)
    return datetime.combine(day, end, tzinfo=ZoneInfo(tz))


def _address(recipient: registry.Recipient, channel: str) -> str:
    if channel == Channel.EMAIL:
        return recipient.email.lower()
    if channel in {Channel.SMS, Channel.WHATSAPP}:
        from tutortrack.tenancy.models import Organisation

        org = Organisation.objects.get(pk=require_organisation_id())
        return channels.normalise_phone(recipient.phone, org.country)
    return recipient.user_id or ""  # in-app and push go to the signed-in user


def notify(
    type_key: str,
    subject: Any,
    *,
    key: str,
    immediate: bool = False,
    only_channel: str | None = None,
) -> list[Message]:
    """Send notification ``type_key`` about ``subject``. ``key`` identifies the occurrence
    (with type, recipient and channel it forms the dedupe key)."""
    from tutortrack.core import demo_mode

    if demo_mode.active():  # sample data (FR-02-6) never messages anyone
        return []
    setting = effective(type_key)
    if not setting.enabled and only_channel is None:
        return []
    t = setting.type
    wanted = (only_channel,) if only_channel else setting.channels
    out: list[Message] = []
    for delivery in t.resolve(subject):
        out += _deliver(t, subject, delivery, wanted, key=key, immediate=immediate)
    return out


def notify_on_commit(type_key: str, subject: Any, *, key: str) -> None:
    """``notify`` once the transaction commits, in the organisation that was current when
    it was registered (commit hooks can run after the request's tenant context ends)."""
    from tutortrack.core.context import tenant_context

    organisation_id = require_organisation_id()

    def send() -> None:
        with tenant_context(organisation_id):
            notify(type_key, subject, key=key)

    transaction.on_commit(send)


def _deliver(
    t: NotificationType,
    subject: Any,
    delivery: Delivery,
    wanted: tuple[str, ...],
    *,
    key: str,
    immediate: bool,
) -> list[Message]:
    recipient = delivery.recipient
    possible = [c for c in wanted if c in recipient.available()]
    allowed = allowed_channels(recipient, t.category)
    if allowed is None or Channel.WHATSAPP not in allowed:
        # WhatsApp needs the person's explicit opt-in (a preference naming it).
        possible = [c for c in possible if c != Channel.WHATSAPP]
    if allowed is not None:
        chosen = [c for c in possible if c in allowed]
        if not chosen and t.transactional and Channel.EMAIL in possible:
            chosen = [Channel.EMAIL]  # legally required: the channel can change, not stop
        possible = chosen
    messages = []
    for channel in possible:
        message = _create(t, subject, delivery, channel, key=key)
        if message is None:
            continue
        messages.append(message)
        if message.status == Message.Status.QUEUED:
            _dispatch(message, immediate=immediate)
            if immediate:
                message.refresh_from_db()
    return messages


def _create(
    t: NotificationType, subject: Any, delivery: Delivery, channel: str, *, key: str
) -> Message | None:
    recipient = delivery.recipient
    dedupe = f"{t.key}:{key}:{recipient.kind}:{recipient.id}:{channel}"[:255]
    if Message.objects.filter(dedupe_key=dedupe).exists():
        return None
    meta: dict[str, Any] = {}
    if channel == Channel.WHATSAPP:
        from . import senders

        rendered = senders.render_whatsapp_for_type(t.key, delivery.context)
        if rendered is None:
            return None  # no approved WhatsApp template for this notification
        subject_text, body, meta = "", rendered.body, rendered.meta
    else:
        try:
            subject_text, body = render_message(t.key, channel, delivery.context)
        except render.TemplateInvalid as exc:
            subject_text, body = "", f"[template error: {exc}]"
    address = _address(recipient, channel)
    status = Message.Status.QUEUED
    if not address:
        return None
    if channel == Channel.PUSH and not PushSubscription.objects.filter(user_id=address).exists():
        return None  # no device has push switched on
    if channel not in {Channel.IN_APP, Channel.PUSH} and suppressed(channel, address):
        status = Message.Status.SUPPRESSED
    blocked = hooks.run_pre_send(
        hooks.OutgoingMessage(
            type_key=t.key,
            category=t.category,
            channel=channel,
            recipient_kind=recipient.kind,
            recipient_id=recipient.id,
            recipient_user_id=recipient.user_id,
            subject=subject_text,
            body=body,
        )
    )
    if blocked:
        if channel in {Channel.IN_APP, Channel.PUSH}:
            return None
        status = Message.Status.SUPPRESSED
    scheduled = None
    if channel in {Channel.SMS, Channel.WHATSAPP} and status == Message.Status.QUEUED:
        tz = str((delivery.context.get("organisation") or {}).get("timezone") or "UTC")
        scheduled = _quiet_until(now(), tz)
    related_id = str(getattr(subject, "pk", "") or "")
    try:
        with transaction.atomic():
            message = Message.objects.create(
                type_key=t.key,
                channel=channel,
                recipient_type=recipient.kind,
                recipient_id=recipient.id,
                recipient_name=recipient.name[:200],
                to=address,
                subject=subject_text[:300],
                body=body,
                status=status,
                error=blocked[:500],
                related_type=t.related_type,
                related_id=related_id,
                target_type=recipient.target[0],
                target_id=recipient.target[1],
                dedupe_key=dedupe,
                scheduled_for=scheduled,
                segments=render.sms_segments(body) if channel == Channel.SMS else 0,
                meta=meta,
            )
    except IntegrityError:
        return None  # a concurrent delivery got there first
    if channel == Channel.IN_APP:
        link = t.link(subject) if t.link else ""
        InAppNotification.objects.create(
            user_id=recipient.user_id, type_key=t.key, title=subject_text[:300], body=body,
            link=link[:300],
        )  # fmt: skip
        Message.objects.filter(pk=message.pk).update(status=Message.Status.DELIVERED, sent_at=now())
        message.status = Message.Status.DELIVERED
    return message


def _dispatch(message: Message, *, immediate: bool) -> None:
    from .tasks import send_message

    org_id, message_id = str(message.organisation_id), str(message.pk)
    if immediate:
        send_now(message)
        return
    eta = message.scheduled_for

    def enqueue() -> None:
        if eta:
            send_message.apply_async(
                kwargs={"organisation_id": org_id, "message_id": message_id}, eta=eta
            )
        else:
            send_message.delay(organisation_id=org_id, message_id=message_id)

    transaction.on_commit(enqueue)


def _event(message: Message, kind: str, detail: dict[str, Any] | None = None) -> None:
    MessageEvent.objects.create(message=message, type=kind, occurred_at=now(), detail=detail or {})


def send_now(message: Message) -> Message:
    """Hand one queued message to its channel (called by the send task)."""
    message = Message.objects.get(pk=message.pk)
    if message.status != Message.Status.QUEUED:
        return message
    if message.scheduled_for and message.scheduled_for > now():
        return message  # a retry arrived early: the delayed task will send it
    try:
        if message.channel == Channel.EMAIL:
            _send_email(message)
        elif message.channel == Channel.SMS:
            _send_sms(message)
        elif message.channel == Channel.PUSH:
            _send_push(message)
        elif message.channel == Channel.WHATSAPP:
            _send_whatsapp(message)
    except channels.ChannelError as exc:
        Message.objects.filter(pk=message.pk).update(
            status=Message.Status.FAILED, error=str(exc)[:500]
        )
        _event(message, "failed", {"error": str(exc)[:500]})
        message.refresh_from_db()
        return message
    message.refresh_from_db()
    _after_send(message)
    return message


def _organisation_name() -> str:
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    return str(get_setting("comms.sender_name") or org.name)


def _send_email(message: Message) -> None:
    t = registry.get(message.type_key)
    subject_obj = t.load(message.related_id) if message.related_id else None
    attachments = t.attachments(subject_obj) if t.attachments and subject_obj else []
    headers = {
        "X-PM-Metadata-message-id": str(message.pk),
        "X-PM-Metadata-org": str(message.organisation_id),
    }
    footer = ""
    if not t.transactional and t.audience != "staff":
        recipient = registry.Recipient(
            kind=message.recipient_type, id=message.recipient_id, name="", first_name=""
        )
        token = unsubscribe_token(recipient, t.category, message_id=str(message.pk))
        url = f"{settings.PLATFORM_BASE_URL}/api/v1/unsubscribe/{token}"
        headers["List-Unsubscribe"] = f"<{url}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        footer = f'<a href="{url}">{_("Unsubscribe from these emails")}</a>'
    name = _organisation_name()
    from . import senders

    try:
        channels.send_email(
            to=message.to,
            subject=message.subject,
            text=message.body,
            html=render.to_html(
                message.body,
                organisation=name,
                footer=footer,
                brand=branding.for_email(message.organisation_id),
            ),
            from_name=name,
            reply_to=senders.reply_to_for(message),
            headers=headers,
            attachments=attachments,
            from_address=senders.from_address(),
        )
    except Exception as exc:  # SMTP errors, attachment rendering
        raise channels.ChannelError(str(exc)) from exc
    Message.objects.filter(pk=message.pk).update(status=Message.Status.SENT, sent_at=now())
    _event(message, "sent")


def _send_sms(message: Message) -> None:
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=message.organisation_id)
    if not channels.credit_meter().consume(message.segments or 1, country=org.country):
        raise channels.ChannelError("No SMS credits left.")
    from . import senders

    sender = senders.sender_number(Channel.SMS)
    result = channels.sms_provider().send(
        to=message.to, body=message.body, status_callback=_status_callback(message), sender=sender
    )
    if not sender:
        senders.remember_reply_route(Channel.SMS, message.to)
    Message.objects.filter(pk=message.pk).update(
        status=Message.Status.SENT, sent_at=now(), provider_ref=result.ref
    )
    _event(message, "sent", {"ref": result.ref})


def _status_callback(message: Message) -> str:
    return (
        f"{settings.PLATFORM_BASE_URL}/webhooks/twilio/status"
        f"?org={message.organisation_id}&message={message.pk}"
    )


def _send_whatsapp(message: Message) -> None:
    """Free text inside the 24-hour window (inbox replies), else the approved template
    recorded in ``meta`` (E13-T12)."""
    from . import providers, senders

    meta = message.meta or {}
    content_sid = str(meta.get("content_sid") or "")
    sender = senders.sender_number(Channel.WHATSAPP)
    result = providers.whatsapp_provider().send(
        to=message.to,
        status_callback=_status_callback(message),
        body="" if content_sid else message.body,
        content_sid=content_sid,
        variables={str(k): str(v) for k, v in (meta.get("variables") or {}).items()},
        sender=sender,
    )
    if not sender:
        senders.remember_reply_route(Channel.WHATSAPP, message.to)
    Message.objects.filter(pk=message.pk).update(
        status=Message.Status.SENT, sent_at=now(), provider_ref=result.ref
    )
    _event(message, "sent", {"ref": result.ref})


def _after_send(message: Message) -> None:
    """Types that record their own "sent" fact (invoices)."""
    if message.type_key == "invoice_issued" and message.status == Message.Status.SENT:
        from tutortrack.billing import services as billing
        from tutortrack.billing.models import Invoice

        invoice = Invoice.objects.filter(pk=message.related_id).first()
        if invoice is not None:
            with transaction.atomic():
                billing.mark_sent(invoice, to=[message.to])


# --- Web Push (E16-T09) -------------------------------------------------------------------------

MAX_PUSH_FAILURES = 5
PUSH_URGENT_CATEGORIES = {"scheduling"}
# Where a tutor's push opens in the portal, by the notification's subject record.
TUTOR_PUSH_LINKS = {
    "scheduling.lesson": "/portal/tutor/lessons/{id}",
    "delivery.lessonreport": "/portal/tutor/reports/{id}",
}


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.strip().encode()).hexdigest()


def _b64url(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        return b""


@transaction.atomic
def subscribe_push(
    user: Any, *, endpoint: str, p256dh: str, auth: str, device: str = ""
) -> PushSubscription:
    """Register (or refresh) this browser's push subscription for ``user``. A browser
    shared by two people pushes to whoever subscribed last."""
    try:
        host = channels.push_host(endpoint)
    except ValueError:
        raise _invalid(
            "endpoint", _("Push notifications from this browser aren't supported.")
        ) from None
    key = _b64url(p256dh)
    if len(key) != 65 or key[0] != 4:
        raise _invalid("p256dh", _("The browser sent an invalid push key."))
    if len(_b64url(auth)) != 16:
        raise _invalid("auth", _("The browser sent an invalid push key."))
    digest = endpoint_hash(endpoint)
    row = PushSubscription.objects.filter(endpoint_hash=digest).first()
    if row is not None:
        moved = row.user_id != user.pk
        with audit.track(row, action="update"):
            row.user = user
            row.p256dh, row.auth = p256dh, auth
            row.device = device[:120] or row.device
            row.failures = 0
            row.save()
        if moved:
            publish(events.PushSubscriptionAdded(subject_id=row.pk, user_id=str(user.pk),
                                                 push_service=row.push_service))  # fmt: skip
        return row
    row = PushSubscription.objects.create(
        user=user, endpoint=endpoint.strip(), endpoint_hash=digest, p256dh=p256dh, auth=auth,
        device=device[:120], push_service=host,
    )  # fmt: skip
    audit.record_create(row)
    publish(
        events.PushSubscriptionAdded(subject_id=row.pk, user_id=str(user.pk), push_service=host)
    )
    return row


@transaction.atomic
def remove_push_subscription(row: PushSubscription, *, reason: str = "removed") -> None:
    audit.record(row, "delete")
    publish(
        events.PushSubscriptionRemoved(
            subject_id=row.pk, user_id=str(row.user_id), push_service=row.push_service,
            reason=reason,
        )
    )  # fmt: skip
    row.delete()


def _push_to(
    subscriptions: list[PushSubscription], payload: dict[str, Any], *, urgency: str, topic: str
) -> tuple[int, int]:
    """Push to each device; forget expired ones. Returns (delivered, removed)."""
    provider = channels.push_provider()
    body = json.dumps(payload).encode()
    ttl = int(settings.WEB_PUSH["TTL_SECONDS"])
    delivered = removed = 0
    for sub in subscriptions:
        target = channels.PushTarget(sub.endpoint, sub.p256dh, sub.auth)
        try:
            result = provider.send(target, body, ttl=ttl, urgency=urgency, topic=topic)
        except channels.ChannelError:
            result = channels.PushResult(0)
        if result.gone:
            remove_push_subscription(sub, reason="expired")
            removed += 1
        elif result.ok:
            PushSubscription.objects.filter(pk=sub.pk).update(last_sent_at=now(), failures=0)
            delivered += 1
        elif sub.failures + 1 >= MAX_PUSH_FAILURES:
            remove_push_subscription(sub, reason="failing")
            removed += 1
        else:
            PushSubscription.objects.filter(pk=sub.pk).update(failures=sub.failures + 1)
    return delivered, removed


def _push_url(message: Message) -> str:
    t = registry.get(message.type_key)
    if message.recipient_type == "tutor":
        pattern = TUTOR_PUSH_LINKS.get(t.related_type)
        if pattern and message.related_id:
            return pattern.format(id=message.related_id)
    subject = t.load(message.related_id) if message.related_id else None
    link = ""
    if t.link is not None and (subject is not None or not message.related_id):
        try:
            link = t.link(subject)
        except AttributeError:
            link = ""
    if message.recipient_type == "tutor" and not link.startswith("/portal/"):
        return "/portal/tutor"
    return link or "/"


def _send_push(message: Message) -> None:
    subscriptions = list(PushSubscription.objects.filter(user_id=message.to))
    if not subscriptions:
        raise channels.ChannelError("No device has push notifications switched on.")
    t = registry.get(message.type_key)
    tag = f"{message.type_key}:{message.related_id}"[:64]
    payload = {
        "title": (message.subject or _organisation_name())[:120],
        "body": " ".join(message.body.split())[:240],
        "url": _push_url(message),
        "tag": tag,
    }
    urgency = "high" if t.category in PUSH_URGENT_CATEGORIES else "normal"
    topic = hashlib.sha256(tag.encode()).hexdigest()[:32]  # a newer push replaces it
    delivered, removed = _push_to(subscriptions, payload, urgency=urgency, topic=topic)
    if not delivered:
        raise channels.ChannelError(
            f"No device accepted the notification ({len(subscriptions)} tried, {removed} removed)."
        )
    Message.objects.filter(pk=message.pk).update(
        status=Message.Status.SENT, sent_at=now(), provider_ref=f"{delivered} device(s)"
    )
    _event(message, "sent", {"devices": delivered, "removed": removed})


def send_test_push(user: Any) -> int:
    """A test notification to each of ``user``'s devices; returns how many accepted it."""
    subscriptions = list(PushSubscription.objects.filter(user=user))
    if not subscriptions:
        raise BusinessRuleViolation(_("Turn on push notifications on this device first."))
    payload = {
        "title": _("Notifications are on"),
        "body": _("This is how %(name)s will let you know about changes.")
        % {"name": _organisation_name()},
        "url": "/portal/tutor/notifications",
        "tag": "test",
    }
    delivered, _removed = _push_to(subscriptions, payload, urgency="normal", topic="")
    return delivered


# --- my notification preferences (E16-T09, FR-16-9) ---------------------------------------------


def person_for(user: Any) -> tuple[str, str]:
    """The recipient a signed-in user is in notifications: their tutor profile, else the
    user (staff)."""
    from tutortrack.people.models import TutorProfile

    tutor = TutorProfile.objects.filter(membership__user=user).only("pk").first()
    return ("tutor", str(tutor.pk)) if tutor is not None else ("user", str(user.pk))


def my_preferences(user: Any) -> list[dict[str, Any]]:
    """Per category: the channels the user's notifications can use and the ones chosen."""
    person_type, person_id = person_for(user)
    audience = "tutor" if person_type == "tutor" else "staff"
    rows = {
        r.category: set(r.channels)
        for r in CommunicationPreference.objects.filter(
            person_type=person_type, person_id=person_id
        )
    }
    out = []
    for category in registry.CATEGORIES:
        available: set[str] = set()
        for t in registry.visible_types():
            if t.category == category and t.audience == audience:
                available.update(t.channels)
        if not available:
            continue
        order = [c for c in Channel.values if c in available]
        chosen = rows.get(category)
        out.append(
            {
                "category": category,
                "available": order,
                "channels": order if chosen is None else [c for c in order if c in chosen],
            }
        )
    return out


@transaction.atomic
def set_my_preferences(user: Any, choices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    person_type, person_id = person_for(user)
    current = {row["category"]: row for row in my_preferences(user)}
    for choice in choices:
        row = current.get(choice["category"])
        if row is None:
            raise _invalid("category", _("Unknown category."))
        unknown = set(choice["channels"]) - set(row["available"])
        if unknown:
            raise _invalid("channels", _("That channel isn't available here."))
        # Keep channels this screen doesn't offer (e.g. text) as they were.
        others = set(Channel.values) - set(row["available"])
        existing = CommunicationPreference.objects.filter(
            person_type=person_type, person_id=person_id, category=choice["category"]
        ).first()
        kept = others & (set(existing.channels) if existing else others)
        set_preference(person_type, person_id, choice["category"],
                       sorted(kept | set(choice["channels"])))  # fmt: skip
    return my_preferences(user)


# --- delivery events (T03/T04) ------------------------------------------------------------------

POSTMARK_STATUS = {
    "Delivery": Message.Status.DELIVERED,
    "Open": Message.Status.OPENED,
    "Click": Message.Status.CLICKED,
    "Bounce": Message.Status.BOUNCED,
    "SpamComplaint": Message.Status.COMPLAINED,
}
PROGRESS: list[str] = [
    Message.Status.QUEUED,
    Message.Status.SENT,
    Message.Status.DELIVERED,
    Message.Status.OPENED,
    Message.Status.CLICKED,
]


def record_delivery_event(message: Message, status: str, detail: dict[str, Any]) -> Message:
    """Apply a provider status (out-of-order safe: never moves backwards along
    sent → delivered → opened → clicked; failures always win)."""
    terminal = status in {
        Message.Status.BOUNCED,
        Message.Status.COMPLAINED,
        Message.Status.FAILED,
    }
    current = message.status
    forward = (
        current in PROGRESS
        and status in PROGRESS
        and PROGRESS.index(status) > PROGRESS.index(current)
    )
    _event(message, status, detail)
    if terminal or forward:
        Message.objects.filter(pk=message.pk).update(status=status)
        message.status = status
    if status in {Message.Status.BOUNCED, Message.Status.COMPLAINED}:
        hard = status == Message.Status.COMPLAINED or detail.get("Type") in {
            "HardBounce",
            "BadEmailAddress",
            "ManuallyDeactivated",
            "SpamNotification",
        }
        if hard:
            suppress(message.channel, message.to, status)
    return message


def sms_opt_out(phone: str, stop: bool) -> None:
    if stop:
        SmsOptOut.objects.get_or_create(phone=phone)
    else:
        SmsOptOut.objects.filter(phone=phone).delete()


# --- in-app (T08) -------------------------------------------------------------------------------


def mark_read(user: Any, ids: list[Any] | None = None) -> int:
    qs = InAppNotification.objects.filter(user=user, read_at__isnull=True)
    if ids is not None:
        qs = qs.filter(pk__in=ids)
    return qs.update(read_at=now())


def test_send(type_key: str, channel: str, *, user: Any) -> Message:
    """Send the sample message to the current user (email or in-app)."""
    t = registry.get(type_key)
    if channel not in {Channel.EMAIL, Channel.IN_APP}:
        raise _invalid("channel", _("Test sends go to your email or your notifications."))
    recipient = registry.Recipient(
        kind="user", id=str(user.pk), name=user.get_full_name() or user.email,
        first_name=user.first_name or user.email, email=user.email, user_id=str(user.pk),
    )  # fmt: skip
    context = {
        **t.sample,
        "recipient": {"name": recipient.name, "first_name": recipient.first_name},
    }
    test_type = NotificationType(
        **{**t.__dict__, "attachments": None, "link": None, "transactional": True}
    )
    message = _create(test_type, None, Delivery(recipient, context), channel,
                      key=f"test:{now().timestamp()}")  # fmt: skip
    if message is None:
        raise BusinessRuleViolation(_("Nothing was sent."))
    if message.status == Message.Status.QUEUED:
        send_now(message)
    message.refresh_from_db()
    return message


# --- free-form messages (E13 Phase 2: broadcasts and inbox replies) -----------------------------


def queue_message(
    *,
    type_key: str,
    channel: str,
    recipient: registry.Recipient,
    subject: str,
    body: str,
    dedupe_key: str,
    related: tuple[str, str] = ("", ""),
    thread: Any = None,
    meta: dict[str, Any] | None = None,
    respect_quiet_hours: bool = True,
    category: str = "",
) -> Message | None:
    """Queue one message that isn't a templated notification (a broadcast to one person,
    an inbox reply) through the same channels, suppressions, quiet hours and delivery
    tracking. ``type_key`` is a hidden registry type; ``dedupe_key`` makes retries
    harmless (None = already queued, or nowhere to send it)."""
    from tutortrack.tenancy.models import Organisation

    dedupe_key = dedupe_key[:255]
    if Message.objects.filter(dedupe_key=dedupe_key).exists():
        return None
    address = _address(recipient, channel)
    if not address:
        return None
    status = Message.Status.QUEUED
    if channel not in {Channel.IN_APP, Channel.PUSH} and suppressed(channel, address):
        status = Message.Status.SUPPRESSED
    # E29 pre-send hooks (e.g. no marketing to children). People's own words are screened
    # where they write them (the inbox), so this carries no sender.
    blocked = hooks.run_pre_send(
        hooks.OutgoingMessage(
            type_key=type_key,
            category=category,
            channel=channel,
            recipient_kind=recipient.kind,
            recipient_id=recipient.id,
            recipient_user_id=recipient.user_id,
            subject=subject,
            body=body,
            source_type=related[0] or "comms.message",
            source_id=related[1],
        )
    )
    if blocked:
        if channel in {Channel.IN_APP, Channel.PUSH}:
            return None
        status = Message.Status.SUPPRESSED
    scheduled = None
    texting = channel in {Channel.SMS, Channel.WHATSAPP}
    if respect_quiet_hours and texting and status == Message.Status.QUEUED:
        tz = Organisation.objects.get(pk=require_organisation_id()).timezone
        scheduled = _quiet_until(now(), tz)
    try:
        with transaction.atomic():
            message = Message.objects.create(
                type_key=type_key,
                channel=channel,
                recipient_type=recipient.kind,
                recipient_id=recipient.id,
                recipient_name=recipient.name[:200],
                to=address,
                subject=subject[:300],
                body=body,
                status=status,
                error=blocked[:500],
                related_type=related[0],
                related_id=related[1],
                target_type=recipient.target[0],
                target_id=recipient.target[1],
                dedupe_key=dedupe_key,
                scheduled_for=scheduled,
                segments=render.sms_segments(body) if channel == Channel.SMS else 0,
                thread=thread,
                meta=meta or {},
            )
    except IntegrityError:
        return None
    if status == Message.Status.QUEUED:
        _dispatch(message, immediate=False)
    return message
