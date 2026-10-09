"""What jobs need to know about lessons, supplied by scheduling (E08).

Jobs come before lessons in the build order, so scheduling registers a provider here
(``set_provider``) instead of jobs importing scheduling. Until then every job has no lessons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

from tutortrack.core.money import Money


@dataclass
class LessonStats:
    planned: int = 0
    completed: int = 0
    hours_delivered: Decimal = Decimal(0)
    revenue: Money | None = None
    tutor_cost: Money | None = None
    next_lesson_at: datetime | None = None
    last_lesson_at: datetime | None = None


@dataclass
class AffectedLesson:
    id: str
    starts_at: datetime
    conflict: str = ""  # why the new tutor can't take it, if they can't


@dataclass
class ReplacementPreview:
    lessons: list[AffectedLesson] = field(default_factory=list)

    @property
    def conflicts(self) -> list[AffectedLesson]:
        return [lesson for lesson in self.lessons if lesson.conflict]


class LessonsProvider(Protocol):
    def stats(self, job: Any) -> LessonStats: ...

    def hours_scheduled(self, job: Any, start: date | None, end: date | None) -> Decimal: ...

    def future_lessons(
        self, job: Any, tutor: Any, from_date: date, new_tutor: Any | None
    ) -> list[AffectedLesson]: ...


class _NoLessons:
    def stats(self, job: Any) -> LessonStats:
        return LessonStats()

    def hours_scheduled(self, job: Any, start: date | None, end: date | None) -> Decimal:
        return Decimal(0)

    def future_lessons(
        self, job: Any, tutor: Any, from_date: date, new_tutor: Any | None
    ) -> list[AffectedLesson]:
        return []


_provider: LessonsProvider = _NoLessons()


def set_provider(provider: LessonsProvider) -> None:
    global _provider
    _provider = provider


def provider() -> LessonsProvider:
    return _provider
