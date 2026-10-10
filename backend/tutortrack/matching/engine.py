"""Tutor matching (E19 FR-19-1, T01/T02): hard filters, then a weighted score with a breakdown.

Hard filters: the tutor is active (not restricted, no lapsed blocking check), has the subject
approved at the level (any approved subject when none is asked for), delivers the mode,
works in the branch, isn't excluded by the student or already on the job, holds any required
checks and, in person, lives within their travel radius. ``include_restricted`` (permission
``matching.include_restricted``) relaxes the compliance and approval filters: the tutor then
only needs to have claimed the subject, and is flagged ``restricted`` with the reasons.

Each factor scores 0..1 and the weights (``matching.weights``) combine them into 0..100.
Unknown inputs (no availability set, no address, no ratings) score 0.5, so missing data
neither helps nor sinks a tutor; the breakdown says which were unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, Exists, OuterRef, Q
from django.utils.translation import gettext as _

from tutortrack.core.time import now
from tutortrack.people.models import TutorProfile, TutorSubject

WEEKS = 4
NEUTRAL = 0.5
FACTORS = (
    "availability", "distance", "rating", "experience", "workload", "history", "margin",
    "response", "fairness",
)  # fmt: skip
MODES = ("online", "in_person", "either")


@dataclass
class Criteria:
    subject_id: str | None = None
    subject_name: str = ""
    level_id: str | None = None
    mode: str = "either"
    lat: Decimal | None = None
    lng: Decimal | None = None
    area: str = ""
    slots: list[dict[str, Any]] = field(default_factory=list)
    intervals: list[tuple[datetime, datetime]] = field(default_factory=list)
    start_date: date | None = None
    duration_minutes: int = 60
    timezone: str = "UTC"
    branch_id: str | None = None
    languages: list[str] = field(default_factory=list)
    max_pay_rate: Decimal | None = None
    charge_rate: Decimal | None = None
    requirements: list[str] = field(default_factory=list)
    exclude: set[str] = field(default_factory=set)
    job_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "job": self.job_id,
            "subject": self.subject_id,
            "subject_name": self.subject_name,
            "level": self.level_id,
            "mode": self.mode,
            "lat": str(self.lat) if self.lat is not None else None,
            "lng": str(self.lng) if self.lng is not None else None,
            "area": self.area,
            "slots": self.slots,
            "lessons": [[s.isoformat(), e.isoformat()] for s, e in self.intervals],
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "duration_minutes": self.duration_minutes,
            "timezone": self.timezone,
            "branch": self.branch_id,
            "languages": self.languages,
            "max_pay_rate": str(self.max_pay_rate) if self.max_pay_rate is not None else None,
            "requirements": self.requirements,
        }


@dataclass
class Match:
    tutor: TutorProfile
    score: Decimal
    breakdown: dict[str, dict[str, Any]]
    distance_km: Decimal | None = None
    slot_fit: list[float] = field(default_factory=list)
    restricted: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def point(self) -> tuple[float, float] | None:
        """The tutor's home, rounded to about a kilometre (for the map, not directions)."""
        address = self.tutor.address
        if address is None or address.lat is None or address.lng is None:
            return None
        return round(float(address.lat), 2), round(float(address.lng), 2)


# --- criteria -----------------------------------------------------------------------------------


def area_of(address: Any) -> str:
    """A neighbourhood, not an address: the postcode's outward part, else the town."""
    if address is None:
        return ""
    postcode = (address.postcode or "").strip()
    if postcode:
        if " " in postcode:
            return postcode.split()[0].upper()
        return postcode[:-3].upper() if len(postcode) > 5 else postcode.upper()
    return address.city or ""


def job_place(job: Any) -> Any:
    """Where lessons happen: the job's location, else the student's lesson address or
    the family's address. ``None`` when nothing is known."""
    if job.location_id and job.location.address_id:
        return job.location.address
    links = job.students.filter(active_to__isnull=True).select_related(
        "student__lesson_address", "student__client__billing_address",
        "student__client__primary_contact__address",
    )  # fmt: skip
    fallback = None
    for link in links:
        student = link.student
        contact = student.client.primary_contact
        for address in (
            student.lesson_address,
            contact.address if contact is not None else None,
            student.client.billing_address,
        ):
            if address is None:
                continue
            if address.lat is not None:
                return address
            fallback = fallback or address
    return fallback


