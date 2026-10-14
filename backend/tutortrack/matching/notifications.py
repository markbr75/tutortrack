"""Messages for shared shortlists (E19-T08) on the E13 registry: ``shortlist_shared`` (the
family's link) and ``staff_shortlist_choice`` (staff hear which tutor the family chose)."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms import catalogue
from tutortrack.comms.catalogue import SAMPLE_BASE, contact_recipient, organisation, tenant_link
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, register


def _shared(payload: Any) -> list[Delivery]:
    from .models import ShortlistShare

    share_id, token = payload
    share = (
        ShortlistShare.objects.select_related("contact", "job")
        .filter(pk=share_id, status=ShortlistShare.Status.ACTIVE)
        .first()
    )
    if share is None or share.contact is None:
        return []
    contact = share.contact
    return [
        Delivery(
            contact_recipient(contact),
            {
                "organisation": organisation(),
                "recipient": {"name": contact.full_name, "first_name": contact.first_name},
                "shortlist": {
                    "count": len(share.tutors),
                    "message": share.message,
                    "expires": share.expires_at.date().isoformat(),
                    "link": tenant_link(f"/shortlists/{token}"),
                },
            },
        )
    ]


register(
    NotificationType(
        key="shortlist_shared",
        label=str(_("Tutor shortlist for a family")),
        category="account",
        audience="client",
        channels=("email", "sms"),
        default_channels=("email",),
        resolve=_shared,
        load=lambda pk: None,
        related_type="",
        variables=(
            "shortlist.count",
            "shortlist.message",
            "shortlist.expires",
            "shortlist.link",
        ),
        sample={
            **SAMPLE_BASE,
            "shortlist": {
                "count": 3,
                "message": "Here are three tutors we think would suit Arjun.",
                "expires": "2026-10-28",
                "link": "https://example.com",
            },
        },
    )
)
register(
    NotificationType(
        key="staff_shortlist_choice",
        label=str(_("A family chose a tutor from a shortlist")),
        category="staff",
        audience="staff",
        channels=("in_app", "email"),
        default_channels=("in_app", "email"),
        resolve=catalogue._alert("matching.offer.manage"),
        load=lambda pk: None,
        related_type="",
        variables=("alert.title", "alert.body", "alert.link"),
        sample=catalogue.SAMPLE_ALERT,
        link=lambda payload: payload[2],
    )
)

DEFAULTS[("shortlist_shared", "email")] = (
    "Tutors for you to choose from",
    "Hello {{ recipient.first_name }},\n\n"
    "{% if shortlist.message %}{{ shortlist.message }}\n\n{% endif %}"
    "We've picked {{ shortlist.count }} tutor{% if shortlist.count != 1 %}s{% endif %} "
    "who could help. "
    "Have a look and choose the one you'd like: {{ shortlist.link }}\n\n"
    "The link works until {{ shortlist.expires }}." + SIGN,
)
DEFAULTS[("shortlist_shared", "sms")] = (
    "",
    "{{ organisation.name }}: choose your tutor here (until {{ shortlist.expires }}): "
    "{{ shortlist.link }}",
)
DEFAULTS[("staff_shortlist_choice", "in_app")] = ("{{ alert.title }}", "{{ alert.body }}")
DEFAULTS[("staff_shortlist_choice", "email")] = (
    "{{ alert.title }}",
    "{{ alert.body }}\n\n{{ alert.link }}" + SIGN,
)
