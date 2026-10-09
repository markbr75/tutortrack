"""Communications writes (E13): settings, templates, the notification pipeline, sending,
preferences, suppressions and in-app notifications.

Pipeline (FR-13-4): ``notify(type, subject)`` → the organisation's setting (enabled,
channels) → recipients from the type → each channel the recipient can receive, allowed by
their preferences and not suppressed → render (override or default template) → a
``Message`` with a dedupe key (retries and redelivered events never double-send) → sent by
a task (texts deferred out of quiet hours).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import channels, defaults, registry, render
from .models import (
    Channel,
    CommunicationPreference,
    InAppNotification,
    Message,
    MessageEvent,
    MessageTemplate,
    OrgNotificationSetting,
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
    return Suppression.objects.filter(channel=channel, address=address.lower()).exists()


def suppress(channel: str, address: str, reason: str) -> None:
    Suppression.objects.get_or_create(
        channel=channel, address=address.lower(), defaults={"reason": reason[:40]}
    )


UNSUBSCRIBE_SALT = "comms.unsubscribe"


def unsubscribe_token(recipient: registry.Recipient, category: str) -> str:
    return signing.dumps(
        {
            "o": str(require_organisation_id()),
            "k": recipient.kind,
            "i": recipient.id,
            "c": category,
        },
        salt=UNSUBSCRIBE_SALT,
    )


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
    channels_left = set(current.channels) if current else set(Channel.values)
    channels_left.discard(Channel.EMAIL)
    set_preference(data["k"], data["i"], data["c"], sorted(channels_left))


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
    if channel == Channel.SMS:
        from tutortrack.tenancy.models import Organisation

        org = Organisation.objects.get(pk=require_organisation_id())
        return channels.normalise_phone(recipient.phone, org.country)
    return recipient.user_id or ""


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
    setting = effective(type_key)
    if not setting.enabled and only_channel is None:
        return []
    t = setting.type
    wanted = (only_channel,) if only_channel else setting.channels
    out: list[Message] = []
    for delivery in t.resolve(subject):
        out += _deliver(t, subject, delivery, wanted, key=key, immediate=immediate)
    return out


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
    try:
        subject_text, body = render_message(t.key, channel, delivery.context)
    except render.TemplateInvalid as exc:
        subject_text, body = "", f"[template error: {exc}]"
    address = _address(recipient, channel)
    status = Message.Status.QUEUED
    if not address:
        return None
    if channel != Channel.IN_APP and suppressed(channel, address):
        status = Message.Status.SUPPRESSED
    scheduled = None
    if channel == Channel.SMS and status == Message.Status.QUEUED:
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
                related_type=t.related_type,
                related_id=related_id,
                target_type=recipient.target[0],
                target_id=recipient.target[1],
                dedupe_key=dedupe,
                scheduled_for=scheduled,
                segments=render.sms_segments(body) if channel == Channel.SMS else 0,
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
        token = unsubscribe_token(recipient, t.category)
        url = f"{settings.PLATFORM_BASE_URL}/api/v1/unsubscribe/{token}"
        headers["List-Unsubscribe"] = f"<{url}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        footer = f'<a href="{url}">{_("Unsubscribe from these emails")}</a>'
    name = _organisation_name()
    try:
        channels.send_email(
            to=message.to,
            subject=message.subject,
            text=message.body,
            html=render.to_html(message.body, organisation=name, footer=footer),
            from_name=name,
            reply_to=str(get_setting("comms.reply_to")),
            headers=headers,
            attachments=attachments,
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
    callback = (
        f"{settings.PLATFORM_BASE_URL}/webhooks/twilio/status"
        f"?org={message.organisation_id}&message={message.pk}"
    )
    result = channels.sms_provider().send(
        to=message.to, body=message.body, status_callback=callback
    )
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
