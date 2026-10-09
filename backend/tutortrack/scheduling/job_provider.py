"""Lesson data for jobs (E07 ``LessonsProvider``), completing E08-T10."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from tutortrack.core.money import Money, sum_money
from tutortrack.core.time import now
from tutortrack.jobs.lessons import AffectedLesson, LessonStats

from . import conflicts
from .models import Lesson


def _hours(lessons: Any) -> Decimal:
    return sum(
        (Decimal((lesson.end - lesson.start).total_seconds()) / 3600 for lesson in lessons),
        Decimal(0),
    )


class SchedulingLessonsProvider:
    def stats(self, job: Any) -> LessonStats:
        lessons = list(
            job.lessons.exclude(status=Lesson.Status.CANCELLED).prefetch_related(
                "attendees", "tutors"
            )
        )
        completed = [lesson for lesson in lessons if lesson.status == Lesson.Status.COMPLETED]
        upcoming = sorted(
            lesson.start
            for lesson in lessons
            if lesson.status == Lesson.Status.PLANNED and lesson.start >= now()
        )
        past = sorted(lesson.start for lesson in completed)
        currency = job.currency
        revenue = sum_money(
            (
                a.charge_amount
                for lesson in completed
                for a in lesson.attendees.all()
                if a.charge_amount and a.chargeable
            ),
            currency,
        )
        cost = sum_money(
            (
                t.pay_amount
                for lesson in completed
                for t in lesson.tutors.all()
                if t.pay_amount and t.payable
            ),
            currency,
        )
        return LessonStats(
            planned=len(lessons),
            completed=len(completed),
            hours_delivered=_hours(completed).quantize(Decimal("0.01")),
            revenue=revenue if completed else Money.zero(currency),
            tutor_cost=cost if completed else Money.zero(currency),
            next_lesson_at=upcoming[0] if upcoming else None,
            last_lesson_at=past[-1] if past else None,
        )

    def hours_scheduled(self, job: Any, start: date | None, end: date | None) -> Decimal:
        lessons = job.lessons.exclude(status=Lesson.Status.CANCELLED)
        zone = ZoneInfo(str(job.branch.timezone))
        if start is not None:
            lessons = lessons.filter(start__gte=datetime.combine(start, time.min, tzinfo=zone))
        if end is not None:
            lessons = lessons.filter(
                start__lt=datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone)
            )
        return _hours(lessons)

    def future_lessons(
        self, job: Any, tutor: Any, from_date: date, new_tutor: Any | None
    ) -> list[AffectedLesson]:
        zone = ZoneInfo(str(job.branch.timezone))
        lessons = job.lessons.filter(
            tutors__tutor=tutor,
            status=Lesson.Status.PLANNED,
            lock_state=Lesson.Lock.UNLOCKED,
            start__gte=datetime.combine(from_date, time.min, tzinfo=zone),
        ).order_by("start")
        out = []
        for lesson in lessons:
            conflict = ""
            if new_tutor is not None:
                found = conflicts.hard(
                    conflicts.check(
                        start=lesson.start,
                        end=lesson.end,
                        tz=lesson.timezone,
                        tutors=[new_tutor],
                        exclude_lesson_ids=[lesson.pk],
                    )
                )
                conflict = found[0].message if found else ""
            out.append(AffectedLesson(str(lesson.pk), lesson.start, conflict))
        return out
