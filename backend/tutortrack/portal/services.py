"""Portal writes (E15): announcements and household profile edits. Everything else reuses
the owning app's services (cancellation, reports, payments) after a household check."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.people import services as people
from tutortrack.people.models import Contact, Student

from .events import SensitiveUpdated
from .models import Announcement

CONTACT_EDITABLE = {"first_name", "last_name", "phone", "mobile", "receives_reminders",
                    "receives_invoices", "receives_reports", "receives_marketing"}  # fmt: skip
STUDENT_EDITABLE = {"preferred_name", "school", "year_group", "learning_needs"}


@transaction.atomic
def save_announcement(
    *,
    title: str,
    body: str,
    audience: str = Announcement.Audience.EVERYONE,
    published_at: datetime | None = None,
    expires_at: datetime | None = None,
    branch: Any = None,
    announcement: Announcement | None = None,
    user: Any = None,
) -> Announcement:
    if expires_at and expires_at <= (published_at or now()):
        raise BusinessRuleViolation(
            _("It must expire after it's published."),
            extra={"errors": {"expires_at": [_("Choose a later date.")]}},
        )
    row = announcement or Announcement(created_by=user)
    action = "update" if announcement else "create"
    with audit.track(row, action=action):
        row.title, row.body, row.audience = title, body, audience
        row.published_at = published_at or row.published_at or now()
        row.expires_at = expires_at
        row.branch = branch
        row.save()
    return row


@transaction.atomic
def update_contact(contact: Contact, **changes: Any) -> Contact:
    unknown = set(changes) - CONTACT_EDITABLE
    if unknown:
        raise BusinessRuleViolation(_("Those details can't be changed here."))
    return people.update_contact(contact, **changes)


@transaction.atomic
def update_student(student: Student, **changes: Any) -> Student:
    unknown = set(changes) - STUDENT_EDITABLE
    if unknown:
        raise BusinessRuleViolation(_("Those details can't be changed here."))
    sensitive = "learning_needs" in changes and changes["learning_needs"] != student.learning_needs
    people.update_student(student, **changes)
    if sensitive:
        publish(SensitiveUpdated(subject_id=student.pk, name=student.full_name))
    return student
