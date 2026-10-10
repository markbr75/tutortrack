"""Matching writes (E19): searches, shortlists, offers, the job board and cover requests.

Offers run in ``JobOfferCascadeWorkflow`` and cover requests in ``CoverRequestWorkflow``
(``processes.py``); the activities there call the functions below, which are idempotent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.jobs.models import Job, JobTutor
from tutortrack.people.models import TutorProfile

from . import engine, events
from .models import (
    CoverLesson,
    CoverRequest,
    JobOffer,
    JobPosting,
    JobPostingApplication,
    MatchQuery,
    MatchResult,
    OfferBatch,
    Shortlist,
)

OPEN_BATCH = (OfferBatch.Status.OPEN, OfferBatch.Status.AWAITING_CONFIRMATION)
CLOSED_JOB = (Job.Status.COMPLETED, Job.Status.CANCELLED)


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def _setting(key: str) -> Any:
    from tutortrack.tenancy.settings_service import get_setting

    return get_setting(key)


def _alert(type_key: str, title: str, body: str, link: str, key: str) -> None:
    from tutortrack.comms import services as comms

    transaction.on_commit(lambda: comms.notify(type_key, (title, body, link), key=key))


def _notify(type_key: str, subject: Any, key: str) -> None:
    from tutortrack.comms import services as comms

    transaction.on_commit(lambda: comms.notify(type_key, subject, key=key))


# --- search -------------------------------------------------------------------------------------


@transaction.atomic
def run_search(
    criteria: engine.Criteria,
    *,
    include_restricted: bool = False,
    limit: int = 50,
    job: Job | None = None,
) -> tuple[MatchQuery, list[engine.Match]]:
    """Search and keep the query and its ranked results (for analytics and audit)."""
    matches = engine.search(criteria, include_restricted=include_restricted, limit=limit)
    query = MatchQuery.objects.create(
        job=job,
        criteria=criteria.to_json(),
        include_restricted=include_restricted,
        result_count=len(matches),
        top_score=matches[0].score if matches else None,
    )
    MatchResult.objects.bulk_create(
        [
            MatchResult(
                organisation_id=query.organisation_id,
                query=query,
                tutor=m.tutor,
                rank=rank,
                score=m.score,
                breakdown=m.breakdown,
                restricted=m.restricted,
            )
            for rank, m in enumerate(matches, start=1)
        ]
    )
    if include_restricted:
        audit.record(query, "include_restricted", {"include_restricted": [False, True]})
    return query, matches


def score_tutor(job: Job, tutor: TutorProfile) -> engine.Match | None:
    """The tutor's match against the job, or ``None`` when a hard filter excludes them."""
    criteria = engine.criteria_for_job(job)
    criteria.exclude.discard(str(tutor.pk))
    found = engine.search(criteria, only=[str(tutor.pk)])
    return found[0] if found else None


@transaction.atomic
def set_weights(weights: dict[str, Any]) -> dict[str, float]:
    from tutortrack.tenancy.settings_service import update_settings

    from .org_settings import DEFAULT_WEIGHTS

    cleaned = {}
    for key, value in weights.items():
        if key not in DEFAULT_WEIGHTS:
            raise _invalid("weights", _("Unknown factor: %(key)s") % {"key": key})
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise _invalid("weights", _("Weights are numbers from 0 to 100.")) from exc
        if not 0 <= number <= 100:
            raise _invalid("weights", _("Weights are numbers from 0 to 100."))
        cleaned[key] = number
    merged = {**DEFAULT_WEIGHTS, **cleaned}
    if not any(merged.values()):
        raise _invalid("weights", _("At least one factor needs a weight."))
    update_settings("matching", {"matching.weights": merged})
    return {k: float(v) for k, v in merged.items()}


# --- shortlist ----------------------------------------------------------------------------------


@transaction.atomic
def shortlist_add(job: Job, tutor: TutorProfile, *, note: str = "") -> Shortlist:
    if job.status in CLOSED_JOB:
        raise BusinessRuleViolation(_("The job is closed."))
    match = score_tutor(job, tutor)
    entry, created = Shortlist.objects.get_or_create(
        job=job,
        tutor=tutor,
        defaults={
            "score": match.score if match else None,
            "breakdown": match.breakdown if match else {},
            "note": note,
        },
    )
    if created:
        audit.record_create(entry)
    return entry


