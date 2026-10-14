"""A direct channel to students (G4, FR-13-2 and FR-13-5).

Lesson messages (booked, moved, cancelled, reminders) can also go to the student
themselves when the organisation turns it on (``comms.student_direct``): adult learners
only, or students aged 13 and over. A student is reached at their own login (email,
in-app, push) or, for adult learners, the contact who *is* the student.

E29 children's rules always apply:

* under-13s, and students whose date of birth isn't known, are only ever reached through
  their parents or guardians: no student recipient is built for them, and the pre-send
  hook below blocks anything addressed to them directly (a conversation with a parent
  or guardian on it is left to E29's thread rules);
* no marketing to under-18s, whatever ``privacy.child_defaults`` says (the E29 hook
  blocks it when child defaults are on; this one always does for students).
"""

from __future__ import annotations

from typing import Any

from tutortrack.tenancy.settings_service import get_setting

from .hooks import OutgoingMessage, register_pre_send
from .registry import Recipient

GUARDIANS_ONLY_AGE = 13
ADULT_AGE = 18


def _age(student: Any) -> int | None:
    from tutortrack.privacy.children import student_age

    return student_age(student)


def student_recipient(student: Any) -> Recipient | None:
    """The student as a recipient, or None when messages go to their family only."""
    mode = str(get_setting("comms.student_direct") or "off")
    if mode == "off":
        return None
    age = _age(student)
    if age is None or age < GUARDIANS_ONLY_AGE:
        return None
    if mode == "adults" and age < ADULT_AGE:
        return None
    email = phone = ""
    user_id = None
    locale = ""
    user = student.user if student.user_id else None
    if user is not None and user.is_active:
        email, user_id, locale = user.email, str(user.pk), str(user.locale or "")
    contact = student.contact if student.contact_id else None
    if contact is not None:
        email = email or contact.email
        phone = contact.mobile
        locale = locale or contact.language or ""
    if not (email or phone or user_id):
        return None
    return Recipient(
        kind="student",
        id=str(student.pk),
        name=student.full_name,
        first_name=student.preferred_name or student.first_name,
        email=email,
        phone=phone,
        user_id=user_id,
        target=("people.student", str(student.pk)),
        locale=locale,
    )


def lesson_students(lesson: Any, existing: list[Recipient]) -> list[Recipient]:
    """Students on ``lesson`` who get its messages themselves, skipping anyone whose
    address already gets them as a family contact (adult learners)."""
    taken = {r.email.lower() for r in existing if r.email}
    out = []
    for attendee in lesson.attendees.all():
        r = student_recipient(attendee.student)
        if r is not None and not (r.email and r.email.lower() in taken):
            out.append(r)
    return out


def check_student(message: OutgoingMessage) -> str:
    """Pre-send hook: nothing goes straight to an under-13 (or a student of unknown age),
    and no marketing goes to an under-18."""
    if message.recipient_kind != "student":
        return ""
    if any(kind == "contact" for kind, _ref in message.participants):
        return ""  # a conversation with a parent or guardian on it (E29's rules apply)
    from tutortrack.people.models import Student

    student = Student.objects.filter(pk=message.recipient_id).first()
    if student is None:
        return ""
    age = _age(student)
    if age is None or age < GUARDIANS_ONLY_AGE:
        return "children:guardians_only"
    if message.category == "marketing" and age < ADULT_AGE:
        return "children:no_marketing"
    return ""


register_pre_send(check_student)
