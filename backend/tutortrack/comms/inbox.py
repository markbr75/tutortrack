"""The conversations inbox (E13-T11): the service layer.

Threads gather everything said with one family, one tutor, a tutor and a family, or an
unknown sender, whatever the channel:

* **Inbound** email (``reply+…``/``inbox+…`` addresses through the Postmark inbound
  webhook), texts and WhatsApp messages (Twilio), and portal chat from families and
  tutors (E15/E16). Duplicate webhook deliveries are ignored (``provider_ref``).
* **Outbound** staff replies go back by the thread's channel (email with the thread's
  reply address, text, WhatsApp within the 24-hour window) or as portal chat; internal
  notes stay with staff.
* **Team inbox:** assignment, snooze (reopens by itself when the time passes: the read
  side compares ``snoozed_until`` with now), close/reopen, canned replies and an SLA
  timer (``awaiting_reply_since`` + ``comms.inbox_sla_hours``).
* **Safeguarding (FR-13-7, E29):** every message is kept and visible to staff; messages
  with contact details or profanity are flagged, and ``comms.block_contact_sharing``
  stops tutors and families exchanging contact details.

New non-staff messages publish ``message.received`` (staff alerts and E31 hooks);
portal chat replies notify the other side ("you have a new message").
"""

from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import events, hooks
from .models import CannedReply, Channel, Message, Thread, ThreadMessage, ThreadParticipant
from .registry import Recipient

Kind = Thread.Kind
Via = ThreadMessage.Via
Direction = ThreadMessage.Direction
Role = ThreadParticipant.Role
REOPEN_WITHIN = timedelta(days=14)
MAX_INBOUND_ATTACHMENT_BYTES = 10 * 1024 * 1024


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


# --- safeguarding detection ---------------------------------------------------------------------

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?\d[\s().-]?){9,}")
PROFANITY = frozenset(
    {"fuck", "fucking", "shit", "bitch", "bastard", "cunt", "wanker", "twat", "dickhead"}
)


def detect_flags(body: str) -> list[str]:
    flags = []
    if EMAIL_RE.search(body) or PHONE_RE.search(body):
        flags.append("contact_details")
    words = set(re.findall(r"[a-z]+", body.lower()))
    if words & PROFANITY:
        flags.append("profanity")
    return flags


# --- participants -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Author:
    type: str  # contact | student | tutor | user | external | system
    id: str
    name: str
    user: Any = None

    @classmethod
    def staff(cls, user: Any) -> Author:
        return cls("user", str(user.pk), user.get_full_name() or user.email, user)


def _participant(thread: Thread, role: str, person_type: str, person_id: str, **values: Any) -> Any:
    row, created = ThreadParticipant.objects.get_or_create(
        thread=thread,
        person_type=person_type,
        person_id=str(person_id),
        defaults={"role": role, **values},
    )
    if not created:
        changed = False
        for name, value in values.items():
            if value and getattr(row, name) != value:
                setattr(row, name, value)
                changed = True
        if changed:
            row.save()
    return row


def _add_family(thread: Thread, client: Any) -> None:
    from tutortrack.people.models import Contact

    for contact in Contact.objects.filter(client=client, archived_at__isnull=True):
        _participant(
            thread,
            Role.FAMILY,
            "contact",
            str(contact.pk),
            user=contact.user,
            name=contact.full_name,
            email=contact.email,
            phone=contact.mobile,
        )


def _add_tutor(thread: Thread, tutor: Any) -> None:
    membership = tutor.membership
    user = membership.user if membership is not None and membership.status == "active" else None
    _participant(
        thread,
        Role.TUTOR,
        "tutor",
        str(tutor.pk),
        user=user,
        name=tutor.full_name,
        email=tutor.email,
        phone=tutor.phone,
    )


def _branch_for(client: Any = None, tutor: Any = None) -> Any:
    if client is not None:
        return client.branch_id
    if tutor is not None:
        first = tutor.branches.order_by("pk").values_list("pk", flat=True).first()
        if first:
            return first
    return None


