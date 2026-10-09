"""Who can give consent. Apps register subject types with a check that the id belongs to
the organisation in context (E05 adds people.client / people.contact / people.student)."""

from __future__ import annotations

from collections.abc import Callable

_subjects: dict[str, Callable[[str], bool]] = {}


def register(subject_type: str, exists: Callable[[str], bool]) -> None:
    _subjects[subject_type] = exists


def is_valid(subject_type: str, subject_id: str) -> bool:
    check = _subjects.get(subject_type)
    return check is not None and check(subject_id)


def subject_types() -> list[str]:
    return sorted(_subjects)


def _user_is_member(subject_id: str) -> bool:
    from tutortrack.identity.models import Membership

    return Membership.objects.filter(user_id=subject_id).exists()


register("identity.user", _user_is_member)
