"""Course reads (E20): scoped querysets, places, rosters and the public catalogue."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import Count, Q, QuerySet

from tutortrack.core.permissions import permission_scope, scope_queryset

from .models import (
    ClassSession,
    Course,
    Enrolment,
    GroupClass,
    MakeupBooking,
    Term,
    TermBreak,
)

VIEW = "courses.view"


def courses(user: Any) -> QuerySet[Course]:
    """Courses are organisation-wide products; tutors (own scope) see the ones they teach."""
    scope = permission_scope(user, VIEW)
    qs = Course.objects.all()
    if scope is None:
        return qs.none()
    if scope == "own":
        mine = GroupClass.objects.filter(GroupClass.own_scope_q(user)).values("course_id")
        return qs.filter(pk__in=mine)
    return qs


def terms(user: Any) -> QuerySet[Term]:
    return scope_queryset(user, Term.objects.select_related("academic_year"), VIEW)


def classes(user: Any) -> QuerySet[GroupClass]:
    return scope_queryset(
        user,
        GroupClass.objects.select_related("course", "term", "location", "room"),
        VIEW,
    )


def enrolments(user: Any, codename: str = VIEW) -> QuerySet[Enrolment]:
    return scope_queryset(
        user,
        Enrolment.objects.select_related("group_class__course", "student", "client"),
        codename,
    )


def sessions(user: Any, codename: str = VIEW) -> QuerySet[ClassSession]:
    visible = (
        classes(user)
        if codename == VIEW
        else scope_queryset(user, GroupClass.objects.all(), codename)
    )
    return ClassSession.objects.filter(group_class__in=visible.values("pk")).select_related(
        "lesson", "group_class__course"
    )


# --- places -------------------------------------------------------------------------------------


def _waitlist_holds(group_class: GroupClass, exclude_entry: Any = None) -> int:
    """Places promised to the waitlist: offers out, and accepted offers not enrolled yet."""
    from tutortrack.leads.models import WaitlistEntry

    used = Enrolment.objects.filter(
        group_class=group_class, waitlist_entry_id__isnull=False
    ).values_list("waitlist_entry_id", flat=True)
    holds = WaitlistEntry.objects.filter(
        group_class_id=group_class.pk,
        status__in=[WaitlistEntry.Status.OFFERED, WaitlistEntry.Status.ACCEPTED],
    ).exclude(pk__in=list(used))
    if exclude_entry is not None:
        holds = holds.exclude(pk=exclude_entry)
    return holds.count()


def active_count(group_class: GroupClass) -> int:
    return Enrolment.objects.filter(group_class=group_class, status__in=Enrolment.ACTIVE).count()


def taken_places(group_class: GroupClass, *, exclude_entry: Any = None) -> int:
    return active_count(group_class) + _waitlist_holds(group_class, exclude_entry)


def places_left(group_class: GroupClass) -> int:
    return max(group_class.capacity - taken_places(group_class), 0)


def waiting(group_class: GroupClass) -> QuerySet[Any]:
    from tutortrack.leads.models import WaitlistEntry

    return (
        WaitlistEntry.objects.filter(group_class_id=group_class.pk)
        .exclude(status=WaitlistEntry.Status.REMOVED)
        .select_related("student")
        .order_by("created_at")
    )


# --- rosters ------------------------------------------------------------------------------------


def attending_on(group_class: GroupClass, day: date) -> QuerySet[Enrolment]:
    """Enrolments whose students are in the class on ``day``: current ones from their
    start date, and those who left (withdrawn, transferred) up to their last day."""
    left = ("withdrawn", "transferred", "completed")
    return Enrolment.objects.filter(
        Q(status__in=Enrolment.ATTENDING) | Q(status__in=left, end_date__isnull=False),
        group_class=group_class,
        start_date__lte=day,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=day))


def makeups_for(session: ClassSession) -> QuerySet[MakeupBooking]:
    return MakeupBooking.objects.filter(
        session=session, status=MakeupBooking.Status.BOOKED
    ).select_related("student")


def session_dates(group_class: GroupClass) -> list[date]:
    return list(
        ClassSession.objects.filter(group_class=group_class)
        .exclude(lesson__status="cancelled")
        .order_by("date")
        .values_list("date", flat=True)
    )


def breaks_of(term: Term) -> list[tuple[date, date]]:
    return list(TermBreak.objects.filter(term=term).values_list("start_date", "end_date"))


def term_dates(branch_id: Any) -> list[tuple[date, date]]:
    return list(Term.objects.filter(branch_id=branch_id).values_list("start_date", "end_date"))


def break_dates(branch_id: Any, start: date, end: date) -> set[date]:
    from datetime import timedelta

    days: set[date] = set()
    for b_start, b_end in TermBreak.objects.filter(
        term__branch_id=branch_id, start_date__lte=end, end_date__gte=start
    ).values_list("start_date", "end_date"):
        day = max(b_start, start)
        while day <= min(b_end, end):
            days.add(day)
            day += timedelta(days=1)
    return days


def enrolled_counts(class_ids: list[Any]) -> dict[str, int]:
    rows = (
        Enrolment.objects.filter(group_class_id__in=class_ids, status__in=Enrolment.ACTIVE)
        .values("group_class_id")
        .annotate(n=Count("id"))
    )
    return {str(r["group_class_id"]): r["n"] for r in rows}


# --- public catalogue (T09) ---------------------------------------------------------------------


def public_classes(
    *,
    subject: str = "",
    age: int | None = None,
    weekday: int | None = None,
    location: str = "",
    course: str = "",
) -> list[GroupClass]:
    """Open public classes of public courses whose enrolment window is open (FR-20-8)."""
    from tutortrack.core.time import now

    today = now().date()
    qs = (
        GroupClass.objects.filter(
            is_public=True,
            course__is_public=True,
            course__archived_at__isnull=True,
            status__in=GroupClass.ENROLLABLE,
            end_date__gte=today,
        )
        .filter(Q(term__enrolment_opens__isnull=True) | Q(term__enrolment_opens__lte=today))
        .filter(Q(term__enrolment_closes__isnull=True) | Q(term__enrolment_closes__gte=today))
        .select_related("course__subject", "course__level", "term", "location", "room")
        .order_by("start_date", "start_time")
    )
    if subject:
        qs = (
            qs.filter(course__subject_id=subject)
            if _is_uuid(subject)
            else qs.filter(course__subject__name__iexact=subject)
        )
    if course:
        qs = qs.filter(course_id=course) if _is_uuid(course) else qs.none()
    if location:
        qs = qs.filter(location_id=location) if _is_uuid(location) else qs.none()
    out = []
    for c in qs:
        if weekday is not None and not _meets_on(c, weekday):
            continue
        if age is not None and not _age_fits(c, age):
            continue
        out.append(c)
    return out


def _is_uuid(value: str) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


WEEKDAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def meeting_days(group_class: GroupClass) -> list[int]:
    """Weekdays the class meets (from BYDAY, else the start date's weekday)."""
    rule = group_class.rrule.upper()
    for part in rule.split(";"):
        if part.startswith("BYDAY="):
            codes = [c.strip()[-2:] for c in part[6:].split(",")]
            return sorted({WEEKDAY_CODES.index(c) for c in codes if c in WEEKDAY_CODES})
    return [group_class.start_date.weekday()]


def _meets_on(group_class: GroupClass, weekday: int) -> bool:
    return weekday in meeting_days(group_class)


def age_range(group_class: GroupClass) -> tuple[int | None, int | None]:
    course = group_class.course
    return (
        group_class.min_age if group_class.min_age is not None else course.min_age,
        group_class.max_age if group_class.max_age is not None else course.max_age,
    )


def year_groups(group_class: GroupClass) -> list[str]:
    return list(group_class.year_groups or group_class.course.year_groups or [])


def _age_fits(group_class: GroupClass, age: int) -> bool:
    low, high = age_range(group_class)
    return (low is None or age >= low) and (high is None or age <= high)


def _locale() -> str:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.filter(pk=require_organisation_id()).first()
    return str(getattr(org, "locale", "") or "en-GB").replace("-", "_")


def public_card(group_class: GroupClass, *, locale: str | None = None) -> dict[str, Any]:
    """What the catalogue shows for a class (no prices of other people, no rosters)."""
    course = group_class.course
    left = places_left(group_class)
    price = course.price.round_to_minor()
    low, high = age_range(group_class)
    return {
        "id": str(group_class.pk),
        "name": group_class.name,
        "course": {
            "id": str(course.pk),
            "name": course.name,
            "description": course.public_description,
            "subject": course.subject.name if course.subject else "",
            "level": course.level.name if course.level else "",
            "image_url": f"/api/v1/public/assets/{course.image_id}" if course.image_id else "",
            "prerequisites": course.prerequisites,
            "delivery_mode": course.delivery_mode,
        },
        "term": group_class.term.name,
        "start_date": group_class.start_date.isoformat(),
        "end_date": group_class.end_date.isoformat(),
        "weekdays": meeting_days(group_class),
        "start_time": group_class.start_time.strftime("%H:%M"),
        "duration_minutes": group_class.duration_minutes,
        "location": group_class.location.name if group_class.location else "",
        "online": group_class.online,
        "min_age": low,
        "max_age": high,
        "year_groups": year_groups(group_class),
        "pricing_model": course.pricing_model,
        "pricing_label": str(course.get_pricing_model_display()),
        "price": price.format(locale or _locale()),
        "price_amount": str(price.amount),
        "currency": course.currency,
        "places_left": left,
        "capacity": group_class.capacity,
        "full": left <= 0,
        "waitlist": left <= 0 and group_class.waitlist_enabled,
    }


def public_course_images() -> list[str]:
    return [
        str(v)
        for v in Course.objects.filter(
            is_public=True, archived_at__isnull=True, image__isnull=False
        ).values_list("image_id", flat=True)
    ]
