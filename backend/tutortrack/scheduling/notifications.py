"""Staff alerts for the Phase 2 scheduling flows (E08-T13..T15), on the E13 registry.

Registered from here (not in ``comms.catalogue``) so the scheduling app owns them; E13
templates and preferences treat them like every other staff alert. Family- and
tutor-facing messages for reschedule requests and bookings follow the lesson events
(``lesson.rescheduled``, ``lesson.scheduled``) that E13 already sends.
"""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

from tutortrack.comms.catalogue import SAMPLE_ALERT, _alert
from tutortrack.comms.registry import NotificationType, register

ALERTS = (
    ("staff_time_off_requested", _("Time off waiting for approval"),
     "scheduling.availability.manage_others"),
    ("staff_reschedule_requested", _("Reschedule request waiting"), "scheduling.lesson.edit"),
    ("staff_booking_requested", _("Online booking waiting for approval"),
     "scheduling.lesson.create"),
)  # fmt: skip

for _key, _label, _code in ALERTS:
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
