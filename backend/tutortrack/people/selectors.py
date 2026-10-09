"""People reads (E05)."""

from __future__ import annotations

import re
from typing import Any

from django.db.models import F, Func, Q

from .models import Client, Contact, Student, TutorProfile


class DigitsOnly(Func):
    """SQL: the value with every non-digit removed."""

    function = "regexp_replace"
    template = "%(function)s(%(expressions)s, '\\D', '', 'g')"


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone)[-9:]  # compare the national significant part


def possible_duplicates(
    *,
    email: str = "",
    phone: str = "",
    first_name: str = "",
    last_name: str = "",
    date_of_birth: str = "",
) -> list[dict[str, Any]]:
    """Records that look like the person being created (FR-05-13)."""
    found: list[dict[str, Any]] = []
    email = email.strip().lower()
    digits = _digits(phone) if phone else ""
    if email:
        for c in Contact.objects.filter(email=email, archived_at__isnull=True)[:10]:
            found.append(
                {
                    "type": "contact",
                    "id": c.pk,
                    "name": c.full_name,
                    "client_id": c.client_id,
                    "reason": "email",
                }
            )
        for t in TutorProfile.objects.filter(email=email)[:5]:
            found.append(
                {
                    "type": "tutor",
                    "id": t.pk,
                    "name": t.full_name,
                    "client_id": None,
                    "reason": "email",
                }
            )
    if len(digits) >= 7:
        contacts = Contact.objects.annotate(
            phone_digits=DigitsOnly(F("phone")), mobile_digits=DigitsOnly(F("mobile"))
        ).filter(Q(phone_digits__endswith=digits) | Q(mobile_digits__endswith=digits))
        for c in contacts[:10]:
            found.append(
                {"type": "contact", "id": c.pk, "name": c.full_name, "client_id": c.client_id,
                 "reason": "phone"}
            )  # fmt: skip
    if first_name and last_name:
        students = Student.objects.filter(
            first_name__iexact=first_name.strip(), last_name__iexact=last_name.strip()
        )
        if date_of_birth:
            students = students.filter(date_of_birth=date_of_birth)
        for s in students[:10]:
            found.append(
                {
                    "type": "student",
                    "id": s.pk,
                    "name": s.full_name,
                    "client_id": s.client_id,
                    "reason": "name and date of birth" if date_of_birth else "name",
                }
            )
    unique: dict[tuple[str, Any], dict[str, Any]] = {}
    for row in found:
        unique.setdefault((row["type"], row["id"]), row)
    return list(unique.values())


def client_summary(client: Client) -> dict[str, Any]:
    """Computed figures for a client page. Balance/credit/overdue arrive with E10 and
    next/last lesson with E08; they are reported as ``None`` until then."""
    return {
        "active_students": client.students.filter(
            archived_at__isnull=True, status__in=["active", "trial"]
        ).count(),
        "balance": None,
        "available_credit": None,
        "overdue": None,
        "lifetime_revenue": None,
        "next_lesson_at": None,
        "last_lesson_at": None,
    }
