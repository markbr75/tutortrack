"""People reads (E05)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import (
    Count,
    DecimalField,
    F,
    Func,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Cast, Coalesce

from tutortrack.core.time import now

from .models import Client, Contact, Student, TutorProfile


class DigitsOnly(Func):
    """SQL: the value with every non-digit removed."""

    function = "regexp_replace"
    template = "%(function)s(%(expressions)s, '\\D', '', 'g')"


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone)[-9:]  # compare the national significant part


def possible_duplicates(
    *,
    email: str = "",
    phone: str = "",
    first_name: str = "",
    last_name: str = "",
    date_of_birth: str = "",
) -> list[dict[str, Any]]:
    """Records that look like the person being created (FR-05-13)."""
    found: list[dict[str, Any]] = []
    email = email.strip().lower()
    digits = _digits(phone) if phone else ""
    if email:
        for c in Contact.objects.filter(email=email, archived_at__isnull=True)[:10]:
            found.append(
                {
                    "type": "contact",
                    "id": c.pk,
                    "name": c.full_name,
                    "client_id": c.client_id,
                    "reason": "email",
                }
            )
        for t in TutorProfile.objects.filter(email=email)[:5]:
            found.append(
                {
                    "type": "tutor",
                    "id": t.pk,
                    "name": t.full_name,
                    "client_id": None,
                    "reason": "email",
                }
            )
    if len(digits) >= 7:
        contacts = Contact.objects.annotate(
            phone_digits=DigitsOnly(F("phone")), mobile_digits=DigitsOnly(F("mobile"))
        ).filter(Q(phone_digits__endswith=digits) | Q(mobile_digits__endswith=digits))
        for c in contacts[:10]:
            found.append(
                {"type": "contact", "id": c.pk, "name": c.full_name, "client_id": c.client_id,
                 "reason": "phone"}
            )  # fmt: skip
    if first_name and last_name:
        students = Student.objects.filter(
            first_name__iexact=first_name.strip(), last_name__iexact=last_name.strip()
        )
        if date_of_birth:
            students = students.filter(date_of_birth=date_of_birth)
        for s in students[:10]:
            found.append(
                {
                    "type": "student",
                    "id": s.pk,
                    "name": s.full_name,
                    "client_id": s.client_id,
                    "reason": "name and date of birth" if date_of_birth else "name",
                }
            )
    unique: dict[tuple[str, Any], dict[str, Any]] = {}
    for row in found:
        unique.setdefault((row["type"], row["id"]), row)
    return list(unique.values())


def timeline_scope(target_type: str, target_id: str) -> dict[str, list[str]]:
    """Which clients, students and tutors a record's activity timeline covers (FR-05-10):
    a contact's timeline shows its family's lessons, invoices and payments."""
    from django.core.exceptions import ValidationError

    out: dict[str, list[str]] = {"client": [], "student": [], "tutor": []}
    try:
        if target_type == "people.client":
            out["client"] = [str(target_id)]
        elif target_type == "people.contact":
            clients = Contact.objects.filter(pk=target_id).values_list("client_id", flat=True)
            out["client"] = [str(c) for c in clients]
        elif target_type == "people.student":
            out["student"] = [str(target_id)]
        elif target_type == "people.tutor":
            out["tutor"] = [str(target_id)]
    except (ValidationError, ValueError):
        pass
    return out


MERGE_ENTITIES = {
    "clients": "people.client",
    "contacts": "people.contact",
    "students": "people.student",
}


def _person(kind: str, record: Any) -> dict[str, Any]:
    detail = ""
    if kind == "contact":
        detail = str(record.client)
    elif kind == "student":
        detail = " · ".join(p for p in (record.year_group, str(record.client)) if p)
    return {
        "id": str(record.pk),
        "name": str(record),
        "detail": detail,
        "client_id": str(record.client_id) if kind != "client" else str(record.pk),
        "created_at": record.created_at,
    }


def duplicate_pairs(user: Any, kind: str, limit: int = 100) -> list[dict[str, Any]]:
    """Records that look like the same person or family (FR-05-13), for the duplicates
    list: contacts with the same email or phone, students with the same name (and date of
    birth when both have one), and families sharing a contact email or phone, or a name.
    The older record of a pair is suggested as the one to keep (``a``)."""
    from collections import defaultdict

    from django.db.models.functions import Lower, Right

    from tutortrack.core.permissions import has_perm, scope_queryset

    if kind not in {"client", "contact", "student"} or not has_perm(user, f"people.{kind}.view"):
        return []
    groups: list[tuple[str, list[Any]]] = []
    live = {"archived_at__isnull": True, "merged_into__isnull": True}
    contacts = scope_queryset(
        user, Contact.objects.filter(**live).select_related("client"), "people.contact.view"
    )
    if kind in {"contact", "client"}:
        by: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for c in contacts.exclude(email="").annotate(key=Lower("email")):
            by[("email", c.key)].append(c)
        phones = contacts.annotate(digits=Right(DigitsOnly(F("phone")), 9)).filter(
            digits__regex=r"^\d{7,}$"
        )
        for c in phones:
            by[("phone", c.digits)].append(c)
        for (reason, _key), rows in by.items():
            if kind == "contact":
                groups.append((reason, rows))
            else:
                clients = {c.client_id: c.client for c in rows if c.client.archived_at is None}
                groups.append((reason, list(clients.values())))
    if kind == "client":
        names: dict[str, list[Any]] = defaultdict(list)
        for client in scope_queryset(user, Client.objects.filter(**live), "people.client.view"):
            names[client.display_name.strip().lower()].append(client)
        groups += [("name", rows) for rows in names.values()]
        visible = set(
            scope_queryset(user, Client.objects.all(), "people.client.view").values_list(
                "pk", flat=True
            )
        )
        groups = [(r, [c for c in rows if c.pk in visible]) for r, rows in groups]
    if kind == "student":
        by_name: dict[tuple[str, str], list[Any]] = defaultdict(list)
        students = scope_queryset(
            user, Student.objects.filter(**live).select_related("client"), "people.student.view"
        )
        for s in students.annotate(f=Lower("first_name"), last=Lower("last_name")):
            by_name[(s.f.strip(), s.last.strip())].append(s)
        for rows in by_name.values():
            groups.append(("name", rows))
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for reason, rows in groups:
        rows = sorted({r.pk: r for r in rows}.values(), key=lambda r: (r.created_at, str(r.pk)))
        for i, a in enumerate(rows):
            for b in rows[i + 1 :]:
                why = reason
                if kind == "student" and a.date_of_birth and b.date_of_birth:
                    if a.date_of_birth != b.date_of_birth:
                        continue
                    why = "name and date of birth"
                key = (str(a.pk), str(b.pk))
                if key not in pairs:
                    pairs[key] = {
                        "type": kind,
                        "a": _person(kind, a),
                        "b": _person(kind, b),
                        "reason": why,
                    }
    out = sorted(pairs.values(), key=lambda p: p["b"]["created_at"], reverse=True)
    return out[:limit]


def merge_preview(user: Any, subject_type: str, source_id: Any, target_id: Any) -> dict[str, Any]:
    """What merging ``source`` into ``target`` would do (FR-05-13)."""
    from . import merging

    source = merging.load(subject_type, source_id)
    target = merging.load(subject_type, target_id)
    return merging.preview(user, subject_type, source, target)


# --- computed list fields (FR-05-1/4/11) --------------------------------------------------------


class EpochSeconds(Func):
    """SQL: the number of seconds in an interval."""

    template = "EXTRACT(EPOCH FROM %(expressions)s)"
    output_field = DecimalField(max_digits=20, decimal_places=6)


FAR_FUTURE = datetime(9999, 12, 31, tzinfo=UTC)
FAR_PAST = datetime(1970, 1, 1, tzinfo=UTC)
BOOKED = ("planned", "completed")
SLA_DAYS = 90


def current_term() -> tuple[datetime, datetime] | None:
    """The organisation's term running today (E20), as a UTC range; ``None`` without one."""
    from zoneinfo import ZoneInfo

    from tutortrack.core.context import require_organisation_id
    from tutortrack.courses.models import Term
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    tz = ZoneInfo(org.timezone)
    today = now().astimezone(tz).date()
    term = (
        Term.objects.filter(start_date__lte=today, end_date__gte=today)
        .order_by("start_date")
        .first()
    )
    if term is None:
        return None
    start = datetime.combine(term.start_date, time.min, tzinfo=tz)
    end = datetime.combine(term.end_date + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def current_month() -> tuple[datetime, datetime]:
    """This calendar month in the organisation's timezone, as a UTC range."""
    from zoneinfo import ZoneInfo

    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    tz = ZoneInfo(Organisation.objects.get(pk=require_organisation_id()).timezone)
    local = now().astimezone(tz)
    start = datetime(local.year, local.month, 1, tzinfo=tz)
    end = datetime(local.year + local.month // 12, local.month % 12 + 1, 1, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def _hours(qs: QuerySet[Any], group: str, lesson: str = "lesson__") -> Any:
    seconds = qs.values(group).annotate(
        s=Sum(EpochSeconds(F(f"{lesson}end") - F(f"{lesson}start")))
    )
    return Coalesce(
        Subquery(seconds.values("s")[:1]) / Value(Decimal(3600)),
        Value(Decimal(0)),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )


def _lesson_dates(path: str) -> dict[str, Any]:
    """``next_lesson_at``/``last_lesson_at`` plus never-null sort keys (cursor pagination
    can't page over nulls)."""
    from tutortrack.scheduling.models import Lesson

    moment = now()
    upcoming = Lesson.objects.filter(
        **{path: OuterRef("pk")}, status="planned", start__gte=moment
    ).order_by("start")
    past = Lesson.objects.filter(**{path: OuterRef("pk")}, status="completed").order_by("-start")
    return {
        "next_lesson_at": Subquery(upcoming.values("start")[:1]),
        "last_lesson_at": Subquery(past.values("start")[:1]),
    }


def _sort_keys(qs: QuerySet[Any]) -> QuerySet[Any]:
    return qs.annotate(
        next_lesson_sort=Coalesce(F("next_lesson_at"), Value(FAR_FUTURE)),
        last_lesson_sort=Coalesce(F("last_lesson_at"), Value(FAR_PAST)),
    )


def with_client_figures(user: Any, qs: QuerySet[Client]) -> QuerySet[Client]:
    """Balance (ledger, in the client's currency), next and last lesson and hours this term,
    each only when the user may see that area (billing, lessons)."""
    from tutortrack.core.permissions import has_perm

    if has_perm(user, "billing.invoice.view"):
        from tutortrack.billing.models import ClientLedgerEntry

        total = (
            ClientLedgerEntry.objects.filter(client=OuterRef("pk"), currency=OuterRef("currency"))
            .values("client")
            .annotate(t=Sum("amount_amount"))
            .values("t")[:1]
        )
        qs = qs.annotate(
            balance=Coalesce(
                Subquery(total),
                Value(Decimal(0)),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
    if has_perm(user, "scheduling.lesson.view"):
        from tutortrack.scheduling.models import LessonAttendee

        qs = _sort_keys(qs.annotate(**_lesson_dates("attendees__client")))
        term = current_term()
        if term is not None:
            attended = LessonAttendee.objects.filter(
                client=OuterRef("pk"),
                lesson__status__in=BOOKED,
                lesson__start__gte=term[0],
                lesson__start__lt=term[1],
            )
            qs = qs.annotate(hours_this_term=_hours(attended, "client"))
    return qs


def with_student_figures(user: Any, qs: QuerySet[Student]) -> QuerySet[Student]:
    from tutortrack.core.permissions import has_perm

    if not has_perm(user, "scheduling.lesson.view"):
        return qs
    from tutortrack.scheduling.models import LessonAttendee

    qs = _sort_keys(qs.annotate(**_lesson_dates("attendees__student")))
    term = current_term()
    if term is not None:
        attended = LessonAttendee.objects.filter(
            student=OuterRef("pk"),
            lesson__status__in=BOOKED,
            lesson__start__gte=term[0],
            lesson__start__lt=term[1],
        )
        qs = qs.annotate(hours_this_term=_hours(attended, "student"))
    return qs


def with_tutor_figures(user: Any, qs: QuerySet[TutorProfile]) -> QuerySet[TutorProfile]:
    """Hours booked this month and report SLA compliance (share of the reports due in the
    last 90 days that were submitted on time; ``None`` when none were due)."""
    from tutortrack.core.permissions import has_perm

    if has_perm(user, "scheduling.lesson.view"):
        from tutortrack.scheduling.models import LessonTutor

        start, end = current_month()
        taught = LessonTutor.objects.filter(
            tutor=OuterRef("pk"),
            lesson__status__in=BOOKED,
            lesson__start__gte=start,
            lesson__start__lt=end,
        )
        qs = qs.annotate(hours_this_month=_hours(taught, "tutor"))
    if has_perm(user, "delivery.report.view"):
        from tutortrack.delivery.models import LessonReport

        moment = now()
        due = LessonReport.objects.filter(
            tutor=OuterRef("pk"), due_at__lte=moment, due_at__gte=moment - timedelta(days=SLA_DAYS)
        )
        rate = due.values("tutor").annotate(
            r=Cast(
                Count("pk", filter=Q(submitted_at__isnull=False, submitted_at__lte=F("due_at")))
                * Value(100.0)
                / Count("pk"),
                DecimalField(max_digits=5, decimal_places=1),
            )
        )
        qs = qs.annotate(
            report_sla=Subquery(rate.values("r")[:1]),
            report_sla_sort=Coalesce(
                Subquery(rate.values("r")[:1]),
                Value(Decimal(-1)),
                output_field=DecimalField(max_digits=5, decimal_places=1),
            ),
        )
    return qs


def tutor_utilisation(tutors: list[TutorProfile]) -> dict[str, Decimal | None]:
    """Booked minutes this month as a share of the tutor's weekly availability this month
    (FR-05-4), per tutor id. ``None`` when the tutor has no availability set."""
    from tutortrack.reporting.reports.operations import available_minutes
    from tutortrack.scheduling.selectors import scheduled_minutes

    if not tutors:
        return {}
    start, end = current_month()
    ids = [str(t.pk) for t in tutors]
    booked = scheduled_minutes(ids, start, end)
    available = available_minutes(ids, start.date(), (end - timedelta(days=1)).date())
    out: dict[str, Decimal | None] = {}
    for tutor_id in ids:
        minutes = available.get(tutor_id, 0)
        out[tutor_id] = (
            (Decimal(booked.get(tutor_id, 0)) * 100 / minutes).quantize(Decimal("0.1"))
            if minutes
            else None
        )
    return out


def client_summary(client: Client) -> dict[str, Any]:
    """Computed figures for a client page (FR-05-1)."""
    from tutortrack.billing import ledger
    from tutortrack.scheduling.models import Lesson

    balances = ledger.balances(client)
    moment = now()
    lessons = Lesson.objects.filter(attendees__client=client)
    upcoming = lessons.filter(status="planned", start__gte=moment).order_by("start").first()
    last = lessons.filter(status="completed").order_by("-start").first()
    return {
        "active_students": client.students.filter(
            archived_at__isnull=True, status__in=["active", "trial"]
        ).count(),
        "balance": balances.ledger,
        "available_credit": balances.available_credit,
        "overdue": balances.overdue,
        "next_lesson_at": upcoming.start if upcoming else None,
        "last_lesson_at": last.start if last else None,
    }


# --- map view (E05-T12) -------------------------------------------------------------------------

MAP_KINDS = ("student", "tutor")
MAP_LIMIT = 2000


def student_place(student: Student) -> Any:
    """Where a student has in-person lessons: their lesson address, else the family's."""
    for address in (student.lesson_address, student.client.billing_address):
        if address is not None and (address.lat is not None or address.one_line()):
            return address
    return None


def _point(kind: str, record: Any, place: Any, subjects: list[str], radius: Any) -> dict[str, Any]:
    from tutortrack.core.geo import area_of, rounded

    lat, lng = rounded(place.lat, place.lng)
    return {
        "kind": kind,
        "id": str(record.pk),
        "name": record.full_name,
        "status": record.status,
        "area": area_of(place),
        "lat": lat,
        "lng": lng,
        "subjects": subjects,
        "travel_radius_km": radius,
    }


def map_points(
    user: Any,
    *,
    kinds: Any = MAP_KINDS,
    status: str = "",
    branch: str = "",
    subject: str = "",
) -> dict[str, Any]:
    """Geocoded students and tutors the user may see (FR-05-11 map view).

    Points are rounded to about 100 m and carry an area (postcode district), never the
    street address. People without coordinates are counted so staff can geocode them."""
    from tutortrack.core.permissions import has_perm, scope_queryset

    points: list[dict[str, Any]] = []
    missing = {"student": 0, "tutor": 0}
    wanted = subject.strip().lower()
    if "student" in kinds and has_perm(user, "people.student.view"):
        students = scope_queryset(
            user,
            Student.objects.filter(archived_at__isnull=True).select_related(
                "lesson_address", "client__billing_address"
            ),
            "people.student.view",
        )
        if status:
            students = students.filter(status=status)
        if branch:
            students = students.filter(branch_id=branch)
        for student in students[:MAP_LIMIT]:
            subjects = [str(s.get("subject", "")) for s in student.subjects or [] if s]
            if wanted and wanted not in {s.lower() for s in subjects}:
                continue
            place = student_place(student)
            if place is None or place.lat is None or place.lng is None:
                missing["student"] += 1
                continue
            points.append(_point("student", student, place, subjects, None))
    if "tutor" in kinds and has_perm(user, "people.tutor.view"):
        tutors = scope_queryset(
            user,
            TutorProfile.objects.filter(archived_at__isnull=True)
            .select_related("address")
            .prefetch_related("subjects"),
            "people.tutor.view",
        )
        if status:
            tutors = tutors.filter(status=status)
        if branch:
            tutors = tutors.filter(branches__id=branch)
        for tutor in tutors.distinct()[:MAP_LIMIT]:
            subjects = sorted({s.subject for s in tutor.subjects.all() if s.subject})
            if wanted and wanted not in {s.lower() for s in subjects}:
                continue
            place = tutor.address
            if place is None or place.lat is None or place.lng is None:
                missing["tutor"] += 1
                continue
            radius = tutor.travel_radius_km if tutor.delivers_in_person else None
            points.append(_point("tutor", tutor, place, subjects, radius))
    return {"points": points, "missing": missing}


def teaches(membership: Any) -> bool:
    """Whether this login has its own tutor record (it can use the tutor app)."""
    return membership is not None and TutorProfile.objects.filter(membership=membership).exists()
