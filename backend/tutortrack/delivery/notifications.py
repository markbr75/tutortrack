"""Lesson feedback messages (FR-09-9, E09-T09) on the E13 registry.

``lesson_feedback_request`` is in the ``reports`` category and is not transactional, so a
family's channel preferences and unsubscribes apply. ``staff_lesson_feedback_low`` alerts
staff who can see feedback when a lesson is rated low."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.comms import catalogue
from tutortrack.comms.catalogue import SAMPLE_BASE, contact_recipient, organisation, tenant_link
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, register


def _request(payload: Any) -> list[Delivery]:
    from .models import LessonFeedback

    feedback_id, token = payload
    feedback = (
        LessonFeedback.objects.select_related("lesson", "student", "tutor", "contact")
        .filter(pk=feedback_id, status=LessonFeedback.Status.SENT)
        .first()
    )
    if feedback is None or feedback.contact is None:
        return []
    contact = feedback.contact
    tutor = feedback.tutor
    return [
        Delivery(
            contact_recipient(contact),
            {
                "organisation": organisation(),
                "recipient": {"name": contact.full_name, "first_name": contact.first_name},
                "feedback": {
                    "student": feedback.student.preferred_name or feedback.student.first_name,
                    "tutor": (tutor.display_name or tutor.first_name) if tutor else "",
                    "lesson": feedback.lesson.title,
                    "date": feedback.lesson_date.isoformat(),
                    "link": tenant_link(f"/feedback/{token}"),
                },
            },
        )
    ]


register(
    NotificationType(
        key="lesson_feedback_request",
        label=str(_("Lesson feedback request")),
        category="reports",
        audience="client",
        channels=("email", "sms"),
        default_channels=("email",),
        resolve=_request,
        load=lambda pk: None,
        related_type="",
        variables=(
            "feedback.student",
            "feedback.tutor",
            "feedback.lesson",
            "feedback.date",
            "feedback.link",
        ),
        sample={
            **SAMPLE_BASE,
            "feedback": {
                "student": "Arjun",
                "tutor": "Nia",
                "lesson": "GCSE Maths",
                "date": "2026-10-14",
                "link": "https://example.com",
            },
        },
    )
)
register(
    NotificationType(
        key="staff_lesson_feedback_low",
        label=str(_("Lesson rated low by a family")),
        category="staff",
        audience="staff",
        channels=("in_app", "email"),
        default_channels=("in_app", "email"),
        resolve=catalogue._alert("delivery.feedback.view"),
        load=lambda pk: None,
        related_type="",
        variables=("alert.title", "alert.body", "alert.link"),
        sample=catalogue.SAMPLE_ALERT,
        link=lambda payload: payload[2],
    )
)

DEFAULTS[("lesson_feedback_request", "email")] = (
    "How was {{ feedback.student }}'s lesson?",
    "Hello {{ recipient.first_name }},\n\nHow did {{ feedback.student }}'s lesson"
    "{% if feedback.tutor %} with {{ feedback.tutor }}{% endif %} on {{ feedback.date }} go? "
    "Tap a star to tell us; it takes a few seconds: {{ feedback.link }}" + SIGN,
)
DEFAULTS[("lesson_feedback_request", "sms")] = (
    "",
    "{{ organisation.name }}: how was {{ feedback.student }}'s lesson on {{ feedback.date }}? "
    "Rate it here: {{ feedback.link }}",
)
DEFAULTS[("staff_lesson_feedback_low", "in_app")] = ("{{ alert.title }}", "{{ alert.body }}")
DEFAULTS[("staff_lesson_feedback_low", "email")] = (
    "{{ alert.title }}",
    "{{ alert.body }}\n\n{{ alert.link }}" + SIGN,
)