@transaction.atomic
def shortlist_remove(entry: Shortlist) -> None:
    audit.record(entry, "delete")
    entry.delete()


# --- offers -------------------------------------------------------------------------------------


def job_brief(job: Job, *, pay_rate: Money | None = None) -> dict[str, Any]:
    """What a tutor sees before accepting: no surnames, no street address (FR-19-2)."""
    students = [
        link.student
        for link in job.students.filter(active_to__isnull=True).select_related("student")
    ]
    names = [
        f"{s.preferred_name or s.first_name} {s.last_name[:1]}.".strip().rstrip(" .") + "."
        if s.last_name
        else (s.preferred_name or s.first_name)
        for s in students
    ]
    return {
        "job": str(job.pk),
        "reference": job.reference,
        "students": names,
        "year_groups": [s.year_group for s in students if s.year_group],
        "subject": job.subject.name if job.subject is not None else "",
        "level": job.level.name if job.level is not None else "",
        "service": job.service.name,
        "mode": "online" if job.online else "in_person",
        "area": engine.area_of(engine.job_place(job)),
        "schedule": list(job.default_schedule or []),
        "duration_minutes": job.default_duration_minutes,
        "start_date": job.start_date.isoformat() if job.start_date else None,
        "pay_rate": (
            {"amount": str(pay_rate.amount), "currency": pay_rate.currency} if pay_rate else None
        ),
        "notes": job.notes_for_tutor,
    }


def _check_offerable(job: Job, tutor: TutorProfile) -> None:
    from tutortrack.people.assignability import check_assignable

    check_assignable(tutor, "tutors")
    if job.tutors.filter(
        tutor=tutor, status__in=[JobTutor.Status.OFFERED, JobTutor.Status.ACTIVE]
    ).exists():
        raise _invalid("tutors", _("%(name)s is already on this job.") % {"name": tutor.full_name})


@transaction.atomic
def start_offers(
    job: Job,
    tutors: list[TutorProfile],
    *,
    mode: str = OfferBatch.Mode.SEQUENTIAL,
    expiry_hours: int | None = None,
    admin_confirms: bool | None = None,
    pay_rate: Money | None = None,
) -> OfferBatch:
    """Offer the job to ``tutors`` (in this order for a sequential cascade)."""
    job = Job.objects.select_for_update().get(pk=job.pk)
    if job.status in CLOSED_JOB:
        raise BusinessRuleViolation(_("The job is closed."))
    if not tutors:
        raise _invalid("tutors", _("Choose at least one tutor."))
    if len({t.pk for t in tutors}) != len(tutors):
        raise _invalid("tutors", _("A tutor is listed twice."))
    if OfferBatch.objects.filter(job=job, status__in=OPEN_BATCH).exists():
        raise BusinessRuleViolation(
            _("Offers for this job are still out. Cancel them before sending new ones.")
        )
    if pay_rate is not None and pay_rate.currency != job.currency:
        raise _invalid("pay_rate", _("Use %(c)s, the job's currency.") % {"c": job.currency})
    for tutor in tutors:
        _check_offerable(job, tutor)
    hours = int(expiry_hours or _setting("matching.offer_expiry_hours"))
    batch = OfferBatch(
        job=job,
        mode=mode,
        expiry_hours=hours,
        admin_confirms=(
            bool(_setting("matching.admin_confirms")) if admin_confirms is None else admin_confirms
        ),
        brief=job_brief(job, pay_rate=pay_rate),
        currency=job.currency,
    )
    batch.pay_rate = pay_rate
    batch.save()
    JobOffer.objects.bulk_create(
        [
            JobOffer(
                organisation_id=batch.organisation_id,
                batch=batch,
                job=job,
                tutor=tutor,
                cascade_order=order,
            )
            for order, tutor in enumerate(tutors)
        ]
    )
    audit.record_create(batch)
    publish(
        events.OfferBatchStarted(
            subject_id=batch.pk, job_id=str(job.pk), mode=mode, tutors=len(tutors)
        ),
        branch_id=job.branch_id,
    )
    return batch