@transaction.atomic
def open_thread(
    *,
    kind: str,
    subject: str = "",
    client: Any = None,
    tutor: Any = None,
    contact_name: str = "",
    contact_email: str = "",
    contact_phone: str = "",
    channel: str = Via.CHAT,
) -> Thread:
    if kind in (Kind.CLIENT, Kind.TUTOR_FAMILY) and client is None:
        raise _invalid("client", _("Choose the family."))
    if kind in (Kind.TUTOR, Kind.TUTOR_FAMILY) and tutor is None:
        raise _invalid("tutor", _("Choose the tutor."))
    thread = Thread(
        kind=kind,
        subject=subject[:200],
        client=client,
        tutor=tutor,
        contact_name=contact_name[:200],
        contact_email=contact_email[:254].lower(),
        contact_phone=contact_phone[:32],
        channel=channel,
    )
    branch = _branch_for(client, tutor)
    if branch:
        thread.branch_id = branch
    thread.save()
    audit.record_create(thread)
    if client is not None:
        _add_family(thread, client)
    if tutor is not None:
        _add_tutor(thread, tutor)
    if kind == Kind.OTHER:
        _participant(
            thread,
            Role.EXTERNAL,
            "external",
            hashlib.sha256((contact_email or contact_phone).lower().encode()).hexdigest()[:32],
            name=contact_name,
            email=contact_email,
            phone=contact_phone,
        )
    return thread


def _find_open(
    *, kind: str, client: Any = None, tutor: Any = None, email: str = "", phone: str = ""
) -> Thread | None:
    qs = Thread.objects.filter(kind=kind)
    if client is not None:
        qs = qs.filter(client=client)
    if tutor is not None:
        qs = qs.filter(tutor=tutor)
    if kind == Kind.OTHER:
        qs = qs.filter(contact_email=email.lower()) if email else qs.filter(contact_phone=phone)
    found = qs.exclude(status=Thread.Status.CLOSED).order_by("-last_message_at").first()
    if found is not None:
        return found
    return (
        qs.filter(status=Thread.Status.CLOSED, closed_at__gte=now() - REOPEN_WITHIN)
        .order_by("-closed_at")
        .first()
    )


# --- recording messages -------------------------------------------------------------------------


def _record(
    thread: Thread,
    *,
    direction: str,
    channel: str,
    author: Author,
    body: str,
    subject: str = "",
    provider_ref: str = "",
    attachments: list[dict[str, Any]] | None = None,
    message: Message | None = None,
) -> ThreadMessage | None:
    """Store one entry and update the thread (None: a webhook delivered it twice)."""
    flags = detect_flags(body) if direction != Direction.INTERNAL else []
    try:
        with transaction.atomic():
            entry = ThreadMessage.objects.create(
                thread=thread,
                direction=direction,
                channel=channel,
                author_type=author.type,
                author_id=author.id,
                author_name=author.name[:200],
                author_user=author.user,
                subject=subject[:300],
                body=body,
                provider_ref=provider_ref[:255],
                attachments=attachments or [],
                flags=flags,
                message=message,
            )
    except IntegrityError:
        return None
    moment = entry.created_at
    thread = Thread.objects.select_for_update().get(pk=thread.pk)
    with audit.track(thread, action="message"):
        if direction != Direction.INTERNAL:
            thread.last_message_at = moment
            thread.last_message_preview = " ".join(body.split())[:200]
        if direction == Direction.INBOUND:
            thread.awaiting_reply_since = thread.awaiting_reply_since or moment
            if thread.status != Thread.Status.OPEN:
                thread.status, thread.snoozed_until, thread.closed_at = (
                    Thread.Status.OPEN,
                    None,
                    None,
                )
            if channel != Via.CHAT:
                thread.channel = channel
        elif direction == Direction.OUTBOUND and author.type == "user":
            thread.awaiting_reply_since = None
            if thread.status == Thread.Status.SNOOZED:
                thread.status, thread.snoozed_until = Thread.Status.OPEN, None
        if flags:
            thread.flagged = True
        thread.save()
    if direction == Direction.INBOUND:
        publish(
            events.MessageReceived(
                subject_id=entry.pk,
                thread_id=str(thread.pk),
                channel=channel,
                author_type=author.type,
                flagged=bool(flags),
            )
        )
    return entry


