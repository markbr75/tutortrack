"""Guardian-managed student logins in DSARs and erasure (E29; gap batch G2). Erasing the
student removes the login and switches off its sign-in."""

from __future__ import annotations

from django.utils.translation import gettext as _

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    Section,
    register,
)

from .models import StudentLogin


def export(person: Person) -> list[Section]:
    rows = [
        {
            "username": login.username,
            "created_at": login.created_at,
            "pin_changed_at": login.pin_changed_at,
        }
        for login in StudentLogin.objects.filter(student_id__in=person.of("people.student"))
    ]
    return [Section("portal.student_logins", _("Student logins"), rows)]


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    for login in StudentLogin.objects.select_related("user").filter(
        student_id__in=person.of("people.student")
    ):
        user = login.user
        login.delete()
        user.is_active = False
        user.set_unusable_password()
        user.save(update_fields=["is_active", "password"])
        out.deleted += 1
    return out


register(Provider(key="portal", label="Portal logins", export=export, erase=erase, order=90))
