"""Client-facing tutor selection (FR-19-5, E19-T08): share a job's shortlist with the family.

``share()`` snapshots the shortlisted tutors, signs a link (``/shortlists/<token>``) that
expires after ``matching.share_expiry_days`` and emails it (E13 ``shortlist_shared``). The
public page shows tutor cards only: first name and initial, headline, public bio, approved
subjects, qualifications, experience, languages, rating and the published directory photo;
never surnames, contact details, addresses, pay rates or match scores. ``choose()`` records
the family's pick, alerts staff and (setting) offers the job to that tutor (FR-19-2).

``tutor_card()`` is also used by E17 proposals for their suggested tutors.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core import signing
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.time import now
from tutortrack.jobs.models import Job
from tutortrack.people.models import Contact, TutorProfile
from tutortrack.tenancy.settings_service import get_setting

from . import events
from .models import Shortlist, ShortlistShare

SALT = "shortlist-share"
CLOSED_JOB = (Job.Status.COMPLETED, Job.Status.CANCELLED)


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


# --- public tutor cards -------------------------------------------------------------------------


def public_name(tutor: TutorProfile) -> str:
    """The display name, else first name and the surname's initial."""
    if tutor.display_name:
        return tutor.display_name
    initial = f" {tutor.last_name[:1]}." if tutor.last_name else ""
    return f"{tutor.first_name}{initial}"


def ratings(tutor_ids: list[Any]) -> dict[str, tuple[float, int]]:
    """Families' opinions per tutor: E25 approved reviews and E09 lesson feedback."""
    from tutortrack.delivery.selectors import tutor_feedback_ratings
    from tutortrack.growth.selectors import tutor_ratings

    out: dict[str, tuple[float, int]] = {}
    for source in (tutor_ratings(tutor_ids), tutor_feedback_ratings(tutor_ids)):
        for key, (avg, n) in source.items():
            total, count = out.get(key, (0.0, 0))
            out[key] = (total + avg * n, count + n)
    return {k: (total / count, count) for k, (total, count) in out.items() if count}


def tutor_card(tutor: TutorProfile, rating: tuple[float, int] | None = None) -> dict[str, Any]:
    """What a family may see about a tutor before choosing (no contact details)."""
    from tutortrack.sites.models import PublicProfile

    profile = PublicProfile.objects.filter(
        tutor=tutor, status=PublicProfile.Status.APPROVED
    ).first()
    published = profile.published if profile is not None else {}
    subjects: list[dict[str, str]] = []
    for s in tutor.subjects.filter(approved=True).order_by("subject", "level"):
        row = {"subject": s.subject, "level": s.level}
        if row not in subjects:
            subjects.append(row)
    return {
        "id": str(tutor.pk),
        "name": public_name(tutor),
        "headline": published.get("headline") or tutor.headline,
        "bio": published.get("bio") or tutor.bio_public,
        "photo_url": (
            f"/api/v1/public/assets/{profile.photo_id}"
            if profile is not None and profile.photo_id
            else ""
        ),
        "subjects": subjects,
        "qualifications": [
            {"title": q.title, "institution": q.institution, "year": q.year}
            for q in tutor.qualifications.all().order_by("-year", "title")
        ],
        "years_experience": tutor.years_experience,
        "languages": list(tutor.languages or []),
        "online": tutor.delivers_online,
        "in_person": tutor.delivers_in_person,
        "rating": round(rating[0], 1) if rating else None,
        "rating_count": rating[1] if rating else 0,
    }


def tutor_cards(tutor_ids: list[Any]) -> list[dict[str, Any]]:
    tutors = {
        str(t.pk): t
        for t in TutorProfile.objects.filter(pk__in=tutor_ids).prefetch_related(
            "subjects", "qualifications"
        )
    }
    found = ratings(list(tutors))
    return [tutor_card(tutors[str(i)], found.get(str(i))) for i in tutor_ids if str(i) in tutors]


# --- tokens -------------------------------------------------------------------------------------


def token_for(share: ShortlistShare) -> str:
    return signing.dumps(str(share.pk), salt=f"{SALT}:{share.organisation_id}", compress=True)


def for_token(token: str) -> ShortlistShare:
    if not token or len(token) > 300:
        raise NotFound()
    try:
        pk = signing.loads(
            token, salt=f"{SALT}:{require_organisation_id()}", max_age=timedelta(days=120)
        )
    except signing.BadSignature:
        raise NotFound() from None
    share = ShortlistShare.objects.select_related("job", "job__service").filter(pk=pk).first()
    if share is None or share.status == ShortlistShare.Status.REVOKED:
        raise NotFound()
    return share


# --- staff --------------------------------------------------------------------------------------