def criteria_for_job(job: Any) -> Criteria:
    from tutortrack.jobs.models import JobTutor

    place = job_place(job)
    exclude = {
        str(t)
        for link in job.students.filter(active_to__isnull=True).select_related("student")
        for t in link.student.excluded_tutors.values_list("pk", flat=True)
    }
    exclude |= {
        str(t)
        for t in job.tutors.filter(
            status__in=[JobTutor.Status.OFFERED, JobTutor.Status.ACTIVE]
        ).values_list("tutor_id", flat=True)
    }
    charge = job.charge_rate or job.service.charge_rate
    today = now().date()
    return Criteria(
        job_id=str(job.pk),
        subject_id=str(job.subject_id) if job.subject_id else None,
        subject_name=job.subject.name if job.subject_id else "",
        level_id=str(job.level_id) if job.level_id else None,
        mode="online" if job.online else "in_person",
        lat=place.lat if place is not None else None,
        lng=place.lng if place is not None else None,
        area=area_of(place),
        slots=list(job.default_schedule or []),
        start_date=max(job.start_date or today, today),
        duration_minutes=int(job.default_duration_minutes or 60),
        timezone=str(job.branch.timezone),
        branch_id=str(job.branch_id),
        charge_rate=charge.amount if charge is not None else None,
        exclude=exclude,
    )


def criteria_from_input(data: dict[str, Any], job: Any = None) -> Criteria:
    """Ad hoc criteria, or the job's with the given fields overriding it. A postcode
    without coordinates is geocoded (when a geocoder is configured)."""
    from tutortrack.catalogue.models import Subject
    from tutortrack.core.geo import geocoder
    from tutortrack.tenancy.models import Branch

    c = criteria_for_job(job) if job is not None else Criteria(start_date=now().date())
    if job is None:
        branch = (
            Branch.objects.filter(pk=data.get("branch")).first() if data.get("branch") else None
        )
        branch = branch or Branch.objects.order_by("created_at").first()
        if branch is not None:
            c.timezone = str(branch.timezone)
    for key, attr in (("subject", "subject_id"), ("level", "level_id"), ("branch", "branch_id")):
        if data.get(key):
            setattr(c, attr, str(data[key]))
    if data.get("subject"):
        subject = Subject.objects.filter(pk=data["subject"]).first()
        c.subject_name = subject.name if subject else ""
    if data.get("mode") in MODES:
        c.mode = data["mode"]
    for key in ("slots", "languages", "requirements"):
        if data.get(key) is not None:
            setattr(c, key, list(data[key]))
    for key in ("start_date", "duration_minutes", "max_pay_rate"):
        if data.get(key) is not None:
            setattr(c, key, data[key])
    if data.get("lat") is not None and data.get("lng") is not None:
        c.lat, c.lng = Decimal(str(data["lat"])), Decimal(str(data["lng"]))
    postcode = str(data.get("postcode") or "").strip()
    if postcode:
        c.area = postcode.split()[0].upper() if " " in postcode else postcode.upper()
        if data.get("lat") is None:
            point = geocoder().geocode(postcode)
            c.lat, c.lng = (point.lat, point.lng) if point else (None, None)
    return c


# --- search -------------------------------------------------------------------------------------


def _weights() -> dict[str, float]:
    from tutortrack.tenancy.settings_service import get_setting

    from .org_settings import DEFAULT_WEIGHTS

    configured = get_setting("matching.weights") or {}
    out = {}
    for key in FACTORS:
        try:
            out[key] = max(float(configured.get(key, DEFAULT_WEIGHTS[key])), 0.0)
        except (TypeError, ValueError):
            out[key] = float(DEFAULT_WEIGHTS[key])
    return out


