"""Digest emails (G4, FR-13-2 and FR-13-7): the tutor's daily agenda, a family's weekly
schedule and a daily digest of unread messages.

Each is an E13 notification type (off until the organisation turns it on in Settings →
Notifications; templates are editable as usual). People choose for themselves whether
they get it, at what local time and, for the weekly one, on which day
(``DigestPreference``; no row = the organisation's defaults from ``comms.digest_*``).

Sending: a Celery beat task runs every 15 minutes per organisation (``fan_out_per_org``,
like lesson reminders) and sends each digest to the people whose local time has just
passed their chosen time (a one-hour window, so a missed run is caught by the next). The
dedupe key is the person's local date, so each digest goes at most once a day. There are
no ``next_*_at`` columns and nothing to sweep: the time is worked out from the clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.tenancy.settings_service import get_setting

from .catalogue import (
    SAMPLE_BASE,
    contact_recipient,
    organisation,
    tenant_link,
    tutor_recipient,
    user_recipient,
)
from .defaults import DEFAULTS, SIGN
from .models import DigestPreference
from .registry import Delivery, NotificationType, register

Kind = DigestPreference.Kind
WINDOW = timedelta(hours=1)
TYPE_FOR = {
    Kind.TUTOR_AGENDA: "tutor_daily_agenda",
    Kind.WEEKLY_SCHEDULE: "client_weekly_schedule",
    Kind.MESSAGE_DIGEST: "message_digest",
}
MESSAGE_TYPES = ("conversation_message_tutor", "conversation_message_family", "inbox_new_message")
# Which digests each kind of person can choose.
KINDS_FOR = {
    "tutor": (Kind.TUTOR_AGENDA, Kind.MESSAGE_DIGEST),
    "contact": (Kind.WEEKLY_SCHEDULE,),
    "user": (Kind.MESSAGE_DIGEST,),
}


# --- notification types ---------------------------------------------------------------------------


def _lesson_rows(lessons: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "title": lesson.title,
            "start": lesson.start,
            "end": lesson.end,
            "timezone": lesson.timezone,
            "location": lesson.location.name if lesson.location else "",
            "online": lesson.online,
            "students": ", ".join(a.student.full_name for a in lesson.attendees.all()),
        }
        for lesson in lessons
    ]


def _agenda(payload: Any) -> list[Delivery]:
    tutor, day, lessons = payload
    r = tutor_recipient(tutor)
    context = {
        "organisation": organisation(),
        "recipient": {"name": r.name, "first_name": r.first_name},
        "agenda": {
            "date": day,
            "count": len(lessons),
            "lessons": _lesson_rows(lessons),
            "link": tenant_link("/portal/tutor"),
        },
    }
    return [Delivery(r, context)]


def _weekly(payload: Any) -> list[Delivery]:
    contact, week_start, lessons = payload
    r = contact_recipient(contact)
    context = {
        "organisation": organisation(),
        "recipient": {"name": r.name, "first_name": r.first_name},
        "week": {
            "start": week_start,
            "count": len(lessons),
            "lessons": _lesson_rows(lessons),
            "link": tenant_link("/portal/schedule"),
        },
    }
    return [Delivery(r, context)]


def _messages(payload: Any) -> list[Delivery]:
    recipient, rows = payload
    context = {
        "organisation": organisation(),
        "recipient": {"name": recipient.name, "first_name": recipient.first_name},
        "digest": {
            "count": len(rows),
            "messages": [{"title": n.title, "body": n.body[:200]} for n in rows],
        },
    }
    return [Delivery(recipient, context)]


SAMPLE_ROWS = [
    {
        "title": "GCSE Maths \N{EN DASH} Arjun Patel",
        "start": "2026-11-02T16:30:00+00:00",
        "end": "2026-11-02T17:30:00+00:00",
        "timezone": "Europe/London",
        "location": "Bright Minds Centre",
        "online": False,
        "students": "Arjun Patel",
    }
]
for _key, _label, _audience, _category, _resolve, _vars, _sample in (
    (
        "tutor_daily_agenda",
        _l("Daily agenda for tutors"),
        "tutor",
        "scheduling",
        _agenda,
        ("agenda.date", "agenda.count", "agenda.lessons", "agenda.link"),
        {"agenda": {"date": "2026-11-02", "count": 1, "lessons": SAMPLE_ROWS, "link": "https://x"}},
    ),
    (
        "client_weekly_schedule",
        _l("Weekly schedule for families"),
        "client",
        "scheduling",
        _weekly,
        ("week.start", "week.count", "week.lessons", "week.link"),
        {"week": {"start": "2026-11-02", "count": 1, "lessons": SAMPLE_ROWS, "link": "https://x"}},
    ),
    (
        "message_digest",
        _l("Daily digest of unread messages"),
        "staff",
        "messages",
        _messages,
        ("digest.count", "digest.messages"),
        {"digest": {"count": 1, "messages": [{"title": "New message from Priya", "body": "Hi"}]}},
    ),
):
    register(
        NotificationType(
            key=_key,
            label=str(_label),
            category=_category,
            audience=_audience,
            channels=("email",),
            default_channels=("email",),
            resolve=_resolve,
            load=lambda pk: None,
            related_type="",
            variables=_vars,
            sample={**SAMPLE_BASE, **_sample},
            default_enabled=False,  # organisations turn digests on
        )
    )

LESSON_LINE = (
    "{% for l in LIST %}\n- {{ l.start|time }}{% if l.end %}\N{EN DASH}{{ l.end|time }}{% endif %} "
    "{{ l.title }}{% if l.online %} (online){% elif l.location %}, {{ l.location }}{% endif %}"
    "{% endfor %}"
)
DEFAULTS[("tutor_daily_agenda", "email")] = (
    "Your lessons on {{ agenda.date|date }}",
    "Hello {{ recipient.first_name }},\n\nYou have {{ agenda.count }} lesson(s) on "
    "{{ agenda.date|date }}:\n"
    + LESSON_LINE.replace("LIST", "agenda.lessons")
    + "\n\nOpen your day: {{ agenda.link }}"
    + SIGN,
)
DEFAULTS[("client_weekly_schedule", "email")] = (
    "Lessons in the week of {{ week.start|date }}",
    "Hello {{ recipient.first_name }},\n\nHere are the {{ week.count }} lesson(s) coming up:\n"
    + '{% for l in week.lessons %}\n- {{ l.start|datetime("short") }} {{ l.title }}'
    "{% if l.online %} (online){% elif l.location %}, {{ l.location }}{% endif %}{% endfor %}"
    "\n\nSee the schedule: {{ week.link }}" + SIGN,
)
DEFAULTS[("message_digest", "email")] = (
    "You have {{ digest.count }} unread message(s)",
    "Hello {{ recipient.first_name }},\n\nYou have {{ digest.count }} unread message(s):\n"
    "{% for m in digest.messages %}\n- {{ m.title }}{% if m.body %}: {{ m.body }}{% endif %}"
    "{% endfor %}" + SIGN,
)


# --- preferences ----------------------------------------------------------------------------------


def _clock(value: Any, fallback: str) -> time:
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return time.fromisoformat(fallback)


def default_time(kind: str) -> time:
    if kind == Kind.TUTOR_AGENDA:
        return _clock(get_setting("comms.digest_agenda_time"), "07:00")
    if kind == Kind.WEEKLY_SCHEDULE:
        return _clock(get_setting("comms.digest_weekly_time"), "18:00")
    return _clock(get_setting("comms.digest_messages_time"), "17:00")


def default_weekday() -> int:
    return int(get_setting("comms.digest_weekly_day"))


def person_for(user: Any) -> tuple[str, str]:
    """Tutor profile, else a family contact login, else the user (staff)."""
    from tutortrack.people.models import Contact

    from .services import person_for as tutor_or_user

    kind, ref = tutor_or_user(user)
    if kind == "tutor":
        return kind, ref
    contact = Contact.objects.filter(user=user, archived_at__isnull=True).only("pk").first()
    return ("contact", str(contact.pk)) if contact is not None else ("user", str(user.pk))


@dataclass(frozen=True)
class Choice:
    kind: str
    label: str
    enabled: bool
    org_enabled: bool
    send_time: time
    weekday: int | None
    customised: bool


def _choice(kind: str, row: DigestPreference | None) -> Choice:
    from .services import effective

    return Choice(
        kind=kind,
        label=str(Kind(kind).label),
        enabled=row.enabled if row is not None else True,
        org_enabled=effective(TYPE_FOR[Kind(kind)]).enabled,
        send_time=(row.send_time if row is not None and row.send_time else default_time(kind)),
        weekday=(
            (row.weekday if row is not None and row.weekday is not None else default_weekday())
            if kind == Kind.WEEKLY_SCHEDULE
            else None
        ),
        customised=row is not None,
    )


def my_digests(user: Any) -> list[Choice]:
    person_type, person_id = person_for(user)
    rows = {
        r.kind: r
        for r in DigestPreference.objects.filter(person_type=person_type, person_id=person_id)
    }
    return [_choice(kind, rows.get(kind)) for kind in KINDS_FOR[person_type]]


@transaction.atomic
def set_my_digests(user: Any, choices: list[dict[str, Any]]) -> list[Choice]:
    person_type, person_id = person_for(user)
    allowed = set(KINDS_FOR[person_type])
    for choice in choices:
        kind = choice["kind"]
        if kind not in allowed:
            message = _("That digest isn't available to you.")
            raise BusinessRuleViolation(message, extra={"errors": {"kind": [message]}})
        weekday = choice.get("weekday")
        if weekday is not None and not 0 <= int(weekday) <= 6:
            message = _("Choose a day of the week.")
            raise BusinessRuleViolation(message, extra={"errors": {"weekday": [message]}})
        DigestPreference.objects.update_or_create(
            person_type=person_type,
            person_id=person_id,
            kind=kind,
            defaults={
                "enabled": bool(choice.get("enabled", True)),
                "send_time": choice.get("send_time"),
                "weekday": weekday if kind == Kind.WEEKLY_SCHEDULE else None,
            },
        )
    return my_digests(user)


# --- sending --------------------------------------------------------------------------------------


def _zone(name: str | None, fallback: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or fallback)
    except (ValueError, KeyError):
        return ZoneInfo(fallback)


def due(moment: datetime, tz: ZoneInfo, choice: Choice) -> date | None:
    """The person's local date if ``moment`` is within an hour after their send time
    (and, weekly, on their day); else None."""
    if not choice.enabled:
        return None
    local = moment.astimezone(tz)
    at = datetime.combine(local.date(), choice.send_time, tzinfo=tz)
    if not at <= local < at + WINDOW:
        return None
    if choice.weekday is not None and local.weekday() != choice.weekday:
        return None
    return local.date()


def _prefs(person_type: str) -> dict[str, dict[str, DigestPreference]]:
    out: dict[str, dict[str, DigestPreference]] = {}
    for row in DigestPreference.objects.filter(person_type=person_type):
        out.setdefault(row.person_id, {})[row.kind] = row
    return out


def _day_bounds(day: date, tz: ZoneInfo, days: int = 1) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=days)


def send_agendas(moment: datetime, org_tz: str) -> int:
    from tutortrack.people.models import TutorProfile
    from tutortrack.scheduling.models import Lesson

    from .services import notify

    sent = 0
    prefs = _prefs("tutor")
    tutors = TutorProfile.objects.filter(
        membership__status="active", status__in=["active", "restricted"]
    ).select_related("membership__user")
    for tutor in tutors:
        choice = _choice(Kind.TUTOR_AGENDA, prefs.get(str(tutor.pk), {}).get(Kind.TUTOR_AGENDA))
        tz = _zone(getattr(tutor.membership.user, "timezone", None), org_tz)
        day = due(moment, tz, choice)
        if day is None:
            continue
        start, end = _day_bounds(day, tz)
        lessons = list(
            Lesson.objects.filter(tutors__tutor=tutor, start__gte=start, start__lt=end)
            .exclude(status=Lesson.Status.CANCELLED)
            .select_related("location")
            .prefetch_related("attendees__student")
            .order_by("start")
        )
        if lessons:
            sent += len(
                notify("tutor_daily_agenda", (tutor, day, lessons), key=f"{tutor.pk}:{day}")
            )
    return sent


def send_weekly_schedules(moment: datetime, org_tz: str) -> int:
    from tutortrack.people.models import Contact
    from tutortrack.scheduling.models import Lesson

    from .services import notify

    sent = 0
    prefs = _prefs("contact")
    contacts = (
        Contact.objects.filter(
            archived_at__isnull=True, receives_reminders=True, client__status="active"
        )
        .exclude(email="")
        .select_related("client", "user")
    )
    for contact in contacts:
        row = prefs.get(str(contact.pk), {}).get(Kind.WEEKLY_SCHEDULE)
        choice = _choice(Kind.WEEKLY_SCHEDULE, row)
        tz = _zone(getattr(contact.user, "timezone", None) if contact.user_id else None, org_tz)
        day = due(moment, tz, choice)
        if day is None:
            continue
        start, end = _day_bounds(day + timedelta(days=1), tz, days=7)
        lessons = list(
            Lesson.objects.filter(
                attendees__client_id=contact.client_id,
                status=Lesson.Status.PLANNED,
                start__gte=start,
                start__lt=end,
            )
            .distinct()
            .select_related("location")
            .prefetch_related("attendees__student")
            .order_by("start")
        )
        if lessons:
            payload = (contact, day + timedelta(days=1), lessons)
            sent += len(notify("client_weekly_schedule", payload, key=f"{contact.pk}:{day}"))
    return sent


def send_message_digests(moment: datetime, org_tz: str) -> int:
    from tutortrack.identity.models import User

    from .models import InAppNotification
    from .services import notify, person_for

    sent = 0
    since = moment - timedelta(hours=24)
    unread = (
        InAppNotification.objects.filter(
            type_key__in=MESSAGE_TYPES, read_at__isnull=True, created_at__gte=since
        )
        .order_by("created_at")
        .values_list("user_id", flat=True)
    )
    user_ids = sorted({str(u) for u in unread})
    prefs = {"tutor": _prefs("tutor"), "user": _prefs("user")}
    for user in User.objects.filter(pk__in=user_ids, is_active=True):
        person_type, person_id = person_for(user)
        row = prefs.get(person_type, {}).get(person_id, {}).get(Kind.MESSAGE_DIGEST)
        choice = _choice(Kind.MESSAGE_DIGEST, row)
        day = due(moment, _zone(user.timezone, org_tz), choice)
        if day is None:
            continue
        rows = list(
            InAppNotification.objects.filter(
                user=user, type_key__in=MESSAGE_TYPES, read_at__isnull=True, created_at__gte=since
            ).order_by("created_at")[:20]
        )
        if rows:
            recipient = user_recipient(user)
            sent += len(notify("message_digest", (recipient, rows), key=f"{user.pk}:{day}"))
    return sent


def run(moment: datetime) -> dict[str, int]:
    """Send every digest that is due at ``moment`` (the beat task, every 15 minutes)."""
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    from .services import effective

    org_tz = str(Organisation.objects.get(pk=require_organisation_id()).timezone or "UTC")
    out = {"tutor_agenda": 0, "weekly_schedule": 0, "message_digest": 0}
    if effective("tutor_daily_agenda").enabled:
        out["tutor_agenda"] = send_agendas(moment, org_tz)
    if effective("client_weekly_schedule").enabled:
        out["weekly_schedule"] = send_weekly_schedules(moment, org_tz)
    if effective("message_digest").enabled:
        out["message_digest"] = send_message_digests(moment, org_tz)
    return out