def plan_offers(batch_id: str) -> list[list[str]]:
    """Waves of offers: everyone at once, or one tutor per wave."""
    batch = OfferBatch.objects.get(pk=batch_id)
    ids = [str(pk) for pk in batch.offers.order_by("cascade_order").values_list("pk", flat=True)]
    if batch.mode == OfferBatch.Mode.SIMULTANEOUS:
        return [ids]
    return [[pk] for pk in ids]


def _offer_event(offer: JobOffer, cls: type, **extra: Any) -> None:
    publish(
        cls(
            subject_id=offer.pk,
            batch_id=str(offer.batch_id),
            job_id=str(offer.job_id),
            tutor_id=str(offer.tutor_id),
            **extra,
        )
    )


@transaction.atomic
def send_offers(batch_id: str, offer_ids: list[str], expires_at: datetime) -> list[str]:
    """Send queued offers in a wave. A tutor who is no longer offerable (restricted, already
    on the job) is skipped and the offer withdrawn. Returns the offers now out."""
    batch = OfferBatch.objects.select_for_update().get(pk=batch_id)
    if batch.status not in OPEN_BATCH:
        return []
    sent = []
    for offer in JobOffer.objects.select_for_update().filter(pk__in=offer_ids).select_related(
        "tutor", "job"
    ):  # fmt: skip
        if offer.status == JobOffer.Status.SENT:
            sent.append(str(offer.pk))
            continue
        if offer.status != JobOffer.Status.QUEUED:
            continue
        try:
            _check_offerable(offer.job, offer.tutor)
        except BusinessRuleViolation as exc:
            offer.status = JobOffer.Status.WITHDRAWN
            offer.decline_reason = str(exc)[:300]
            offer.save(update_fields=["status", "decline_reason", "updated_at"])
            continue
        offer.status = JobOffer.Status.SENT
        offer.sent_at = now()
        offer.expires_at = expires_at
        offer.save(update_fields=["status", "sent_at", "expires_at", "updated_at"])
        _offer_event(offer, events.JobOfferSent)
        _notify("job_offer", offer, key=f"offer:{offer.pk}")
        sent.append(str(offer.pk))
    return sent


@transaction.atomic
def respond(offer: JobOffer, *, accept: bool, reason: str = "") -> JobOffer:
    """The tutor accepts or declines. The cascade decides who gets the job."""
    offer = JobOffer.objects.select_for_update().select_related("batch").get(pk=offer.pk)
    if offer.status != JobOffer.Status.SENT or offer.batch.status not in OPEN_BATCH:
        raise BusinessRuleViolation(_("This offer is no longer open."))
    if offer.expires_at and offer.expires_at <= now():
        raise BusinessRuleViolation(_("This offer has expired."))
    with audit.track(offer, action="accept" if accept else "decline"):
        offer.status = JobOffer.Status.ACCEPTED if accept else JobOffer.Status.DECLINED
        offer.responded_at = now()
        offer.decline_reason = "" if accept else reason[:300]
        offer.save(update_fields=["status", "responded_at", "decline_reason", "updated_at"])
    if accept:
        _offer_event(offer, events.JobOfferAccepted)
    else:
        _offer_event(offer, events.JobOfferDeclined, reason=offer.decline_reason)
    return offer


def offer_state(batch_id: str, offer_ids: list[str]) -> dict[str, Any]:
    """Where a wave stands: accepted offers (first first), still pending, and whether a
    coordinator approved or rejected the accepted one."""
    batch = OfferBatch.objects.get(pk=batch_id)
    offers = list(JobOffer.objects.filter(pk__in=offer_ids))
    accepted = sorted(
        (o for o in offers if o.status == JobOffer.Status.ACCEPTED),
        key=lambda o: o.responded_at or o.updated_at,
    )
    return {
        "batch": batch.status,
        "accepted": [str(o.pk) for o in accepted],
        "confirmed": [str(o.pk) for o in accepted if o.confirmed_at is not None],
        "pending": [str(o.pk) for o in offers if o.status == JobOffer.Status.SENT],
    }


