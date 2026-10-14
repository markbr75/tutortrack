"""Support chat replies reach the person by email and push (G6, E30 FR-30-5).

``support_reply``: TutorTrack support answered a conversation; the person who opened it
hears by in-app notification, email and Web Push (E16) with a short excerpt and a link that
opens the chat. Hidden from the notification settings (it is the person's own conversation)
and transactional.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms.catalogue import SAMPLE_BASE, organisation, user_recipient
from tutortrack.comms.defaults import DEFAULTS
from tutortrack.comms.registry import Delivery, NotificationType, register

EXCERPT = 280


def _to_opener(payload: Any) -> list[Delivery]:
    from tutortrack.identity.models import User

    title, body, link, user_id = payload
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return []
    recipient = user_recipient(user)
    return [
        Delivery(
            recipient,
            {
                "organisation": organisation(),
                "recipient": {"name": recipient.name, "first_name": recipient.first_name},
                "alert": {"title": title, "body": body, "link": link},
            },
        )
    ]


register(
    NotificationType(
        key="support_reply",
        label=str(_("A reply from TutorTrack support")),
        category="account",
        audience="staff",
        channels=("in_app", "email", "push"),
        default_channels=("in_app", "email", "push"),
        resolve=_to_opener,
        load=lambda pk: None,
        related_type="",
        variables=("alert.title", "alert.body", "alert.link"),
        sample={**SAMPLE_BASE, "alert": {"title": "Support replied", "body": "", "link": "/"}},
        transactional=True,
        link=lambda payload: payload[2],
        hidden=True,
    )
)
DEFAULTS[("support_reply", "in_app")] = ("{{ alert.title }}", "{{ alert.body }}")
DEFAULTS[("support_reply", "push")] = ("{{ alert.title }}", "{{ alert.body }}")
DEFAULTS[("support_reply", "email")] = (
    "{{ alert.title }}",
    "Hello {{ recipient.first_name }},\n\n{{ alert.body }}\n\n{{ alert.link }}\n\nTutorTrack",
)


def notify_reply(conversation: Any, message: Any) -> None:
    """After commit, in the conversation's organisation (once per message)."""
    from django.db import transaction

    from tutortrack.comms.catalogue import tenant_link
    from tutortrack.comms.services import notify
    from tutortrack.core.context import tenant_context

    if not conversation.opened_by_id:
        return
    org_id = conversation.organisation_id
    body = message.body
    message_id = str(message.pk)
    excerpt = body if len(body) <= EXCERPT else body[: EXCERPT - 1] + "…"
    title = str(_("TutorTrack support replied: %(subject)s") % {"subject": conversation.subject})
    user_id = str(conversation.opened_by_id)
    conversation_id = str(conversation.pk)

    def go() -> None:
        with tenant_context(org_id):
            link = tenant_link(f"/?support={conversation_id}")
            notify(
                "support_reply",
                (title, excerpt, link, user_id),
                key=f"support-reply:{message_id}",
            )

    transaction.on_commit(go)