def _saved(entry: ThreadMessage | None) -> ThreadMessage:
    """Entries without a provider reference are never duplicates."""
    if entry is None:
        raise BusinessRuleViolation(_("That message was already recorded."))
    return entry


def _notify_chat(entry: ThreadMessage) -> None:
    """Portal chat: tell the other side there's a message waiting (max one an hour per
    thread and person, by dedupe key)."""
    from .services import notify

    bucket = now().strftime("%Y%m%d%H")
    thread = entry.thread
    key = f"{thread.pk}:{bucket}"
    if thread.client_id:
        notify("conversation_message_family", entry, key=key)
    if thread.tutor_id:
        notify("conversation_message_tutor", entry, key=key)


# --- staff side ---------------------------------------------------------------------------------


def _external_recipients(thread: Thread, channel: str) -> list[Recipient]:
    """Who a staff reply by email/text/WhatsApp goes to: whoever wrote last from outside,
    else the thread's family (or tutor, or the unknown sender)."""
    last = (
        thread.messages.filter(direction=Direction.INBOUND)
        .exclude(author_type="system")
        .order_by("-created_at")
        .first()
    )
    people = list(thread.participants.exclude(role=Role.STAFF))
    if last is not None:
        authored = [
            p for p in people if (p.person_type, p.person_id) == (last.author_type, last.author_id)
        ]
        if authored:
            people = authored
    elif thread.kind == Kind.TUTOR_FAMILY:
        people = [p for p in people if p.role == Role.FAMILY]
    out = []
    for p in people:
        address = p.email if channel == Via.EMAIL else p.phone
        if not address:
            continue
        target = ("", "")
        if p.role == Role.FAMILY and thread.client_id:
            target = ("people.client", str(thread.client_id))
        elif p.role == Role.TUTOR:
            target = ("people.tutor", p.person_id)
        out.append(
            Recipient(
                kind=p.person_type,
                id=p.person_id,
                name=p.name,
                first_name=(p.name.split(" ")[0] if p.name else ""),
                email=p.email,
                phone=p.phone,
                target=target,
            )
        )
    return out


def _whatsapp_window_open(thread: Thread) -> bool:
    hours = int(settings.COMMS["WHATSAPP_WINDOW_HOURS"])
    return thread.messages.filter(
        direction=Direction.INBOUND,
        channel=Via.WHATSAPP,
        created_at__gte=now() - timedelta(hours=hours),
    ).exists()


def _attachments(ids: list[Any], *, user: Any) -> list[dict[str, Any]]:
    from tutortrack.core.models import StoredFile
    from tutortrack.core.storage.services import can_access

    wanted = [str(i) for i in ids][:10]
    files = list(StoredFile.objects.filter(pk__in=wanted))
    if len(files) != len(set(wanted)) or any(not can_access(user, f) for f in files):
        raise _invalid("attachments", _("An attachment couldn't be found."))
    return [
        {
            "id": str(f.pk),
            "filename": f.filename,
            "content_type": f.content_type,
            "size_bytes": f.size_bytes,
        }
        for f in files
    ]


def _link_files(entry: ThreadMessage) -> None:
    from tutortrack.core.models import StoredFile
    from tutortrack.core.storage.services import attach

    for stored in StoredFile.objects.filter(pk__in=[a["id"] for a in entry.attachments]):
        attach(stored, entry)


class _Blocked(Exception):
    def __init__(self, message: hooks.OutgoingMessage) -> None:
        super().__init__(message.type_key)
        self.message = message