@transaction.atomic
def expire_offers(offer_ids: list[str]) -> int:
    count = 0
    for offer in JobOffer.objects.select_for_update().filter(
        pk__in=offer_ids, status=JobOffer.Status.SENT
    ):
        offer.status = JobOffer.Status.EXPIRED
        offer.save(update_fields=["status", "updated_at"])
        _offer_event(offer, events.JobOfferExpired)
        count += 1
    return count


@transaction.atomic
def request_confirmation(batch_id: str, offer_id: str) -> bool:
    batch = OfferBatch.objects.select_for_update().select_related("job").get(pk=batch_id)
    if batch.status != OfferBatch.Status.OPEN:
        return False
    offer = JobOffer.objects.select_related("tutor").get(pk=offer_id)
    batch.status = OfferBatch.Status.AWAITING_CONFIRMATION
    batch.accepted_offer = offer
    batch.save(update_fields=["status", "accepted_offer", "updated_at"])
    _alert(
        "staff_offer_accepted",
        _("%(tutor)s accepted %(job)s") % {"tutor": offer.tutor.full_name, "job": batch.job},
        _("Confirm the tutor to assign them to the job."),
        f"/jobs/{batch.job_id}/match",
        key=f"confirm:{offer.pk}",
    )
    return True


@transaction.atomic
def decide(batch: OfferBatch, *, approve: bool, reason: str = "") -> OfferBatch:
    """A coordinator confirms (or turns down) the tutor who accepted."""
    batch = OfferBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status != OfferBatch.Status.AWAITING_CONFIRMATION or batch.accepted_offer_id is None:
        raise BusinessRuleViolation(_("No accepted offer is waiting for confirmation."))
    offer = JobOffer.objects.select_for_update().get(pk=batch.accepted_offer_id)
    with audit.track(offer, action="confirm" if approve else "reject"):
        if approve:
            offer.confirmed_at = now()
        else:
            offer.status = JobOffer.Status.DECLINED
            offer.decline_reason = (reason or _("Not confirmed by the coordinator"))[:300]
        offer.save()
    if not approve:
        batch.status = OfferBatch.Status.OPEN
        batch.accepted_offer = None
        batch.save(update_fields=["status", "accepted_offer", "updated_at"])
    publish(events.OfferDecided(subject_id=offer.pk, batch_id=str(batch.pk), approved=approve))
    return batch


def _assign(job: Job, tutor: TutorProfile, pay_rate: Money | None) -> JobTutor:
    """Put the tutor on the job, create its lesson series if it has none, introduce them."""
    from tutortrack.jobs import services as jobs
    from tutortrack.scheduling import services as scheduling

    link = jobs.add_tutor(job, tutor=tutor, pay_rate_override=pay_rate)
    job.refresh_from_db()
    scheduling.schedule_from_job(job)
    _notify("job_intro_tutor", link, key=f"intro:{link.pk}")
    _notify("job_intro_client", link, key=f"intro:{link.pk}")
    return link


def _withdraw(offer: JobOffer, reason: str) -> None:
    offer.status = JobOffer.Status.WITHDRAWN
    offer.decline_reason = reason[:300]
    offer.save(update_fields=["status", "decline_reason", "updated_at"])
    _offer_event(offer, events.JobOfferWithdrawn)
    if offer.sent_at is not None:
        _notify("job_offer_withdrawn", offer, key=f"withdrawn:{offer.pk}")


def _close(batch: OfferBatch, status: str) -> None:
    batch.status = status
    batch.closed_at = now()
    batch.save(update_fields=["status", "closed_at", "accepted_offer", "updated_at"])
    publish(
        events.OfferBatchClosed(subject_id=batch.pk, job_id=str(batch.job_id), status=status),
        branch_id=batch.job.branch_id,
    )


