"""Tutor access toggles (FR-03-6): organisation settings → extra Tutor grants."""

from __future__ import annotations

from .roles import Grant

# setting key -> grants added to the Tutor role when the toggle is on.
TOGGLES: dict[str, tuple[str, ...]] = {
    "tutor_access.message_clients_directly": ("comms.message.send:own",),
    "tutor_access.create_lessons": ("scheduling.lesson.create:own",),
    "tutor_access.reschedule_lessons": ("scheduling.lesson.reschedule:own",),
    "tutor_access.cancel_lessons": ("scheduling.lesson.cancel:own",),
    "tutor_access.edit_rates": ("billing.rates.edit:own", "billing.rates.view_pay:own"),
    "tutor_access.view_other_calendars": ("scheduling.lesson.view_calendar:all",),
    "tutor_access.add_students": ("people.student.create:own",),
}
CONTACT_LEVELS: dict[str, tuple[str, ...]] = {
    "none": (),
    "phone": ("people.contact.view_phone:own",),
    "full": ("people.contact.view_phone:own", "people.contact.view_details:own"),
}


def toggle_grants() -> list[Grant]:
    """Extra grants for tutors in the organisation in context."""
    from tutortrack.tenancy.settings_service import area_values

    values = area_values("tutor_access")
    raw: list[str] = []
    for key, grants in TOGGLES.items():
        if values.get(key):
            raw.extend(grants)
    raw.extend(CONTACT_LEVELS.get(str(values.get("tutor_access.client_contact_details")), ()))
    return [Grant.parse(r) for r in raw]