@transaction.atomic
def share(
    job: Job,
    *,
    tutors: list[TutorProfile] | None = None,
    contact: Contact | None = None,
    message: str = "",
    days: int | None = None,
) -> tuple[ShortlistShare, str]:
    """Share the job's shortlist (or the chosen shortlisted tutors) with the family."""
    from tutortrack.comms import services as comms

    if job.status in CLOSED_JOB:
        raise BusinessRuleViolation(_("The job is closed."))
    shortlisted = list(
        Shortlist.objects.filter(job=job)
        .order_by("-score", "created_at")
        .values_list("tutor_id", flat=True)
    )
    if tutors is not None:
        chosen = [t.pk for t in tutors]
        if not set(chosen) <= set(shortlisted):
            raise _invalid("tutors", _("Share tutors from the job's shortlist."))
        shortlisted = chosen
    if not shortlisted:
        raise _invalid("tutors", _("Shortlist at least one tutor first."))
    if contact is not None and contact.client_id != job.client_id:
        raise _invalid("contact", _("Choose a contact of this family."))
    days = int(days or get_setting("matching.share_expiry_days"))
    record = ShortlistShare.objects.create(
        job=job,
        tutors=[str(t) for t in shortlisted],
        contact=contact or job.client.primary_contact or job.client.billing_contact,
        message=message[:2000],
        expires_at=now() + timedelta(days=days),
    )
    audit.record_create(record)
    token = token_for(record)
    publish(
        events.ShortlistShared(
            subject_id=record.pk,
            job_id=str(job.pk),
            tutor_ids=record.tutors,
            expires_at=record.expires_at.isoformat(),
        ),
        branch_id=job.branch_id,
    )
    payload = (str(record.pk), token)
    comms.notify_on_commit("shortlist_shared", payload, key=f"shortlist-share:{record.pk}")
    return record, token


@transaction.atomic
def revoke(record: ShortlistShare) -> ShortlistShare:
    record = ShortlistShare.objects.select_for_update().get(pk=record.pk)
    if record.status != ShortlistShare.Status.ACTIVE:
        raise BusinessRuleViolation(_("Only open links can be withdrawn."))
    with audit.track(record, action="revoke"):
        record.status = ShortlistShare.Status.REVOKED
        record.save(update_fields=["status", "updated_at"])
    return record


# --- the family ---------------------------------------------------------------------------------


def public_view(token: str) -> dict[str, Any]:
    """The shared page: a minimal job brief and the tutor cards. The first view is noted."""
    record = for_token(token)
    if record.viewed_at is None:
        ShortlistShare.objects.filter(pk=record.pk, viewed_at__isnull=True).update(viewed_at=now())
    job = record.job
    students = [
        link.student.preferred_name or link.student.first_name
        for link in job.students.filter(active_to__isnull=True).select_related("student")
    ]
    return {
        "status": record.state(now()),
        "expires_at": record.expires_at,
        "message": record.message,
        "job": {
            "subject": job.subject.name if job.subject is not None else "",
            "level": job.level.name if job.level is not None else "",
            "service": job.service.name,
            "students": students,
            "online": job.online,
        },
        "tutors": tutor_cards(record.tutors),
        "chosen_tutor": str(record.chosen_tutor_id) if record.chosen_tutor_id else None,
    }


@transaction.atomic
def choose(token: str, *, tutor_id: str, note: str = "") -> ShortlistShare:
    """The family picks a tutor. Staff are told and (setting) the job is offered to them."""
    record = ShortlistShare.objects.select_for_update().get(pk=for_token(token).pk)
    state = record.state(now())
    if state == "chosen":
        raise BusinessRuleViolation(
            _("You have already chosen a tutor. We'll be in touch."), extra={"code": "chosen"}
        )
    if state != "active":
        raise BusinessRuleViolation(_("This link has expired."), extra={"code": "expired"})
    if str(tutor_id) not in record.tutors:
        raise _invalid("tutor", _("Choose one of the tutors shown."))
    tutor = TutorProfile.objects.get(pk=tutor_id)
    with audit.track(record, action="choose"):
        record.status = ShortlistShare.Status.CHOSEN
        record.chosen_tutor = tutor
        record.chosen_at = now()
        record.client_note = note.strip()[:1000]
        record.save()
    batch = _offer(record, tutor)
    publish(
        events.ShortlistTutorChosen(
            subject_id=record.pk,
            job_id=str(record.job_id),
            tutor_id=str(tutor.pk),
            offer_batch_id=str(batch.pk) if batch else None,
        ),
        branch_id=record.job.branch_id,
    )
    _tell_staff(record, tutor, offered=batch is not None)
    return record


def _offer(record: ShortlistShare, tutor: TutorProfile) -> Any:
    """Feed the choice into the offer flow when possible; otherwise staff decide."""
    from . import services

    if not get_setting("matching.share_choice_starts_offer"):
        return None
    try:
        with transaction.atomic():
            batch = services.start_offers(record.job, [tutor])
    except BusinessRuleViolation:
        return None  # offers already out, tutor restricted...: staff take it from here
    ShortlistShare.objects.filter(pk=record.pk).update(offer_batch=batch)
    record.offer_batch = batch
    return batch


def _tell_staff(record: ShortlistShare, tutor: TutorProfile, *, offered: bool) -> None:
    from tutortrack.comms import services as comms

    job = record.job
    title = _("%(family)s chose %(tutor)s") % {
        "family": job.client.display_name,
        "tutor": tutor.full_name,
    }
    body = (
        _("The job has been offered to them.")
        if offered
        else _("Send them an offer when you're ready.")
    )
    if record.client_note:
        body = f"{body}\n\n{record.client_note}"
    payload = (title, body, f"/jobs/{job.pk}/match")
    comms.notify_on_commit("staff_shortlist_choice", payload, key=f"choice:{record.pk}")