@transaction.atomic
def fill(batch_id: str, offer_id: str) -> str:
    """First acceptance wins: assign the tutor, withdraw the other offers. Returns
    ``filled``, ``skipped`` (the tutor can no longer take it; their offer is withdrawn and
    the cascade goes on) or ``closed``."""
    batch = OfferBatch.objects.select_for_update().select_related("job").get(pk=batch_id)
    if batch.status not in OPEN_BATCH:
        return "closed"
    offer = JobOffer.objects.select_for_update().select_related("tutor").get(pk=offer_id)
    if offer.status != JobOffer.Status.ACCEPTED:
        return "skipped"
    if batch.job.status in CLOSED_JOB:
        _close(batch, OfferBatch.Status.CANCELLED)
        return "closed"
    try:
        _check_offerable(batch.job, offer.tutor)
    except BusinessRuleViolation as exc:
        _withdraw(offer, str(exc))
        if batch.status == OfferBatch.Status.AWAITING_CONFIRMATION:
            batch.status = OfferBatch.Status.OPEN
            batch.accepted_offer = None
            batch.save(update_fields=["status", "accepted_offer", "updated_at"])
        return "skipped"
    _assign(batch.job, offer.tutor, batch.pay_rate)
    for other in batch.offers.select_for_update().filter(
        status__in=[JobOffer.Status.QUEUED, JobOffer.Status.SENT, JobOffer.Status.ACCEPTED]
    ).exclude(pk=offer.pk):  # fmt: skip
        _withdraw(other, _("Another tutor took the job"))
    batch.accepted_offer = offer
    _close(batch, OfferBatch.Status.FILLED)
    return "filled"


@transaction.atomic
def exhaust(batch_id: str) -> bool:
    batch = OfferBatch.objects.select_for_update().select_related("job").get(pk=batch_id)
    if batch.status not in OPEN_BATCH:
        return False
    for offer in batch.offers.select_for_update().filter(status=JobOffer.Status.QUEUED):
        _withdraw(offer, _("The offers ended"))
    _close(batch, OfferBatch.Status.EXHAUSTED)
    _alert(
        "staff_offers_exhausted",
        _("No tutor accepted %(job)s") % {"job": batch.job},
        _("Every offer was declined or expired. Search again or post the job."),
        f"/jobs/{batch.job_id}/match",
        key=f"exhausted:{batch.pk}",
    )
    return True


@transaction.atomic
def cancel_batch(batch: OfferBatch) -> OfferBatch:
    batch = OfferBatch.objects.select_for_update().select_related("job").get(pk=batch.pk)
    if batch.status not in OPEN_BATCH:
        raise BusinessRuleViolation(_("These offers are already closed."))
    with audit.track(batch, action="cancel"):
        for offer in batch.offers.select_for_update().filter(
            status__in=[JobOffer.Status.QUEUED, JobOffer.Status.SENT, JobOffer.Status.ACCEPTED]
        ):
            _withdraw(offer, _("The offer was withdrawn"))
        _close(batch, OfferBatch.Status.CANCELLED)
    return batch


@transaction.atomic
def withdraw_offer(offer: JobOffer) -> JobOffer:
    """Withdraw one tutor's offer; the cascade moves on to the next."""
    offer = JobOffer.objects.select_for_update().get(pk=offer.pk)
    if offer.status not in (JobOffer.Status.QUEUED, JobOffer.Status.SENT):
        raise BusinessRuleViolation(_("This offer is no longer open."))
    with audit.track(offer, action="withdraw"):
        _withdraw(offer, _("The offer was withdrawn"))
    return offer


# --- job board ----------------------------------------------------------------------------------