def _candidates(c: Criteria, include_restricted: bool, only: list[str] | None) -> list[Any]:
    qs = TutorProfile.objects.filter(archived_at__isnull=True).select_related("address")
    if only is not None:
        qs = qs.filter(pk__in=only)
    statuses = [TutorProfile.Status.ACTIVE]
    if include_restricted:
        statuses += [TutorProfile.Status.RESTRICTED, TutorProfile.Status.ONBOARDING]
    qs = qs.filter(status__in=statuses)
    subjects = TutorSubject.objects.filter(tutor=OuterRef("pk"))
    if c.subject_id:
        subjects = subjects.filter(catalogue_subject_id=c.subject_id)
    if c.level_id:
        subjects = subjects.filter(
            Q(catalogue_level_id=c.level_id) | Q(catalogue_level__isnull=True)
        )
    qs = qs.annotate(subject_approved=Exists(subjects.filter(approved=True)))
    if include_restricted:
        qs = qs.filter(Exists(subjects.exclude(competency=TutorSubject.Competency.REJECTED)))
    else:
        qs = qs.filter(subject_approved=True)
    if c.mode == "online":
        qs = qs.filter(delivers_online=True)
    elif c.mode == "in_person":
        qs = qs.filter(delivers_in_person=True)
    if c.branch_id:
        qs = qs.filter(Q(branches__isnull=True) | Q(branches=c.branch_id))
    if c.exclude:
        qs = qs.exclude(pk__in=list(c.exclude))
    for language in c.languages:
        qs = qs.filter(languages__contains=[language])
    if c.max_pay_rate is not None:
        qs = qs.filter(Q(pay_rate_amount__isnull=True) | Q(pay_rate_amount__lte=c.max_pay_rate))
    return list(qs.distinct())


def _distance(c: Criteria, tutor: Any, default_radius: int) -> tuple[Decimal | None, bool]:
    """(km, within radius). Online-only searches, unknown places and tutors who can go
    online in an "either" search are never filtered out by distance."""
    from tutortrack.payroll.travel import Place, straight_line_km

    address = tutor.address
    if c.mode == "online" or c.lat is None or c.lng is None:
        return None, True
    if address is None or address.lat is None or address.lng is None:
        return None, True
    km = straight_line_km(Place("job", c.lat, c.lng), Place("tutor", address.lat, address.lng))
    radius = tutor.travel_radius_km or default_radius
    within = km <= radius or (c.mode == "either" and tutor.delivers_online)
    return km, within


def _offer_stats(ids: list[str]) -> dict[str, tuple[int, int]]:
    from .models import JobOffer

    S = JobOffer.Status
    rows = (
        JobOffer.objects.filter(tutor_id__in=ids)
        .values("tutor_id")
        .annotate(
            accepted=Count("id", filter=Q(status=S.ACCEPTED)),
            answered=Count("id", filter=Q(status__in=[S.ACCEPTED, S.DECLINED, S.EXPIRED])),
        )
    )
    return {str(r["tutor_id"]): (r["accepted"], r["answered"]) for r in rows}


def _factor(weight: float, score: float | None, value: Any) -> dict[str, Any]:
    return {
        "weight": weight,
        "score": round(score if score is not None else NEUTRAL, 3),
        "value": value,
        "known": score is not None,
    }