def _safeguarded(fn: Any) -> Any:
    """Run ``fn`` in a transaction; if the safeguards block the message, keep the DSL's
    flag (it would roll back with the message) and refuse with a readable error."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            with transaction.atomic():
                return fn(*args, **kwargs)
        except _Blocked as blocked:
            hooks.run_pre_send(blocked.message)  # records the flag outside the rolled-back work
            raise _invalid(
                "body",
                _("This message can't be sent under your organisation's safeguarding policy."),
            ) from None

    return wrapper


@_safeguarded
def reply(
    thread: Thread,
    user: Any,
    *,
    body: str,
    channel: str | None = None,
    attachments: list[Any] | None = None,
    subject: str = "",
) -> ThreadMessage:
    """A staff reply: by the thread's channel unless another is chosen."""
    body = body.strip()
    if not body:
        raise _invalid("body", _("Write a message."))
    channel = channel or thread.channel or Via.CHAT
    if channel not in (Via.EMAIL, Via.SMS, Via.WHATSAPP, Via.CHAT):
        raise _invalid("channel", _("Choose how to send it."))
    files = _attachments(attachments or [], user=user)
    if files and channel not in (Via.EMAIL, Via.CHAT):
        raise _invalid("attachments", _("Attachments go by email or portal message."))
    if channel == Via.WHATSAPP and not _whatsapp_window_open(thread):
        raise _invalid(
            "channel",
            _("WhatsApp only allows free replies within 24 hours of their last message."),
        )
    recipients = _external_recipients(thread, channel) if channel != Via.CHAT else []
    if channel != Via.CHAT and not recipients:
        raise _invalid("channel", _("We don't have an address for them on that channel."))
    _run_safeguards(thread, user, body=body, subject=subject)
    entry = _record(
        thread,
        direction=Direction.OUTBOUND,
        channel=channel,
        author=Author.staff(user),
        body=body,
        subject=subject,
        attachments=files,
    )
    entry = _saved(entry)
    _link_files(entry)
    if channel == Via.CHAT:
        _notify_chat(entry)
        return entry
    from .services import queue_message

    title = subject or thread.subject or _("Message from %(org)s") % {"org": _org_name()}
    if channel == Via.EMAIL and not title.lower().startswith("re:") and thread.messages.count() > 1:
        title = f"Re: {title}"
    first = None
    for recipient in recipients:
        message = queue_message(
            type_key="inbox_reply",
            channel=channel,
            recipient=recipient,
            subject=title,
            body=body,
            dedupe_key=f"inbox:{entry.pk}:{recipient.kind}:{recipient.id}",
            related=("comms.threadmessage", str(entry.pk)),
            thread=thread,
            respect_quiet_hours=False,
        )
        first = first or message
    if first is not None:
        ThreadMessage.objects.filter(pk=entry.pk).update(message=first)
        entry.message = first
    return entry


def _org_name() -> str:
    from .services import _organisation_name

    return _organisation_name()


@transaction.atomic
def add_note(thread: Thread, user: Any, *, body: str) -> ThreadMessage:
    body = body.strip()
    if not body:
        raise _invalid("body", _("Write a note."))
    entry = _record(
        thread, direction=Direction.INTERNAL, channel=Via.NOTE, author=Author.staff(user), body=body
    )
    entry = _saved(entry)
    return entry


@transaction.atomic
def start_conversation(
    user: Any,
    *,
    kind: str,
    body: str,
    subject: str = "",
    client: Any = None,
    tutor: Any = None,
    channel: str = Via.CHAT,
) -> Thread:
    """Staff start a conversation with a family or a tutor (or both)."""
    thread = open_thread(kind=kind, subject=subject, client=client, tutor=tutor, channel=channel)
    assign(thread, user, by=user)
    reply(thread, user, body=body, channel=channel, subject=subject)
    return thread


@transaction.atomic
def assign(thread: Thread, assignee: Any, *, by: Any = None) -> Thread:
    if assignee is not None:
        from tutortrack.core.permissions import has_perm

        if not has_perm(assignee, "comms.inbox.reply"):
            raise _invalid("assignee", _("They can't reply to conversations."))
    with audit.track(thread, action="assign"):
        thread.assignee = assignee
        thread.save()
    publish(
        events.ThreadAssigned(
            subject_id=thread.pk, assignee_id=str(assignee.pk) if assignee else None
        )
    )
    return thread


