"""Proposal messages (E17-T09) on the E13 registry: ``proposal_sent`` (the family's link
with the PDF attached; also the reminder) and ``staff_proposal_response`` (accepted or
declined)."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms import catalogue
from tutortrack.comms.catalogue import SAMPLE_BASE, contact_recipient, organisation, tenant_link
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, register


def _load(pk: Any) -> Any:
    from .models import Proposal

    return Proposal.objects.select_related("contact").filter(pk=pk).first()


def _resolve(notice: Any) -> list[Delivery]:
    from .models import Proposal

    proposal = _load(notice.pk)
    if proposal is None or proposal.contact is None or proposal.status != Proposal.Status.SENT:
        return []
    contact = proposal.contact
    return [
        Delivery(
            contact_recipient(contact),
            {
                "organisation": organisation(),
                "recipient": {"name": contact.full_name, "first_name": contact.first_name},
                "proposal": {
                    "number": proposal.number,
                    "title": proposal.title,
                    "expires": proposal.expires_at.date().isoformat()
                    if proposal.expires_at
                    else "",
                    "link": tenant_link(f"/proposals/{notice.token}"),
                    "reminder": bool(notice.reminder),
                },
            },
        )
    ]


def _attachments(proposal: Any) -> list[tuple[str, bytes, str]]:
    from .proposals import pdf

    return [(f"{proposal.number}.pdf", pdf(proposal), "application/pdf")]


register(
    NotificationType(
        key="proposal_sent",
        label=str(_("Proposal for a family")),
        category="account",
        audience="client",
        channels=("email",),
        default_channels=("email",),
        resolve=_resolve,
        load=_load,
        related_type="leads.proposal",
        variables=(
            "proposal.number",
            "proposal.title",
            "proposal.expires",
            "proposal.link",
            "proposal.reminder",
        ),
        sample={
            **SAMPLE_BASE,
            "proposal": {
                "number": "PRO-000001",
                "title": "GCSE Maths tuition for Arjun",
                "expires": "2026-10-28",
                "link": "https://example.com",
                "reminder": False,
            },
        },
        attachments=_attachments,
        transactional=True,
    )
)
register(
    NotificationType(
        key="staff_proposal_response",
        label=str(_("A family answered a proposal")),
        category="staff",
        audience="staff",
        channels=("in_app", "email"),
        default_channels=("in_app", "email"),
        resolve=catalogue._alert("leads.enquiry.view"),
        load=lambda pk: None,
        related_type="",
        variables=("alert.title", "alert.body", "alert.link"),
        sample=catalogue.SAMPLE_ALERT,
        link=lambda payload: payload[2],
    )
)

DEFAULTS[("proposal_sent", "email")] = (
    "{% if proposal.reminder %}Reminder: {% endif %}{{ proposal.title }}",
    "Hello {{ recipient.first_name }},\n\n"
    "{% if proposal.reminder %}Just a reminder: our proposal is open until "
    "{{ proposal.expires }}.{% else %}Thank you for your enquiry. Our proposal "
    "{{ proposal.number }} is attached.{% endif %}\n\n"
    "Read it and accept online: {{ proposal.link }}" + SIGN,
)
DEFAULTS[("staff_proposal_response", "in_app")] = ("{{ alert.title }}", "{{ alert.body }}")
DEFAULTS[("staff_proposal_response", "email")] = (
    "{{ alert.title }}",
    "{{ alert.body }}\n\n{{ alert.link }}" + SIGN,
)
