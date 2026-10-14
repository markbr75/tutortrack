"""Children's privacy (E29-T10, FR-29-7).

* **COPPA** (``privacy.coppa``: automatically for US organisations): a student under 13
  gets a portal login only after verifiable parental consent is on record (consent type
  ``parental-consent``, given by a parent: a signed form recorded by staff, or the parent
  in their portal). ``people.services.invite_to_portal`` calls ``require_login_allowed``.
* **UK Age Appropriate Design Code** (``privacy.child_defaults``, on by default): under-18s
  get high-privacy defaults: marketing consent can't be recorded for them, marketing
  messages to them are blocked (comms pre-send hook) and nothing profiles them.

A student whose date of birth is unknown is treated as a child (the safe default).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

CHILD_AGE = 18
COPPA_AGE = 13
PARENTAL_CONSENT = "parental-consent"
MARKETING_CATEGORIES = frozenset({"marketing_email", "marketing_sms"})


class ParentalConsentRequired(BusinessRuleViolation):
    problem_type = "parental-consent-required"
    title = "Parental consent is required"


def age_on(dob: date | None, today: date) -> int | None:
    if dob is None:
        return None
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def student_age(student: Any) -> int | None:
    return age_on(getattr(student, "date_of_birth", None), now().date())


def is_child(student: Any) -> bool:
    age = student_age(student)
    return age is None or age < CHILD_AGE


def coppa_applies() -> bool:
    mode = get_setting("privacy.coppa")
    if mode == "on":
        return True
    if mode == "off":
        return False
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    return org.country == "US" or org.region == "us"


def needs_parental_consent(student: Any) -> bool:
    if not coppa_applies():
        return False
    age = student_age(student)
    return age is None or age < COPPA_AGE


def has_parental_consent(student: Any) -> bool:
    from .services import is_granted

    return is_granted("people.student", str(student.pk), PARENTAL_CONSENT)


def require_login_allowed(student: Any) -> None:
    """Called before a student is invited to the portal."""
    if needs_parental_consent(student) and not has_parental_consent(student):
        raise ParentalConsentRequired(
            _(
                "This student is under 13: record verifiable parental consent (for example a "
                "signed form) before giving them a login."
            ),
            extra={"code": "parental_consent_required"},
        )


def child_defaults_on() -> bool:
    return bool(get_setting("privacy.child_defaults"))


def check_consent_allowed(subject_type: str, subject_id: str, category: str, granted: bool) -> None:
    """AADC: no marketing to children, so marketing consent can't be granted for one."""
    if not granted or category not in MARKETING_CATEGORIES or subject_type != "people.student":
        return
    if not child_defaults_on():
        return
    from tutortrack.people.models import Student

    student = Student.objects.filter(pk=subject_id).first()
    if student is not None and is_child(student):
        raise BusinessRuleViolation(
            _("Marketing consent can't be recorded for children."),
            extra={"code": "child_marketing"},
        )


def child_for_user(user_id: str | None) -> Any:
    """The under-18 student this login belongs to, if any."""
    if not user_id:
        return None
    from tutortrack.people.models import Student

    student = Student.objects.filter(user_id=user_id).first()
    return student if student is not None and is_child(student) else None


def defaults_for(student: Any) -> dict[str, Any]:
    """What applies to this student (shown on the student's privacy panel)."""
    child = is_child(student)
    return {
        "age": student_age(student),
        "is_child": child,
        "high_privacy_defaults": child and child_defaults_on(),
        "coppa_applies": needs_parental_consent(student),
        "parental_consent": has_parental_consent(student),
    }
