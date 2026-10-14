"""Messages for classes and enrolment (E20), on the E13 registry.

Registered here so the courses app owns them; E13 templates and preferences treat them
like every other type. Waitlist offers reuse E17's ``waitlist_offer``.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms.catalogue import (
    SAMPLE_ALERT,
    SAMPLE_BASE,
    _alert,
    client_contacts,
    contact_recipient,
    organisation,
    tenant_link,
)
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, register


def _family(client: Any, extra: dict[str, Any]) -> list[Delivery]:
    return [
        Delivery(
            contact_recipient(c),
            {
                "organisation": organisation(),
                "recipient": {"name": c.full_name, "first_name": c.first_name},
                **extra,
            },
        )
        for c in client_contacts(client)
    ]


def _class_info(group_class: Any) -> dict[str, Any]:
    return {
        "course": group_class.course.name,
        "name": group_class.name,
        "term": group_class.term.name,
        "starts": group_class.start_date.isoformat(),
        "time": group_class.start_time.strftime("%H:%M"),
    }


def load_enrolment(pk: Any) -> Any:
    from .models import Enrolment

    return (
        Enrolment.objects.select_related(
            "group_class__course", "group_class__term", "student", "client"
        )
        .filter(pk=pk)
        .first()
    )


def _enrolment_confirmed(enrolment: Any) -> list[Delivery]:
    if enrolment is None:
        return []
    return _family(
        enrolment.client,
        {
            "enrolment": {
                "student": enrolment.student.first_name,
                "start_date": enrolment.start_date.isoformat(),
                "status": enrolment.get_status_display(),
            },
            "class": _class_info(enrolment.group_class),
        },
    )


def _rollover_invite(payload: Any) -> list[Delivery]:
    from .models import RolloverOffer

    offer_id, token, reminder = payload
    offer = (
        RolloverOffer.objects.select_related(
            "rollover", "to_class__course", "to_class__term", "student", "client"
        )
        .filter(pk=offer_id)
        .first()
    )
    if offer is None:
        return []
    return _family(
        offer.client,
        {
            "rollover": {
                "student": offer.student.first_name,
                "deadline": offer.rollover.deadline,
                "opt_out": offer.rollover.mode == "opt_out",
                "reminder": bool(reminder),
                "link": tenant_link(f"/re-enrol/{token}"),
            },
            "class": _class_info(offer.to_class),
        },
    )


SAMPLE_CLASS = {
    "course": "Year 6 11+ Prep",
    "name": "Saturday 10am",
    "term": "Spring 2027",
    "starts": "2027-01-09",
    "time": "10:00",
}

register(
    NotificationType(
        key="class_enrolment_confirmed",
        label=str(_("Class enrolment confirmed")),
        category="scheduling",
        audience="client",
        channels=("email", "in_app"),
        default_channels=("email",),
        resolve=_enrolment_confirmed,
        load=load_enrolment,
        related_type="courses.enrolment",
        variables=("enrolment.student", "enrolment.start_date", "class.course", "class.name",
                   "class.term", "class.starts", "class.time"),
        sample={**SAMPLE_BASE, "enrolment": {"student": "Arjun", "start_date": "2027-01-09",
                                             "status": "Enrolled"},
                "class": SAMPLE_CLASS},
        transactional=True,
    )
)  # fmt: skip
register(
    NotificationType(
        key="term_rollover_invite",
        label=str(_("Keep your place next term")),
        category="scheduling",
        audience="client",
        channels=("email", "sms"),
        default_channels=("email",),
        resolve=_rollover_invite,
        load=lambda pk: None,
        related_type="",
        variables=("rollover.student", "rollover.deadline", "rollover.link", "rollover.opt_out",
                   "rollover.reminder", "class.course", "class.name", "class.term"),
        sample={**SAMPLE_BASE, "rollover": {"student": "Arjun", "deadline": None,
                                            "opt_out": False, "reminder": False,
                                            "link": "https://example.com"},
                "class": SAMPLE_CLASS},
    )
)  # fmt: skip
for _key, _label, _code in (
    ("staff_class_below_minimum", _("A class is below its minimum size"), "courses.manage"),
    ("staff_class_full", _("A class is full"), "courses.manage"),
):
    register(
        NotificationType(
            key=_key,
            label=str(_label),
            category="staff",
            audience="staff",
            channels=("in_app", "email"),
            default_channels=("in_app",),
            resolve=_alert(_code),
            load=lambda pk: None,
            related_type="",
            variables=("alert.title", "alert.body", "alert.link"),
            sample=SAMPLE_ALERT,
            link=lambda payload: payload[2],
        )
    )
    DEFAULTS[(_key, "in_app")] = ("{{ alert.title }}", "{{ alert.body }}")
    DEFAULTS[(_key, "email")] = ("{{ alert.title }}", "{{ alert.body }}" + SIGN)

DEFAULTS[("class_enrolment_confirmed", "email")] = (
    "{{ enrolment.student }} is enrolled: {{ class.course }}",
    "Hello {{ recipient.first_name }},\n\n{{ enrolment.student }} has a place in "
    "{{ class.course }} ({{ class.name }}, {{ class.term }}) from {{ enrolment.start_date }} "
    "at {{ class.time }}." + SIGN,
)
DEFAULTS[("class_enrolment_confirmed", "in_app")] = (
    "{{ enrolment.student }} is enrolled",
    "{{ class.course }} ({{ class.name }}) from {{ enrolment.start_date }}",
)
DEFAULTS[("term_rollover_invite", "email")] = (
    "{% if rollover.reminder %}Reminder: {% endif %}{{ rollover.student }}'s place next term",
    "Hello {{ recipient.first_name }},\n\n{{ rollover.student }} can keep their place in "
    "{{ class.course }} ({{ class.name }}) for {{ class.term }}, starting {{ class.starts }}.\n\n"
    "{% if rollover.opt_out %}The place is kept unless you tell us otherwise"
    "{% else %}Please confirm you'd like to keep it{% endif %}"
    '{% if rollover.deadline %} by {{ rollover.deadline|datetime("short") }}{% endif %}: '
    "{{ rollover.link }}" + SIGN,
)
DEFAULTS[("term_rollover_invite", "sms")] = (
    "",
    "{{ organisation.name }}: keep {{ rollover.student }}'s place in {{ class.course }} next "
    "term? Reply here: {{ rollover.link }}",
)