@transaction.atomic
def snooze(thread: Thread, *, until: datetime) -> Thread:
    if until <= now():
        raise _invalid("until", _("Choose a time in the future."))
    with audit.track(thread, action="snooze"):
        thread.status, thread.snoozed_until = Thread.Status.SNOOZED, until
        thread.save()
    return thread


@transaction.atomic
def close(thread: Thread) -> Thread:
    with audit.track(thread, action="close"):
        thread.status, thread.closed_at, thread.snoozed_until = Thread.Status.CLOSED, now(), None
        thread.save()
    publish(events.ThreadClosed(subject_id=thread.pk))
    return thread


@transaction.atomic
def reopen(thread: Thread) -> Thread:
    with audit.track(thread, action="reopen"):
        thread.status, thread.closed_at, thread.snoozed_until = Thread.Status.OPEN, None, None
        thread.save()
    return thread


def mark_read(thread: Thread, user: Any) -> None:
    """Remember when ``user`` last read the thread (unread counts)."""
    updated = ThreadParticipant.objects.filter(thread=thread, user=user).update(last_read_at=now())
    if not updated:
        _participant(
            thread,
            Role.STAFF,
            "user",
            str(user.pk),
            user=user,
            name=user.get_full_name() or user.email,
            last_read_at=now(),
        )


# --- canned replies -----------------------------------------------------------------------------


@transaction.atomic
def save_canned_reply(
    row: CannedReply | None = None, *, title: str, body: str, shortcut: str = "", user: Any = None
) -> CannedReply:
    title, body = title.strip(), body.strip()
    if not title or not body:
        raise _invalid("title" if not title else "body", _("This field is required."))
    clash = CannedReply.objects.filter(title=title)
    if row is not None:
        clash = clash.exclude(pk=row.pk)
    if clash.exists():
        raise _invalid("title", _("A canned reply with this title already exists."))
    if row is None:
        row = CannedReply.objects.create(title=title, body=body, shortcut=shortcut, created_by=user)
        audit.record_create(row)
        return row
    with audit.track(row, action="update"):
        row.title, row.body, row.shortcut = title, body, shortcut
        row.save()
    return row


@transaction.atomic
def delete_canned_reply(row: CannedReply) -> None:
    audit.record(row, "delete")
    row.delete()


# --- portal side (E15-T09 families, E16 tutors) -------------------------------------------------


def _check_safeguarding(thread: Thread, body: str) -> None:
    if (
        thread.kind == Kind.TUTOR_FAMILY
        and get_setting("comms.block_contact_sharing")
        and "contact_details" in detect_flags(body)
    ):
        raise _invalid(
            "body", _("Please keep contact details out of messages; talk to us if you need them.")
        )


def _run_safeguards(thread: Thread, sender: Any, *, body: str, subject: str = "") -> None:
    """E29 messaging safeguards for a message a person writes, before it is stored."""
    if sender is None:
        return
    participants = tuple(
        (p.person_type, p.person_id) for p in thread.participants.exclude(person_type="external")
    )
    message = hooks.OutgoingMessage(
        type_key="inbox_message",
        category="service",
        channel=Via.CHAT,
        recipient_kind="thread",
        recipient_id=str(thread.pk),
        recipient_user_id=None,
        subject=subject,
        body=body,
        sender_user_id=str(sender.pk),
        participants=participants,
        source_type="comms.thread",
    )
    blocked = hooks.run_pre_send(message)
    if blocked:
        raise _Blocked(message)


@_safeguarded
def post_from_portal(
    thread: Thread, author: Author, *, body: str, attachments: list[Any] | None = None
) -> ThreadMessage:
    """A family member, student or tutor writes in the portal."""
    return _post(thread, author, body=body, attachments=attachments)


