"""Interview booking through the slot engine, with an automatic video link (FR-18-2, gap
batch G5a).

Staff send a *booking link*: the applicant picks any free slot of the interviewer inside a
date window. Free time comes from the E08 slot engine (``scheduling.availability``):

* an interviewer who is also a tutor here uses their weekly availability, lessons, time
  off and connected calendars (exactly what lesson booking uses);
* other staff use the organisation's interview hours (``recruitment.interview_hours``,
  weekdays and local times), minus organisation closures;
* in both cases their other booked interviews are busy time.

Once an interview is booked, ``InterviewWorkflow`` creates the video meeting (E22, the
organisation's default provider through ``calendar_sync.meetings``), emails the applicant
the time and link, alerts recruiters, and reminds the applicant a day before.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db import connection, transaction
from django.utils.translation import gettext as _

from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import compliance, events
from .models import Interview

STEP_MINUTES = 30
MAX_SLOTS = 120
MAX_WINDOW_DAYS = 28
REMINDER_BEFORE = timedelta(hours=24)


def _org() -> Any:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    return Organisation.objects.get(pk=require_organisation_id())


def _office_hours(start: date, end: date, tz: str) -> list[tuple[datetime, datetime]]:
    from tutortrack.scheduling.recurrence import to_utc

    spec = get_setting("recruitment.interview_hours") or {}
    days = {int(d) for d in spec.get("days", [0, 1, 2, 3, 4])}
    try:
        opens = time.fromisoformat(str(spec.get("start", "09:00")))
        closes = time.fromisoformat(str(spec.get("end", "17:00")))
    except ValueError:
        opens, closes = time(9), time(17)
    out = []
    day = start
    while day <= end:
        if day.weekday() in days and opens < closes:
            out.append((to_utc(day, opens, tz), to_utc(day, closes, tz)))
        day += timedelta(days=1)
    return out


def interviewer_slots(
    interviewer: Any,
    *,
    start: date,
    end: date,
    minutes: int,
    exclude: Interview | None = None,
) -> list[datetime]:
    """Start times the interviewer is free for ``minutes`` between two local dates."""
    from tutortrack.people.models import TutorProfile
    from tutortrack.scheduling import availability

    tz = _org().timezone
    tutor = TutorProfile.objects.filter(membership__user=interviewer).first()
    if tutor is not None and availability.has_template(tutor.pk):
        free = availability.available_intervals(tutor.pk, start, end)
        busy = availability.busy_intervals(tutor.pk, free[0][0], free[-1][1]) if free else []
    else:
        free = _office_hours(start, end, tz)
        busy = availability.closure_intervals(free[0][0], free[-1][1]) if free else []
    if not free:
        return []
    others = Interview.objects.filter(
        interviewer=interviewer,
        status=Interview.Status.BOOKED,
        start__lt=free[-1][1],
        start__gte=free[0][0] - timedelta(hours=4),
    )
    if exclude is not None:
        others = others.exclude(pk=exclude.pk)
    busy = [*busy, *((i.start, i.start + timedelta(minutes=i.minutes)) for i in others)]
    min_notice = int(get_setting("scheduling.min_notice_hours"))
    slots = availability.fit_slots(
        free,
        busy,
        duration_minutes=minutes,
        step_minutes=STEP_MINUTES,
        earliest=now() + timedelta(hours=min_notice),
    )
    return [s.start for s in slots[:MAX_SLOTS]]


def check_window(start: date, end: date) -> None:
    today = compliance.today()
    if start < today or end < start:
        raise BusinessRuleViolation(
            _("Choose dates from today onwards."),
            extra={"errors": {"window_start": [_("Check the dates.")]}},
        )
    if (end - start).days > MAX_WINDOW_DAYS:
        raise BusinessRuleViolation(
            _("Offer at most four weeks of dates."),
            extra={"errors": {"window_end": [_("Too far ahead.")]}},
        )


def options_for(interview: Interview) -> list[str]:
    """The times the applicant can choose from right now."""
    if interview.mode != Interview.Mode.AVAILABILITY:
        return list(interview.options)
    if interview.status != Interview.Status.PROPOSED or not interview.window_start:
        return []
    today = compliance.today()
    start = max(interview.window_start, today)
    end = interview.window_end or start
    if end < start:
        return []
    return [
        s.isoformat()
        for s in interviewer_slots(
            interview.interviewer, start=start, end=end, minutes=interview.minutes
        )
    ]


def lock_interviewer(interviewer_id: Any) -> None:
    """Serialise bookings for one interviewer (two applicants can't take the same slot)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", [f"interviewer:{interviewer_id}"]
        )


