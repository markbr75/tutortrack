"""@mentions in notes notify the mentioned staff (FR-05-7, FR-13-2) on the E13 registry:
``note_mention``, in-app by default and optionally by email. Only people who may read the
note (its visibility and the record it is on) are told about it."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms.catalogue import SAMPLE_BASE, organisation, tenant_link, user_recipient
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, register

RECORD_PATHS = {
    "people.client": "/clients/{id}",
    "people.student": "/students/{id}",
    "people.tutor": "/tutors/{id}",
}


def load_note(pk: Any) -> Any:
    from .models import Note

    return Note.objects.filter(pk=pk).first()


def record_link(note: Any) -> str:
    """Where the note can be read: the record page (a contact's notes are on the family)."""
    target_id = note.target_id
    if note.target_type == "people.contact":
        from tutortrack.people.models import Contact

        contact = Contact.objects.filter(pk=note.target_id).first()
        if contact is None:
            return "/"
        return f"/clients/{contact.client_id}"
    path = RECORD_PATHS.get(note.target_type)
    return path.format(id=target_id) if path else "/"


def excerpt(html: str, size: int = 200) -> str:
    import nh3

    text = " ".join(nh3.clean(html, tags=set()).split())
    return text if len(text) <= size else text[: size - 1] + "…"


def may_read(user: Any, note: Any) -> bool:
    from tutortrack.core.permissions import has_perm

    from . import targets
    from .models import Note

    if not has_perm(user, "crm.note.view"):
        return False
    if note.visibility == Note.Visibility.STAFF and not has_perm(user, "crm.note.view_staff_only"):
        return False
    return targets.can_see(user, note.target_type, note.target_id)


def _resolve(note: Any) -> list[Delivery]:
    from tutortrack.identity.models import User

    from . import targets

    author = note.created_by.get_full_name() if note.created_by_id else ""
    record = targets.describe(note.target_type, note.target_id)
    link = record_link(note)
    out = []
    for user in User.objects.filter(pk__in=note.mentions or []).exclude(pk=note.created_by_id):
        if not may_read(user, note):
            continue
        r = user_recipient(user)
        out.append(
            Delivery(
                r,
                {
                    "organisation": organisation(),
                    "recipient": {"name": r.name, "first_name": r.first_name},
                    "mention": {
                        "author": author or str(_("A colleague")),
                        "record": record,
                        "excerpt": excerpt(note.body),
                        "link": tenant_link(link),
                    },
                },
            )
        )
    return out


register(
    NotificationType(
        key="note_mention",
        label=str(_("You were mentioned in a note")),
        category="staff",
        audience="staff",
        channels=("in_app", "email"),
        default_channels=("in_app",),
        resolve=_resolve,
        load=load_note,
        related_type="crm.note",
        variables=("mention.author", "mention.record", "mention.excerpt", "mention.link"),
        sample={
            **SAMPLE_BASE,
            "mention": {
                "author": "Sam Clarke",
                "record": "The Patel Family",
                "excerpt": "@Priya can you call them about mocks?",
                "link": "https://example.com",
            },
        },
        link=record_link,
    )
)

DEFAULTS[("note_mention", "in_app")] = (
    "{{ mention.author }} mentioned you on {{ mention.record }}",
    "{{ mention.excerpt }}",
)
DEFAULTS[("note_mention", "email")] = (
    "{{ mention.author }} mentioned you on {{ mention.record }}",
    "Hello {{ recipient.first_name }},\n\n{{ mention.author }} mentioned you in a note on "
    "{{ mention.record }}:\n\n{{ mention.excerpt }}\n\nRead it: {{ mention.link }}" + SIGN,
)
