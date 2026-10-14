"""Messages and preferences in DSARs, erasure and retention (E29 Part 2, ADR 0028).

Erasure blanks the messages sent to the person (the log keeps that a message was sent,
not what it said or where), scrubs their name from messages to their family, and deletes
their preferences, in-app notifications and push devices. Suppression lists are kept:
they exist to honour opt-outs."""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    RetentionCategory,
    Section,
    register,
    register_retention,
)

from .models import (
    CommunicationPreference,
    InAppNotification,
    Message,
    MessageEvent,
    PushSubscription,
)

KINDS = {
    "contact": "people.contact",
    "tutor": "people.tutor",
    "user": "identity.user",
    "student": "people.student",
}


def _to_person(person: Person) -> Q:
    q = Q(pk__in=[])
    for kind, subject_type in KINDS.items():
        ids = person.of(subject_type)
        if ids:
            q |= Q(recipient_type=kind, recipient_id__in=ids)
    addresses = sorted(person.emails | person.phones)
    if addresses:
        q |= Q(to__in=addresses)
    return q


def _preferences(person: Person) -> Q:
    q = Q(pk__in=[])
    for kind, subject_type in KINDS.items():
        ids = person.of(subject_type)
        if ids:
            q |= Q(person_type=kind, person_id__in=ids)
    return q


def export(person: Person) -> list[Section]:
    messages = [
        {
            "id": str(m.pk),
            "type": m.type_key,
            "channel": m.channel,
            "to": m.to,
            "subject": m.subject,
            "body": m.body,
            "status": m.status,
            "sent_at": m.sent_at or m.created_at,
        }
        for m in Message.objects.filter(_to_person(person)).order_by("-created_at")[:2000]
    ]
    preferences = [
        {"id": str(p.pk), "category": p.category, "channels": p.channels}
        for p in CommunicationPreference.objects.filter(_preferences(person))
    ]
    return [
        Section("comms.messages", _("Messages we sent you"), messages),
        Section("comms.preferences", _("Communication preferences"), preferences),
    ]


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    mine = Message.objects.filter(_to_person(person))
    MessageEvent.objects.filter(message__in=mine).update(detail={})
    for message in mine.only("pk", "recipient_type", "recipient_id"):
        subject_type = KINDS.get(message.recipient_type, "")
        Message.objects.filter(pk=message.pk).update(
            to="",
            subject="",
            body="",
            recipient_name=ctx.label(subject_type, message.recipient_id, _("Erased person")),
        )
        out.anonymised += 1
    # Messages to the family that mention the person.
    households = sorted(person.context.get("people.client", set()))
    if households:
        for message in Message.objects.filter(
            target_type="people.client", target_id__in=households
        ).exclude(body=""):
            subject, body = ctx.scrub(message.subject), ctx.scrub(message.body)
            if (subject, body) != (message.subject, message.body):
                Message.objects.filter(pk=message.pk).update(subject=subject, body=body)
                out.anonymised += 1
    out.deleted += CommunicationPreference.objects.filter(_preferences(person)).delete()[0]
    users = person.of("identity.user")
    if users:
        out.deleted += InAppNotification.objects.filter(user_id__in=users).delete()[0]
        out.deleted += PushSubscription.objects.filter(user_id__in=users).delete()[0]
    return out


def _purge_messages(cutoff: datetime, dry_run: bool, limit: int) -> int:
    """The message log and in-app notifications older than the period (held people's
    messages are kept)."""
    from tutortrack.privacy.selectors import held_ids

    held = Q(pk__in=[])
    for kind, subject_type in KINDS.items():
        held_people = held_ids(subject_type)
        if held_people:
            held |= Q(recipient_type=kind, recipient_id__in=list(held_people))
    held_clients = held_ids("people.client")
    if held_clients:
        held |= Q(target_type="people.client", target_id__in=list(held_clients))
    messages = Message.objects.filter(created_at__lt=cutoff).exclude(held)
    notifications = InAppNotification.objects.filter(created_at__lt=cutoff)
    if dry_run:
        return messages.count() + notifications.count()
    ids = list(messages.values_list("pk", flat=True)[:limit])
    if ids:
        Message.objects.filter(pk__in=ids).delete()
    left = limit - len(ids)
    note_ids = list(notifications.values_list("pk", flat=True)[:left]) if left > 0 else []
    if note_ids:
        InAppNotification.objects.filter(pk__in=note_ids).delete()
    return len(ids) + len(note_ids)


register(Provider(key="comms", label="Messages", export=export, erase=erase, order=50))
register_retention(
    RetentionCategory(
        key="messages",
        label=gettext_lazy("Message log and in-app notifications"),
        default_days=365 * 2,
        purge=_purge_messages,
        order=30,
    )
)