def is_free(interview: Interview, start: datetime) -> bool:
    zone = ZoneInfo(_org().timezone)
    day = start.astimezone(zone).date()
    if (
        interview.window_start
        and interview.window_end
        and not interview.window_start <= day <= interview.window_end
    ):
        return False
    slots = interviewer_slots(
        interview.interviewer, start=day, end=day, minutes=interview.minutes, exclude=interview
    )
    return start in slots


# --- after booking (activities of ``InterviewWorkflow``) ------------------------------------


def interview_snapshot(interview_id: Any) -> dict[str, Any]:
    interview = Interview.objects.filter(pk=interview_id).first()
    if interview is None or interview.status != Interview.Status.BOOKED or not interview.start:
        return {"booked": False, "start": "", "video": False}
    return {
        "booked": True,
        "start": interview.start.isoformat(),
        "video": bool(get_setting("recruitment.interview_video")) and not interview.meeting_url,
    }


def provision_meeting(interview_id: Any) -> str:
    """Create the video meeting for a booked interview. Idempotent: a link already set (by
    hand or by an earlier attempt) is kept."""
    from tutortrack.calendar_sync import meetings

    interview = (
        Interview.objects.select_related("application", "interviewer")
        .filter(pk=interview_id)
        .first()
    )
    if interview is None or interview.status != Interview.Status.BOOKED or not interview.start:
        return "skipped"
    if interview.meeting_url:
        return "kept"
    host = interview.interviewer
    provider, info = meetings.create_standalone_meeting(
        key=f"interview-{interview.pk}",
        topic=_("Interview: %(name)s") % {"name": interview.application.full_name},
        start=interview.start,
        end=interview.start + timedelta(minutes=interview.minutes),
        timezone=_org().timezone,
        host_user_id=host.pk,
        host_name=host.get_full_name() or host.email,
    )
    if info is None:
        return "none"
    with transaction.atomic():
        updated = Interview.objects.filter(pk=interview.pk, meeting_url="").update(
            meeting_url=info.join_url[:1000],
            host_url=(info.host_url or info.join_url)[:1000],
            video_provider=provider,
            meeting_external_id=info.external_id[:200],
            updated_at=now(),
        )
        if updated:
            publish(
                events.InterviewMeetingCreated(
                    subject_id=interview.application_id,
                    interview_id=str(interview.pk),
                    provider=provider,
                ),
                dedupe_key=f"interview-meeting:{interview.pk}",
            )
    return "created" if updated else "kept"


def confirm(interview_id: Any) -> bool:
    """The applicant gets the time and link; recruiters hear it was booked."""
    from tutortrack.comms import services as comms

    interview = Interview.objects.select_related("application").filter(pk=interview_id).first()
    if interview is None or interview.status != Interview.Status.BOOKED or not interview.start:
        return False
    comms.notify("interview_confirmed", interview.pk, key=f"interview-confirmed:{interview.pk}")
    comms.notify(
        "staff_interview_booked",
        (
            _("Interview booked: %(name)s") % {"name": interview.application.full_name},
            interview.start.isoformat(),
            f"/recruitment/{interview.application_id}",
        ),
        key=f"interview-booked:{interview.pk}",
    )
    return True


def remind(interview_id: Any, start: str) -> bool:
    from tutortrack.comms import services as comms

    interview = Interview.objects.filter(pk=interview_id).first()
    if (
        interview is None
        or interview.status != Interview.Status.BOOKED
        or not interview.start
        or interview.start.isoformat() != start
    ):
        return False
    comms.notify("interview_reminder", interview.pk, key=f"interview-reminder:{interview.pk}")
    return True