def _post(
    thread: Thread, author: Author, *, body: str, attachments: list[Any] | None = None
) -> ThreadMessage:
    body = body.strip()
    if not body:
        raise _invalid("body", _("Write a message."))
    _check_safeguarding(thread, body)
    _run_safeguards(thread, author.user, body=body)
    files = _attachments(attachments or [], user=author.user)
    entry = _record(
        thread,
        direction=Direction.INBOUND,
        channel=Via.CHAT,
        author=author,
        body=body,
        attachments=files,
    )
    entry = _saved(entry)
    _link_files(entry)
    if thread.kind == Kind.TUTOR_FAMILY:
        _notify_chat(entry)  # the tutor hears from the family and vice versa
    if author.user is not None:
        mark_read(thread, author.user)
    return entry


@_safeguarded
def start_from_portal(
    author: Author,
    *,
    kind: str,
    body: str,
    subject: str = "",
    client: Any = None,
    tutor: Any = None,
    student: Any = None,
    attachments: list[Any] | None = None,
) -> Thread:
    thread = open_thread(kind=kind, subject=subject, client=client, tutor=tutor)
    if student is not None:
        _participant(
            thread,
            Role.FAMILY,
            "student",
            str(student.pk),
            user=student.user,
            name=student.full_name,
        )
    _check_safeguarding(thread, body)
    _post(thread, author, body=body, attachments=attachments)
    return thread


# --- inbound email, texts and WhatsApp ----------------------------------------------------------


def _match_email(email: str) -> tuple[str, Any, Any]:
    """(kind, client, tutor) for a sender address."""
    from tutortrack.people.models import Contact, TutorProfile

    contact = (
        Contact.objects.filter(email__iexact=email, archived_at__isnull=True)
        .select_related("client")
        .first()
    )
    if contact is not None:
        return Kind.CLIENT, contact.client, None
    tutor = TutorProfile.objects.filter(email__iexact=email, archived_at__isnull=True).first()
    if tutor is not None:
        return Kind.TUTOR, None, tutor
    return Kind.OTHER, None, None


def _digits(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())


def _match_phone(phone: str) -> tuple[str, Any, Any, Author | None]:
    """(kind, client, tutor, author) for an inbound phone number (E.164)."""
    from tutortrack.people.models import Contact, TutorProfile

    from .channels import normalise_phone

    last = (
        Message.objects.filter(to=phone, recipient_type__in=["contact", "tutor"])
        .order_by("-created_at")
        .first()
    )
    if last is not None and last.recipient_type == "contact":
        contact = Contact.objects.filter(pk=last.recipient_id).select_related("client").first()
        if contact is not None:
            return (
                Kind.CLIENT,
                contact.client,
                None,
                Author("contact", str(contact.pk), contact.full_name),
            )
    if last is not None and last.recipient_type == "tutor":
        tutor = TutorProfile.objects.filter(pk=last.recipient_id).first()
        if tutor is not None:
            return Kind.TUTOR, None, tutor, Author("tutor", str(tutor.pk), tutor.full_name)
    tail = _digits(phone)[-6:]
    if tail:
        from tutortrack.core.context import require_organisation_id
        from tutortrack.tenancy.models import Organisation

        country = Organisation.objects.get(pk=require_organisation_id()).country
        for contact in Contact.objects.filter(
            mobile__contains=tail[-4:], archived_at__isnull=True
        ).select_related("client")[:50]:
            if normalise_phone(contact.mobile, country) == phone:
                return (
                    Kind.CLIENT,
                    contact.client,
                    None,
                    Author("contact", str(contact.pk), contact.full_name),
                )
        for tutor in TutorProfile.objects.filter(
            phone__contains=tail[-4:], archived_at__isnull=True
        )[:50]:
            if normalise_phone(tutor.phone, country) == phone:
                return Kind.TUTOR, None, tutor, Author("tutor", str(tutor.pk), tutor.full_name)
    return Kind.OTHER, None, None, None


def _author_by_email(thread: Thread, email: str, name: str) -> Author:
    participant = thread.participants.filter(email__iexact=email).first()
    if participant is not None:
        return Author(
            participant.person_type,
            participant.person_id,
            participant.name or name,
            participant.user,
        )
    return Author(
        "external", hashlib.sha256(email.lower().encode()).hexdigest()[:32], name or email
    )


