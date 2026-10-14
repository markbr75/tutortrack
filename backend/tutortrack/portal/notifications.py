"""Portal messages on the E13 registry (gap batch G2): the invitation a parent sends to
another guardian from the portal (FR-15-8)."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms.catalogue import SAMPLE_BASE, contact_recipient, organisation, tenant_link
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, register


def _guardian_invite(payload: Any) -> list[Delivery]:
    from tutortrack.people.models import Contact

    contact_id, token, inviter = payload
    contact = Contact.objects.filter(pk=contact_id).first()
    if contact is None or not contact.email:
        return []
    return [
        Delivery(
            contact_recipient(contact),
            {
                "organisation": organisation(),
                "recipient": {"name": contact.full_name, "first_name": contact.first_name},
                "invite": {
                    "inviter": inviter,
                    "link": tenant_link(f"/accept-invite?token={token}"),
                },
            },
        )
    ]


register(
    NotificationType(
        key="guardian_invite",
        label=str(_("Invitation from another guardian")),
        category="account",
        audience="client",
        channels=("email",),
        default_channels=("email",),
        resolve=_guardian_invite,
        load=lambda pk: None,
        related_type="",
        variables=("invite.inviter", "invite.link"),
        sample={**SAMPLE_BASE, "invite": {"inviter": "Priya Patel", "link": "https://example.com"}},
        transactional=True,
    )
)

DEFAULTS[("guardian_invite", "email")] = (
    "{{ invite.inviter }} invited you to {{ organisation.name }}'s portal",
    "Hello {{ recipient.first_name }},\n\n{{ invite.inviter }} has added you as a guardian and "
    "invited you to the family portal, where you can see lessons, reports and invoices. "
    "Accept the invitation within 7 days: {{ invite.link }}" + SIGN,
)
