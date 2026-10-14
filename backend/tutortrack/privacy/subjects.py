"""Data subjects: who can give consent or make a data subject request. Apps register
subject types with a check that the id belongs to the organisation in context (E05 adds
people.client / people.contact / people.student; E29 Part 2 adds tutors, applicants and
affiliates) and, optionally, a display label for staff screens."""

from __future__ import annotations

from collections.abc import Callable

_subjects: dict[str, Callable[[str], bool]] = {}
_labels: dict[str, Callable[[str], str]] = {}


def register(
    subject_type: str, exists: Callable[[str], bool], label: Callable[[str], str] | None = None
) -> None:
    _subjects[subject_type] = exists
    if label is not None:
        _labels[subject_type] = label


def register_label(subject_type: str, label: Callable[[str], str]) -> None:
    _labels[subject_type] = label


def is_valid(subject_type: str, subject_id: str) -> bool:
    check = _subjects.get(subject_type)
    if check is None:
        return False
    from django.core.exceptions import ValidationError

    try:
        return check(subject_id)
    except (ValueError, TypeError, ValidationError):  # not a valid id for that type
        return False


def label(subject_type: str, subject_id: str) -> str:
    fn = _labels.get(subject_type)
    return fn(subject_id) if fn is not None else ""


def subject_types() -> list[str]:
    return sorted(_subjects)


def _user_is_member(subject_id: str) -> bool:
    from tutortrack.identity.models import Membership

    return Membership.objects.filter(user_id=subject_id).exists()


def _user_label(subject_id: str) -> str:
    from tutortrack.identity.models import User

    user = User.objects.filter(pk=subject_id).first()
    return (user.get_full_name() or user.email) if user else ""


register("identity.user", _user_is_member, _user_label)
