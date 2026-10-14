"""The platform's own messages to organisations, sent through E13 comms (G6).

``platform_customer_notice``: a breach, security, service or legal notice to the
organisation's owners and admins (``platform_admin.notices``). Hidden from the
organisation's notification settings, so it can't be switched off, and transactional.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms.catalogue import SAMPLE_BASE, organisation
from tutortrack.comms.defaults import DEFAULTS
from tutortrack.comms.registry import Delivery, NotificationType, register


def _to_owners_and_admins(payload: Any) -> list[Delivery]:
    from .notices import recipients

    title, body, link = payload
    return [
        Delivery(
            r,
            {
                "organisation": organisation(),
                "recipient": {"name": r.name, "first_name": r.first_name},
                "alert": {"title": title, "body": body, "link": link},
            },
        )
        for r in recipients()
    ]


register(
    NotificationType(
        key="platform_customer_notice",
        label=str(_("Notice from TutorTrack (breach, security or service)")),
        category="staff",
        audience="staff",
        channels=("in_app", "email"),
        default_channels=("in_app", "email"),
        resolve=_to_owners_and_admins,
        load=lambda pk: None,
        related_type="",
        variables=("alert.title", "alert.body"),
        sample={**SAMPLE_BASE, "alert": {"title": "Notice", "body": "Details", "link": ""}},
        transactional=True,
        hidden=True,
    )
)
DEFAULTS[("platform_customer_notice", "in_app")] = ("{{ alert.title }}", "{{ alert.body }}")
DEFAULTS[("platform_customer_notice", "email")] = (
    "{{ alert.title }}",
    "Hello {{ recipient.first_name }},\n\n{{ alert.body }}\n\nTutorTrack",
)