@transaction.atomic
def receive_email(
    *,
    thread_id: str = "",
    from_email: str,
    from_name: str = "",
    subject: str = "",
    body: str,
    message_id: str = "",
    attachments: list[dict[str, Any]] | None = None,
) -> ThreadMessage | None:
    """An email to a thread's reply address (``thread_id``) or the organisation's inbox."""
    from_email = from_email.strip().lower()
    thread = Thread.objects.filter(pk=thread_id).first() if thread_id else None
    if thread is None:
        kind, client, tutor = _match_email(from_email)
        thread = _find_open(kind=kind, client=client, tutor=tutor, email=from_email)
        if thread is None:
            thread = open_thread(
                kind=kind,
                subject=subject,
                client=client,
                tutor=tutor,
                contact_name=from_name,
                contact_email=from_email if kind == Kind.OTHER else "",
                channel=Via.EMAIL,
            )
    author = _author_by_email(thread, from_email, from_name)
    entry = _record(
        thread,
        direction=Direction.INBOUND,
        channel=Via.EMAIL,
        author=author,
        body=body.strip() or _("(no text)"),
        subject=subject,
        provider_ref=f"email:{message_id}" if message_id else "",
    )
    if entry is not None and attachments:
        stored = _store_inbound_files(entry, attachments)
        if stored:
            ThreadMessage.objects.filter(pk=entry.pk).update(attachments=stored)
            entry.attachments = stored
    return entry


def _store_inbound_files(entry: ThreadMessage, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Save emailed attachments (base64 in the webhook) and queue their malware scan."""
    from django.contrib.contenttypes.models import ContentType

    from tutortrack.core.models import StoredFile
    from tutortrack.core.storage.client import bucket, s3_client
    from tutortrack.core.storage.services import _validate, complete_upload, safe_filename

    out: list[dict[str, Any]] = []
    total = 0
    for item in files[:10]:
        try:
            data = base64.b64decode(str(item.get("Content", "")), validate=True)
        except (binascii.Error, ValueError):
            continue
        content_type = str(item.get("ContentType") or "application/octet-stream")
        name = str(item.get("Name") or "attachment")[:255]
        total += len(data)
        if total > MAX_INBOUND_ATTACHMENT_BYTES:
            break
        try:
            _validate(content_type, len(data))
        except BusinessRuleViolation:
            continue
        folder = f"org/{entry.organisation_id}/{now():%Y/%m}/inbox/{uuid.uuid4().hex}"
        key = f"{folder}/{safe_filename(name)}"
        s3_client().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)
        stored = StoredFile.objects.create(
            filename=name,
            content_type=content_type,
            size_bytes=len(data),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            storage_key=key,
            visibility=StoredFile.Visibility.PRIVATE,
            owner_content_type=ContentType.objects.get_for_model(ThreadMessage),
            owner_object_id=str(entry.pk),
        )
        complete_upload(stored)
        out.append(
            {
                "id": str(stored.pk),
                "filename": name,
                "content_type": content_type,
                "size_bytes": len(data),
            }
        )
    return out


@transaction.atomic
def receive_text(
    *, channel: str, from_phone: str, body: str, provider_ref: str = ""
) -> ThreadMessage | None:
    """A text or WhatsApp message to the organisation's number (or a reply to the shared
    sender routed here)."""
    if channel not in (Channel.SMS, Channel.WHATSAPP):
        raise ValueError(channel)
    kind, client, tutor, author = _match_phone(from_phone)
    thread = _find_open(kind=kind, client=client, tutor=tutor, phone=from_phone)
    if thread is None:
        thread = open_thread(
            kind=kind,
            client=client,
            tutor=tutor,
            contact_phone=from_phone if kind == Kind.OTHER else "",
            contact_name=from_phone,
            channel=channel,
        )
    if author is None:
        author = Author(
            "external", hashlib.sha256(from_phone.encode()).hexdigest()[:32], from_phone
        )
    return _record(
        thread,
        direction=Direction.INBOUND,
        channel=channel,
        author=author,
        body=body.strip() or _("(no text)"),
        provider_ref=f"twilio:{provider_ref}" if provider_ref else "",
    )