@transaction.atomic
def publish_posting(
    job: Job,
    *,
    title: str = "",
    min_score: Decimal | int = 0,
    closes_on: Any = None,
) -> JobPosting:
    """Post the job for every eligible tutor (those passing the hard filters, scoring at
    least ``min_score``) and tell them."""
    if job.status in CLOSED_JOB:
        raise BusinessRuleViolation(_("The job is closed."))
    if JobPosting.objects.filter(job=job, status=JobPosting.Status.OPEN).exists():
        raise BusinessRuleViolation(_("This job is already on the job board."))
    matches = engine.search(engine.criteria_for_job(job), limit=1000)
    eligible = [str(m.tutor.pk) for m in matches if m.score >= Decimal(str(min_score))]
    brief = job_brief(job)
    posting = JobPosting.objects.create(
        job=job,
        title=title or " ".join(p for p in (brief["subject"], brief["level"]) if p) or job.name,
        brief=brief,
        audience={"min_score": float(min_score)},
        eligible=eligible,
        published_at=now(),
        closes_on=closes_on,
    )
    audit.record_create(posting)
    publish(
        events.JobPostingPublished(
            subject_id=posting.pk, job_id=str(job.pk), eligible=len(eligible)
        ),
        branch_id=job.branch_id,
    )
    for tutor in TutorProfile.objects.filter(pk__in=eligible):
        _notify("job_posting", (posting, tutor), key=f"posting:{posting.pk}:{tutor.pk}")
    return posting


@transaction.atomic
def apply_to_posting(
    posting: JobPosting,
    tutor: TutorProfile,
    *,
    message: str = "",
    proposed_availability: list[dict[str, Any]] | None = None,
) -> JobPostingApplication:
    posting = JobPosting.objects.select_for_update().select_related("job").get(pk=posting.pk)
    if posting.status != JobPosting.Status.OPEN or (
        posting.closes_on and posting.closes_on < now().date()
    ):
        raise BusinessRuleViolation(_("This job is no longer taking applications."))
    if str(tutor.pk) not in posting.eligible:
        raise BusinessRuleViolation(_("This job isn't open to you."))
    from tutortrack.jobs.services import _clean_schedule

    proposed = _clean_schedule(proposed_availability or [])
    match = score_tutor(posting.job, tutor)
    application, created = JobPostingApplication.objects.get_or_create(posting=posting, tutor=tutor)
    if not created and application.status != JobPostingApplication.Status.WITHDRAWN:
        raise BusinessRuleViolation(_("You've already applied for this job."))
    application.status = JobPostingApplication.Status.APPLIED
    application.message = message
    application.proposed_availability = proposed
    application.score = match.score if match else None
    application.breakdown = match.breakdown if match else {}
    application.save()
    audit.record_create(application)
    publish(
        events.JobPostingApplicationReceived(
            subject_id=posting.pk, tutor_id=str(tutor.pk), application_id=str(application.pk)
        ),
        branch_id=posting.job.branch_id,
    )
    _alert(
        "staff_job_application",
        _("%(tutor)s applied for %(job)s") % {"tutor": tutor.full_name, "job": posting.title},
        message[:200],
        f"/jobs/{posting.job_id}/match",
        key=f"application:{application.pk}",
    )
    return application


@transaction.atomic
def withdraw_application(application: JobPostingApplication) -> JobPostingApplication:
    if application.status != JobPostingApplication.Status.APPLIED:
        raise BusinessRuleViolation(_("This application is closed."))
    with audit.track(application, action="withdraw"):
        application.status = JobPostingApplication.Status.WITHDRAWN
        application.save(update_fields=["status", "updated_at"])
    return application


def _close_posting(posting: JobPosting, status: str, keep: Any = None) -> None:
    posting.status = status
    posting.closed_at = now()
    posting.save(update_fields=["status", "closed_at", "updated_at"])
    others = posting.applications.filter(status=JobPostingApplication.Status.APPLIED)
    if keep is not None:
        others = others.exclude(pk=keep.pk)
    for other in others:
        other.status = JobPostingApplication.Status.REJECTED
        other.save(update_fields=["status", "updated_at"])
        _notify("job_application_unsuccessful", other, key=f"unsuccessful:{other.pk}")


