"""Read-only iCalendar feeds (FR-08-11). RFC 5545 output, times in UTC."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from django.db.models import QuerySet

from tutortrack.core.time import now

from .models import ICalFeedToken, Lesson


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Lines longer than 75 octets continue on the next line after a space."""
    data = line.encode()
    if len(data) <= 75:
        return line
    parts: list[str] = []
    current = b""
    for char in line:
        encoded = char.encode()
        if len(current) + len(encoded) > (75 if not parts else 74):
            parts.append(current.decode())
            current = b""
        current += encoded
    parts.append(current.decode())
    return "\r\n ".join(parts)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def feed_lessons(feed: ICalFeedToken) -> QuerySet[Lesson]:
    window_start = now() - timedelta(days=60)
    qs = Lesson.objects.filter(start__gte=window_start).exclude(status=Lesson.Status.CANCELLED)
    if feed.kind == ICalFeedToken.Kind.TUTOR:
        qs = qs.filter(tutors__tutor_id=feed.subject_id)
    elif feed.kind == ICalFeedToken.Kind.CLIENT:
        qs = qs.filter(attendees__client_id=feed.subject_id)
    else:
        qs = qs.filter(attendees__student_id=feed.subject_id)
    return qs.distinct().select_related("location").order_by("start")


def render(lessons: Iterable[Lesson], *, name: str, host: str) -> str:
    stamp = _stamp(now())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TutorTrack//Schedule//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
    ]
    for lesson in lessons:
        where = "Online" if lesson.online else (lesson.location.name if lesson.location else "")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{lesson.pk}@{host}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_stamp(lesson.start)}",
            f"DTEND:{_stamp(lesson.end)}",
            f"SUMMARY:{_escape(lesson.title)}",
            *([f"LOCATION:{_escape(where)}"] if where else []),
            *([f"URL:{lesson.meeting_url}"] if lesson.meeting_url else []),
            f"STATUS:{'CONFIRMED' if lesson.status != Lesson.Status.CANCELLED else 'CANCELLED'}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
