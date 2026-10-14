"""Notification types added in Phase 2 (E13-T10/T11).

* Hidden types carry free-form messages through the delivery pipeline: broadcasts
  (marketing or service announcements) and inbox replies. They aren't configurable.
* ``inbox_new_message`` (staff), ``conversation_message_family`` and
  ``conversation_message_tutor`` tell people a portal message is waiting. They are keyed
  per thread and hour, so a busy conversation sends at most one email an hour (a light
  digest without a sweeper).
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from .catalogue import SAMPLE_BASE, organisation, staff_with, tenant_link, user_recipient
from .defaults import DEFAULTS, SIGN
from .registry import Delivery, NotificationType, Recipient, register

# --- loaders ------------------------------------------------------------------------------------


def load_broadcast(pk: str) -> Any:
    from .models import Broadcast

    return Broadcast.objects.filter(pk=pk).first()


def broadcast_attachments(broadcast: Any) -> list[tuple[str, bytes, str]]:
    return _files(broadcast.attachment_ids or [])


def load_thread_message(pk: str) -> Any:
    from .models import ThreadMessage

    return ThreadMessage.objects.select_related("thread").filter(pk=pk).first()


def thread_message_attachments(entry: Any) -> list[tuple[str, bytes, str]]:
    return _files([a.get("id") for a in entry.attachments or [] if a.get("id")])


def _files(ids: list[Any]) -> list[tuple[str, bytes, str]]:
    from tutortrack.core.models import StoredFile
    from tutortrack.core.storage.client import bucket, s3_client

    out = []
    for stored in StoredFile.objects.filter(pk__in=ids):
        if not stored.is_downloadable:
            continue
        body = s3_client().get_object(Bucket=bucket(), Key=stored.storage_key)["Body"]
        out.append((stored.filename, body.read(), stored.content_type))
    return out


def _none(_subject: Any) -> list[Delivery]:
    return []


for _key, _label, _category, _transactional, _load, _files_for, _related in (
    (
        "broadcast_marketing",
        _("Broadcast (marketing)"),
        "marketing",
        False,
        load_broadcast,
        broadcast_attachments,
        "comms.broadcast",
    ),
    (
        "broadcast_operational",
        _("Broadcast (service announcement)"),
        "account",
        True,
        load_broadcast,
        broadcast_attachments,
        "comms.broadcast",
    ),
    (
        "inbox_reply",
        _("Reply from the inbox"),
        "messages",
        True,
        load_thread_message,
        thread_message_attachments,
        "comms.threadmessage",
    ),
):
    register(
        NotificationType(
            key=_key,
            label=str(_label),
            category=_category,
            audience="client",
            channels=("email", "sms", "whatsapp"),
            default_channels=("email",),
            resolve=_none,
            load=_load,
            related_type=_related,
            transactional=_transactional,
            attachments=_files_for,
            hidden=True,
        )
    )


# --- "you have a new message" -------------------------------------------------------------------

SAMPLE_MESSAGE = {
    "author": "Priya Patel",
    "preview": "Could we move Thursday's lesson to 5pm?",
    "subject": "Thursday's lesson",
    "link": "https://brightminds.tutortrack.app/portal/messages",
}
MESSAGE_VARS = ("message.author", "message.preview", "message.subject", "message.link")


def _message_context(entry: Any, link: str) -> dict[str, Any]:
    return {
        "organisation": organisation(),
        "message": {
            "author": entry.author_name,
            "preview": " ".join(entry.body.split())[:200],
            "subject": entry.thread.subject,
            "link": link,
        },
    }


def _deliveries(recipients: list[Recipient], context: dict[str, Any]) -> list[Delivery]:
    return [
        Delivery(r, {**context, "recipient": {"name": r.name, "first_name": r.first_name}})
        for r in recipients
    ]


def _staff_new_message(entry: Any) -> list[Delivery]:
    from tutortrack.identity.models import User

    thread = entry.thread
    if thread.assignee_id:
        assignee = User.objects.filter(pk=thread.assignee_id, is_active=True).first()
        recipients = [user_recipient(assignee)] if assignee else []
    else:
        recipients = staff_with("comms.inbox.assign")
    recipients = [r for r in recipients if r.user_id != str(entry.author_user_id or "")]
    return _deliveries(
        recipients, _message_context(entry, tenant_link(f"/inbox?thread={thread.pk}"))
    )


def _participants(entry: Any, role: str, path: str) -> list[Delivery]:
    from .models import ThreadParticipant

    out = []
    for p in ThreadParticipant.objects.filter(thread_id=entry.thread_id, role=role).select_related(
        "user"
    ):
        if p.user_id and p.user_id == entry.author_user_id:
            continue
        if (p.person_type, p.person_id) == (entry.author_type, entry.author_id):
            continue
        thread = entry.thread
        target = ("", "")
        if role == "family" and thread.client_id:
            target = ("people.client", str(thread.client_id))
        elif role == "tutor" and thread.tutor_id:
            target = ("people.tutor", str(thread.tutor_id))
        out.append(
            Recipient(
                kind=p.person_type,
                id=p.person_id,
                name=p.name,
                first_name=(p.name.split(" ")[0] if p.name else ""),
                email=p.email,
                user_id=str(p.user_id) if p.user_id else None,
                target=target,
            )
        )
    return _deliveries(out, _message_context(entry, tenant_link(path)))


def _family_new_message(entry: Any) -> list[Delivery]:
    return _participants(entry, "family", f"/portal/messages?thread={entry.thread_id}")


def _tutor_new_message(entry: Any) -> list[Delivery]:
    return _participants(entry, "tutor", f"/portal/tutor/messages?thread={entry.thread_id}")


SAMPLE = {**SAMPLE_BASE, "message": SAMPLE_MESSAGE}

register(
    NotificationType(
        key="inbox_new_message",
        label=str(_("New message in the inbox (to staff)")),
        category="messages",
        audience="staff",
        channels=("in_app", "email"),
        default_channels=("in_app",),
        resolve=_staff_new_message,
        load=load_thread_message,
        related_type="comms.threadmessage",
        variables=MESSAGE_VARS,
        sample=SAMPLE,
        link=lambda entry: f"/inbox?thread={entry.thread_id}",
    )
)
register(
    NotificationType(
        key="conversation_message_family",
        label=str(_("New portal message (to families)")),
        category="messages",
        audience="client",
        channels=("email", "in_app"),
        default_channels=("email", "in_app"),
        resolve=_family_new_message,
        load=load_thread_message,
        related_type="comms.threadmessage",
        variables=MESSAGE_VARS,
        sample=SAMPLE,
        link=lambda entry: f"/portal/messages?thread={entry.thread_id}",
    )
)
register(
    NotificationType(
        key="conversation_message_tutor",
        label=str(_("New portal message (to tutors)")),
        category="messages",
        audience="tutor",
        channels=("email", "in_app"),
        default_channels=("in_app", "push"),
        resolve=_tutor_new_message,
        load=load_thread_message,
        related_type="comms.threadmessage",
        variables=MESSAGE_VARS,
        sample=SAMPLE,
        link=lambda entry: f"/portal/tutor/messages?thread={entry.thread_id}",
    )
)

for _key in ("inbox_new_message", "conversation_message_family", "conversation_message_tutor"):
    DEFAULTS[(_key, "in_app")] = ("New message from {{ message.author }}", "{{ message.preview }}")
    DEFAULTS[(_key, "email")] = (
        "New message from {{ message.author }}",
        "Hello {{ recipient.first_name }},\n\n{{ message.author }} wrote:\n"
        "{{ message.preview }}\n\nRead and reply: {{ message.link }}" + SIGN,
    )
