"""Extension points other apps plug into without scheduling depending on them (E22).

* **Busy sources**: functions ``(tutor_ids, start, end) -> {tutor_id: [(start, end)]}``
  returning time a tutor is busy outside TutorTrack (connected calendars). Conflict checks
  (a hard ``tutor_external_busy`` conflict), free slots and matching's batched fit all
  include it.
* **Join links**: ``(lesson, role, person_id) -> JoinLink | None`` gives the
  role-specific online meeting link (tutor/host vs student/family); without a resolver
  the lesson's ``meeting_url`` is used. Portals and reminders call ``join_link``.

``calendar_sync`` registers both in its ``AppConfig.ready``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

Interval = tuple[datetime, datetime]
BusySource = Callable[[list[str], datetime, datetime], dict[str, list[Interval]]]


@dataclass(frozen=True)
class JoinLink:
    url: str
    opens_at: datetime | None = None
    provider: str = ""
    role: str = "participant"  # host | participant


JoinResolver = Callable[[Any, str, str], JoinLink | None]

_busy_sources: list[BusySource] = []
_join_resolvers: list[JoinResolver] = []


def register_busy_source(source: BusySource) -> BusySource:
    if source not in _busy_sources:
        _busy_sources.append(source)
    return source


def register_join_resolver(resolver: JoinResolver) -> JoinResolver:
    if resolver not in _join_resolvers:
        _join_resolvers.append(resolver)
    return resolver


def external_busy(
    tutor_ids: Iterable[Any], start: datetime, end: datetime
) -> dict[str, list[Interval]]:
    ids = [str(t) for t in tutor_ids]
    out: dict[str, list[Interval]] = defaultdict(list)
    if not ids or not _busy_sources:
        return out
    for source in _busy_sources:
        for tutor_id, intervals in source(ids, start, end).items():
            out[str(tutor_id)].extend(intervals)
    return out


def join_link(lesson: Any, role: str = "participant", person_id: str = "") -> JoinLink | None:
    """The link ``role`` (``host`` for tutors, ``participant`` for families) uses to join
    ``lesson`` online, or None for in-person lessons."""
    if not lesson.online:
        return None
    for resolver in _join_resolvers:
        found = resolver(lesson, role, person_id)
        if found is not None:
            return found
    if not lesson.meeting_url:
        return None
    from tutortrack.tenancy.settings_service import get_setting

    try:
        minutes = int(get_setting("integrations.join_window_minutes"))
    except KeyError:
        minutes = 10
    return JoinLink(
        lesson.meeting_url, lesson.start - timedelta(minutes=minutes), lesson.meeting_provider
    )