def search(
    c: Criteria,
    *,
    include_restricted: bool = False,
    limit: int = 50,
    only: list[str] | None = None,
) -> list[Match]:
    """Ranked tutors for the criteria. ``only`` limits the search to some tutors (to score
    a shortlisted tutor or an applicant)."""
    from tutortrack.jobs.selectors import last_assignment
    from tutortrack.recruitment.compliance import today as org_today
    from tutortrack.recruitment.selectors import (
        lapsed_tutor_ids,
        reference_ratings,
        tutors_with_valid,
    )
    from tutortrack.scheduling.availability import interval_fit, weekly_occurrences
    from tutortrack.scheduling.models import AvailabilityTemplate
    from tutortrack.scheduling.selectors import completed_in_subject, scheduled_minutes
    from tutortrack.tenancy.settings_service import get_setting

    tutors = _candidates(c, include_restricted, only)
    if not tutors:
        return []
    on = org_today()
    ids = [str(t.pk) for t in tutors]
    lapsed = lapsed_tutor_ids(ids, on)
    holders = tutors_with_valid(c.requirements, on)
    default_radius = int(get_setting("matching.default_radius_km"))

    kept: list[tuple[Any, Decimal | None, list[str]]] = []
    for tutor in tutors:
        reasons = []
        if tutor.status != TutorProfile.Status.ACTIVE:
            reasons.append(str(tutor.get_status_display()))
        if str(tutor.pk) in lapsed:
            reasons.append(_("A required check has lapsed"))
        if not tutor.subject_approved:
            reasons.append(_("Subject not approved"))
        if holders is not None and str(tutor.pk) not in holders:
            reasons.append(_("Missing a required check"))
        if reasons and not include_restricted:
            continue
        km, within = _distance(c, tutor, default_radius)
        if not within:
            continue
        kept.append((tutor, km, reasons))
    if not kept:
        return []
    ids = [str(t.pk) for t, _km, _r in kept]

    if c.intervals:
        groups = [list(c.intervals)]
    elif c.slots:
        groups = weekly_occurrences(
            c.slots, start=c.start_date or on, weeks=WEEKS, tz=c.timezone,
            default_minutes=c.duration_minutes,
        )  # fmt: skip
    else:
        groups = []
    buffer = int(get_setting("scheduling.travel_buffer_minutes"))
    fit = interval_fit(ids, groups, buffer_minutes=buffer) if groups else {}
    with_template = {
        str(t)
        for t in AvailabilityTemplate.objects.filter(tutor_id__in=ids).values_list(
            "tutor_id", flat=True
        )
    }
    horizon = now()
    booked = scheduled_minutes(ids, horizon, horizon + timedelta(weeks=WEEKS))
    history = completed_in_subject(ids, c.subject_id)
    ratings = reference_ratings(ids)
    offers = _offer_stats(ids)
    last = last_assignment(ids)
    target_margin = int(get_setting("matching.target_margin_percent")) / 100
    weights = _weights()
    total_weight = sum(weights.values()) or 1.0

    results = []
    for tutor, km, reasons in kept:
        key = str(tutor.pk)
        factors: dict[str, dict[str, Any]] = {}
        shares = fit.get(key, [])
        if groups and (key in with_template or c.intervals):
            mean = sum(shares) / len(shares) if shares else 0.0
            factors["availability"] = _factor(
                weights["availability"], mean, f"{round(mean * 100)}%"
            )
        else:
            factors["availability"] = _factor(weights["availability"], None, None)
        if c.mode == "online":
            factors["distance"] = _factor(weights["distance"], 1.0, "online")
        elif km is not None:
            radius = tutor.travel_radius_km or default_radius
            factors["distance"] = _factor(
                weights["distance"], max(0.0, 1 - float(km) / radius), float(km)
            )
        else:
            factors["distance"] = _factor(weights["distance"], None, None)
        rating = ratings.get(key)
        factors["rating"] = _factor(
            weights["rating"],
            (rating - 1) / 4 if rating is not None else None,
            round(rating, 1) if rating is not None else None,
        )
        years = tutor.years_experience
        factors["experience"] = _factor(
            weights["experience"], min(years, 10) / 10 if years is not None else None, years
        )
        if tutor.max_weekly_hours:
            per_week = booked.get(key, 0) / 60 / WEEKS
            spare = max(0.0, min(1.0, 1 - per_week / tutor.max_weekly_hours))
            factors["workload"] = _factor(
                weights["workload"], spare, f"{per_week:.1f}/{tutor.max_weekly_hours}"
            )
        else:
            factors["workload"] = _factor(weights["workload"], None, None)
        done = history.get(key, 0)
        factors["history"] = _factor(weights["history"], min(done, 20) / 20, done)
        pay = tutor.pay_rate_amount
        if c.charge_rate and pay is not None and c.charge_rate > 0:
            margin = float((c.charge_rate - pay) / c.charge_rate)
            score = max(0.0, min(1.0, margin / target_margin)) if target_margin else 1.0
            factors["margin"] = _factor(weights["margin"], score, f"{round(margin * 100)}%")
        else:
            factors["margin"] = _factor(weights["margin"], None, None)
        accepted, answered = offers.get(key, (0, 0))
        factors["response"] = _factor(
            weights["response"],
            accepted / answered if answered else None,
            f"{accepted}/{answered}" if answered else None,
        )
        when = last.get(key)
        days = (horizon - when).days if when else None
        factors["fairness"] = _factor(
            weights["fairness"], min(days, 90) / 90 if days is not None else 1.0, days
        )
        raw = sum(f["weight"] * f["score"] for f in factors.values()) / total_weight * 100
        results.append(
            Match(
                tutor=tutor,
                score=Decimal(str(round(raw, 1))),
                breakdown=factors,
                distance_km=km,
                slot_fit=shares,
                restricted=bool(reasons),
                reasons=reasons,
            )
        )
    results.sort(key=lambda m: (-m.score, m.tutor.last_name, m.tutor.first_name))
    return results[:limit]