@transaction.atomic
def select_applicant(application: JobPostingApplication) -> JobPostingApplication:
    posting = JobPosting.objects.select_for_update().select_related("job").get(
        pk=application.posting_id
    )  # fmt: skip
    application = JobPostingApplication.objects.select_related("tutor").get(pk=application.pk)
    if posting.status != JobPosting.Status.OPEN:
        raise BusinessRuleViolation(_("This posting is closed."))
    if application.status != JobPostingApplication.Status.APPLIED:
        raise BusinessRuleViolation(_("This application is closed."))
    _check_offerable(posting.job, application.tutor)
    _assign(posting.job, application.tutor, None)
    with audit.track(application, action="select"):
        application.status = JobPostingApplication.Status.SELECTED
        application.save(update_fields=["status", "updated_at"])
    _close_posting(posting, JobPosting.Status.FILLED, keep=application)
    publish(
        events.JobPostingFilled(
            subject_id=posting.pk, job_id=str(posting.job_id), tutor_id=str(application.tutor_id)
        ),
        branch_id=posting.job.branch_id,
    )
    return application


@transaction.atomic
def reject_applicant(application: JobPostingApplication) -> JobPostingApplication:
    if application.status != JobPostingApplication.Status.APPLIED:
        raise BusinessRuleViolation(_("This application is closed."))
    with audit.track(application, action="reject"):
        application.status = JobPostingApplication.Status.REJECTED
        application.save(update_fields=["status", "updated_at"])
    _notify("job_application_unsuccessful", application, key=f"unsuccessful:{application.pk}")
    return application


@transaction.atomic
def close_posting(posting: JobPosting) -> JobPosting:
    posting = JobPosting.objects.select_for_update().get(pk=posting.pk)
    if posting.status != JobPosting.Status.OPEN:
        raise BusinessRuleViolation(_("This posting is already closed."))
    with audit.track(posting, action="close"):
        _close_posting(posting, JobPosting.Status.CLOSED)
    return posting


# --- cover requests -----------------------------------------------------------------------------


def _lesson_tutor(lesson: Any) -> str | None:
    tutors = [str(t) for t in lesson.tutors.values_list("tutor_id", flat=True)]
    return tutors[0] if len(tutors) == 1 else None


@transaction.atomic
def create_cover(
    lessons: list[Any], *, reason: str = "", tutor: TutorProfile | None = None
) -> CoverRequest:
    """Ask for cover for ``lessons`` (one tutor's planned future lessons)."""
    from tutortrack.scheduling.models import Lesson

    if not lessons:
        raise _invalid("lessons", _("Choose at least one lesson."))
    original: str | None = str(tutor.pk) if tutor is not None else None
    current = now()
    for lesson in lessons:
        if lesson.status != Lesson.Status.PLANNED or lesson.start <= current:
            raise _invalid("lessons", _("Only planned future lessons can be covered."))
        on_lesson = [str(t) for t in lesson.tutors.values_list("tutor_id", flat=True)]
        if original is None:
            if len(on_lesson) != 1:
                raise _invalid("lessons", _("Choose lessons with one tutor."))
            original = on_lesson[0]
        if original not in on_lesson:
            raise _invalid("lessons", _("All the lessons must be the same tutor's."))
    if CoverLesson.objects.filter(
        lesson__in=lessons, request__status=CoverRequest.Status.OPEN
    ).exists():
        raise _invalid("lessons", _("Cover is already being found for one of these lessons."))
    cutoff = timedelta(hours=int(_setting("matching.cover_cutoff_hours")))
    deadline = min(lesson.start for lesson in lessons) - cutoff
    if deadline <= current:
        raise _invalid("lessons", _("It's too late to find cover; reassign the lesson directly."))
    request = CoverRequest.objects.create(
        original_tutor_id=original, reason=reason[:300], deadline=deadline
    )
    for lesson in lessons:
        CoverLesson.objects.create(request=request, lesson=lesson)
    audit.record_create(request)
    publish(
        events.CoverRequestCreated(
            subject_id=request.pk,
            tutor_id=str(original),
            lessons=len(lessons),
            deadline=deadline.isoformat(),
        )
    )
    return request


def _cover_lessons(request: CoverRequest) -> list[Any]:
    from tutortrack.scheduling.models import Lesson

    return list(
        Lesson.objects.filter(pk__in=request.lessons.values("lesson_id"))
        .select_related("job__branch", "job__service", "service")
        .order_by("start")
    )


