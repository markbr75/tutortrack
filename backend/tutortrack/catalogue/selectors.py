"""Catalogue reads used by other apps."""

from __future__ import annotations

from .models import Level, Subject


def match_subject(subject: str, level: str = "") -> tuple[Subject | None, Level | None]:
    """The catalogue subject and level with these names (case-insensitive), if any."""
    found = Subject.objects.filter(name__iexact=subject.strip()).first()
    if found is None:
        return None, None
    lvl = found.levels.filter(name__iexact=level.strip()).first() if level.strip() else None
    return found, lvl


def resolve_subject_ids(
    subject_id: str | None, level_id: str | None
) -> tuple[Subject | None, Level | None]:
    """Look up a subject/level pair chosen from the catalogue; the level must belong to it."""
    subject = Subject.objects.filter(pk=subject_id).first() if subject_id else None
    level = (
        Level.objects.filter(pk=level_id).select_related("subject").first() if level_id else None
    )
    if level is not None:
        if subject is not None and level.subject_id != subject.pk:
            return subject, None
        subject = subject or level.subject
    return subject, level