def cover_candidates(request: CoverRequest, *, limit: int = 50) -> list[engine.Match]:
    """Tutors free for every lesson, best first."""
    lessons = _cover_lessons(request)
    if not lessons:
        return []
    job = lessons[0].job
    if job is not None:
        criteria = engine.criteria_for_job(job)
        criteria.slots = []
    else:
        criteria = engine.Criteria(mode="online" if lessons[0].online else "either")
    criteria.intervals = [(lesson.start, lesson.end) for lesson in lessons]
    criteria.exclude = criteria.exclude | {str(request.original_tutor_id)}
    matches = engine.search(criteria, limit=limit * 3)
    return [m for m in matches if m.slot_fit and min(m.slot_fit) >= 1.0][:limit]


@transaction.atomic
def notify_cover(request_id: str) -> int:
    request = CoverRequest.objects.select_for_update().get(pk=request_id)
    if request.status != CoverRequest.Status.OPEN:
        return 0
    if request.notified:
        return len(request.notified)
    limit = int(_setting("matching.cover_notify_limit"))
    chosen = cover_candidates(request, limit=limit)
    request.notified = [str(m.tutor.pk) for m in chosen]
    request.save(update_fields=["notified", "updated_at"])
    for match in chosen:
        _notify("cover_request", (request, match.tutor), key=f"cover:{request.pk}:{match.tutor.pk}")
    return len(chosen)


@transaction.atomic
def accept_cover(
    request: CoverRequest, tutor: TutorProfile, *, by_staff: bool = False
) -> CoverRequest:
    """First acceptance wins: the lessons move to ``tutor`` for those dates only."""
    from tutortrack.scheduling import services as scheduling

    request = CoverRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != CoverRequest.Status.OPEN:
        raise BusinessRuleViolation(_("This cover has already been arranged or closed."))
    if not by_staff and str(tutor.pk) not in request.notified:
        raise BusinessRuleViolation(_("This cover request wasn't sent to you."))
    if str(tutor.pk) == str(request.original_tutor_id):
        raise _invalid("tutor", _("Choose a different tutor."))
    lessons = _cover_lessons(request)
    for lesson in lessons:
        rows = [
            {"tutor": t.tutor, "pay_rate_override": t.pay_rate_override}
            for t in lesson.tutors.select_related("tutor")
            if str(t.tutor_id) != str(request.original_tutor_id)
        ]
        scheduling.update_lesson(
            lesson, tutors=[*rows, {"tutor": tutor}], reason=_("Cover"), notify=True
        )
    with audit.track(request, action="accept"):
        request.status = CoverRequest.Status.FILLED
        request.accepted_by = tutor
        request.accepted_at = now()
        request.closed_at = now()
        request.save()
    publish(events.CoverRequestAccepted(subject_id=request.pk, tutor_id=str(tutor.pk)))
    publish(
        events.CoverRequestFilled(
            subject_id=request.pk, tutor_id=str(tutor.pk), lessons=len(lessons)
        )
    )
    return request


@transaction.atomic
def mark_unfilled(request_id: str) -> bool:
    request = CoverRequest.objects.select_for_update().select_related("original_tutor").get(
        pk=request_id
    )  # fmt: skip
    if request.status != CoverRequest.Status.OPEN:
        return False
    request.status = CoverRequest.Status.UNFILLED
    request.closed_at = now()
    request.save(update_fields=["status", "closed_at", "updated_at"])
    publish(events.CoverRequestUnfilled(subject_id=request.pk))
    _alert(
        "staff_cover_unfilled",
        _("No cover found for %(tutor)s") % {"tutor": request.original_tutor.full_name},
        _("Reassign or cancel the lessons."),
        "/cover-requests",
        key=f"unfilled:{request.pk}",
    )
    return True


@transaction.atomic
def cancel_cover(request: CoverRequest) -> CoverRequest:
    request = CoverRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != CoverRequest.Status.OPEN:
        raise BusinessRuleViolation(_("This cover request is already closed."))
    with audit.track(request, action="cancel"):
        request.status = CoverRequest.Status.CANCELLED
        request.closed_at = now()
        request.save()
    publish(events.CoverRequestCancelled(subject_id=request.pk))
    return request
