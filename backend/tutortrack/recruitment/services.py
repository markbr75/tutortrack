"""Recruitment and onboarding (E18): job openings and applications, the recruitment
pipeline with scorecards, interviews and references, approval into a tutor with an
onboarding checklist, and subject competency.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.time import now
from tutortrack.people.models import TutorProfile
from tutortrack.tenancy.settings_service import get_setting

from . import catalogue, compliance, events
from .models import (
    ApplicationStage,
    ChecklistInstance,
    ChecklistTemplate,
    Interview,
    JobOpening,
    ReferenceRequest,
    Scorecard,
    TutorApplication,
)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def stages() -> list[ApplicationStage]:
    existing = list(ApplicationStage.objects.all())
    if existing:
        return existing
    with transaction.atomic():
        for order, (name, kind, criteria) in enumerate(catalogue.STAGES):
            ApplicationStage.objects.create(name=name, kind=kind, order=order, criteria=criteria)
    return list(ApplicationStage.objects.all())


def _stage(kind: str) -> ApplicationStage:
    return next(s for s in stages() if s.kind == kind)


# --- job openings (T01; G5a editor) ---------------------------------------------------------

OPENING_FIELDS = (
    "title",
    "slug",
    "description",
    "subjects",
    "location",
    "branch",
    "form",
    "published",
    "closes_on",
)


def default_application_form() -> Any:
    """The standard tutor application form (FR-18-1: details, subjects, qualifications,
    experience, right to work, CV and video uploads, referees, privacy notice), created on
    first use and then edited like any other form."""
    from django.utils.text import slugify

    from tutortrack.leads.models import Form

    existing = Form.objects.filter(type=Form.Type.APPLICATION, settings__standard=True).first()
    if existing is not None:
        return existing
    slug = "tutor-application"
    n = 1
    while Form.objects.filter(slug=slug).exists():
        n += 1
        slug = slugify(f"tutor-application-{n}")
    form = Form.objects.create(
        name=_("Tutor application"),
        slug=slug,
        type=Form.Type.APPLICATION,
        schema=catalogue.APPLICATION_FORM,
        settings={"standard": True},
        published=True,
    )
    audit.record(form, "create", {"name": [None, form.name]})
    return form


@transaction.atomic
def save_opening(opening: JobOpening | None, *, user: Any = None, **data: Any) -> JobOpening:
    """Create or edit a job opening (G5a admin editor). The slug is unique per organisation
    and the form must be a tutor application form."""
    from django.utils.text import slugify

    from tutortrack.leads.models import Form

    created = opening is None
    opening = opening or JobOpening()
    data = {k: v for k, v in data.items() if k in OPENING_FIELDS}
    if "slug" in data or created:
        slug = slugify(data.get("slug") or data.get("title") or opening.title)[:80]
        if not slug:
            raise BusinessRuleViolation(
                _("Give the opening a title."), extra={"errors": {"title": [_("Required.")]}}
            )
        clash = JobOpening.objects.filter(slug=slug)
        if not created:
            clash = clash.exclude(pk=opening.pk)
        if clash.exists():
            raise BusinessRuleViolation(
                _("Another opening uses this web address."),
                extra={"errors": {"slug": [_("Choose another.")]}},
            )
        data["slug"] = slug
    form = data.pop("form", None) or (None if not created else default_application_form())
    if form is not None:
        if form.type != Form.Type.APPLICATION:
            raise BusinessRuleViolation(
                _("Choose a tutor application form."),
                extra={"errors": {"form": [_("Choose a tutor application form.")]}},
            )
        data["form"] = form
    if "subjects" in data:
        from tutortrack.leads.forms import _subjects

        data["subjects"] = _subjects(data["subjects"])
    with audit.track(opening, action="create" if created else "update"):
        for key, value in data.items():
            setattr(opening, key, value)
        opening.save()
    return opening


# --- applications (T01) ---------------------------------------------------------------------


@transaction.atomic
def apply(
    opening: JobOpening,
    data: dict[str, Any],
    *,
    ip: str | None = None,
    user_agent: str = "",
    utm: dict[str, Any] | None = None,
    honeypot: str = "",
) -> TutorApplication | None:
    """A public application through the opening's form (FR-18-1)."""
    from tutortrack.leads import forms
    from tutortrack.leads.models import FormSubmission

    if not opening.published or (opening.closes_on and opening.closes_on < compliance.today()):
        raise NotFound()
    submission = FormSubmission.objects.create(
        form=opening.form,
        data=data,
        ip=ip,
        user_agent=user_agent[:300],
        utm=utm or {},
        spam=bool(honeypot),
    )
    if honeypot:
        return None
    answers = forms.clean_submission(opening.form.schema, data)
    fields = forms.fields_of(opening.form.schema)
    applicant: dict[str, Any] = {}
    referees: list[dict[str, str]] = []
    extra: dict[str, Any] = {}
    uploads: dict[str, list[str]] = {}
    for f in fields:
        if f["key"] not in answers:
            continue
        value, target = answers[f["key"]], f.get("maps_to", "")
        if f.get("type") == "file":
            uploads[f["key"]] = list(value)
        elif target.startswith("applicant."):
            applicant[target.split(".", 1)[1]] = value
        elif target == "referees":
            referees = [
                {
                    "name": str(r.get("name", ""))[:150],
                    "email": str(r["email"]).strip(),
                    "relationship": str(r.get("relationship", ""))[:150],
                }
                for r in value
            ]
        else:
            extra[f.get("label", f["key"])] = value
    if not applicant.get("email") or not applicant.get("first_name"):
        raise BusinessRuleViolation(_("Name and email are required."))
    first = next(s for s in stages() if s.kind == ApplicationStage.Kind.OPEN)
    application = TutorApplication.objects.create(
        opening=opening,
        submission=submission,
        first_name=str(applicant["first_name"])[:100],
        last_name=str(applicant.get("last_name", ""))[:100],
        email=str(applicant["email"]).strip().lower(),
        phone=str(applicant.get("phone", ""))[:32],
        postcode=str(applicant.get("postcode", ""))[:20],
        subjects=forms._subjects(applicant.get("subjects")),
        qualifications=str(applicant.get("qualifications", "")),
        experience=str(applicant.get("experience", "")),
        right_to_work=str(applicant.get("right_to_work", ""))[:200],
        video_url=str(applicant.get("video_url", ""))[:200],
        answers=extra,
        stage=first,
        stage_entered_at=now(),
    )
    if uploads:
        _attach_uploads(application, opening, submission, uploads)
    for referee in referees:
        request_reference(application, **referee)
    publish(events.ApplicationSubmitted(subject_id=application.pk, opening_id=str(opening.pk)))
    return application


def _attach_uploads(
    application: TutorApplication,
    opening: JobOpening,
    submission: Any,
    uploads: dict[str, list[str]],
) -> None:
    """G5a: the CV, video introduction and other files uploaded on the public form."""
    from tutortrack.leads import forms
    from tutortrack.leads.models import FormSubmission

    schema = opening.form.schema
    stored = forms.claim_files(
        schema, uploads, owner=application, context=f"opening:{opening.slug}"
    )
    targets = {f["key"]: f.get("maps_to", "") for f in forms.fields_of(schema)}
    others = []
    for key, files in stored.items():
        target = targets.get(key, "")
        if target == "applicant.cv":
            application.cv = files[0]
        elif target == "applicant.video":
            application.video = files[0]
        else:
            others += files
    application.save(update_fields=["cv", "video", "updated_at"])
    if others:
        application.attachments.add(*others)
    FormSubmission.objects.filter(pk=submission.pk).update(
        data={**submission.data, **forms.file_answers(stored)}
    )


def upload_kinds_for_opening(slug: str) -> set[str] | None:
    """Upload context ``opening``: a published, open job opening whose form has file fields."""
    from tutortrack.core.storage.public import file_kinds
    from tutortrack.leads import forms

    opening = JobOpening.objects.filter(slug=slug, published=True).select_related("form").first()
    if opening is None or (opening.closes_on and opening.closes_on < compliance.today()):
        return None
    return file_kinds(forms.fields_of(opening.form.schema))


@transaction.atomic
def move(
    application: TutorApplication, stage: ApplicationStage, *, user: Any = None
) -> TutorApplication:
    application = TutorApplication.objects.select_for_update().get(pk=application.pk)
    if application.status != TutorApplication.Status.OPEN:
        raise BusinessRuleViolation(_("This application is closed."))
    if stage.kind != ApplicationStage.Kind.OPEN:
        raise BusinessRuleViolation(_("Approve or reject the application instead."))
    with audit.track(application, action="move"):
        application.stage = stage
        application.stage_entered_at = now()
        application.save()
    publish(events.ApplicationStageChanged(subject_id=application.pk, to_stage=stage.name))
    return application


@transaction.atomic
def score(
    application: TutorApplication,
    *,
    reviewer: Any,
    scores: dict[str, int],
    recommendation: str,
    notes: str = "",
) -> Scorecard:
    if any(not 1 <= int(v) <= 5 for v in scores.values()):
        raise BusinessRuleViolation(_("Scores are 1 to 5."))
    return Scorecard.objects.create(
        application=application,
        stage=application.stage,
        reviewer=reviewer,
        scores={k: int(v) for k, v in scores.items()},
        recommendation=recommendation,
        notes=notes,
    )


@transaction.atomic
def reject(
    application: TutorApplication, *, reason: str, talent_pool: bool = False, notify: bool = True
) -> TutorApplication:
    application = TutorApplication.objects.select_for_update().get(pk=application.pk)
    if application.status != TutorApplication.Status.OPEN:
        raise BusinessRuleViolation(_("This application is closed."))
    with audit.track(application, action="reject"):
        application.status = (
            TutorApplication.Status.TALENT_POOL if talent_pool else TutorApplication.Status.REJECTED
        )
        application.stage = _stage(ApplicationStage.Kind.REJECTED)
        application.stage_entered_at = now()
        application.decision_reason = reason[:500]
        application.decided_at = now()
        application.save()
    publish(events.ApplicationRejected(subject_id=application.pk, reason=reason[:500]))
    if notify:
        from tutortrack.comms import services as comms

        comms.notify("application_rejected", application, key=f"rejected:{application.pk}")
    return application


def bulk_reject(applications: list[TutorApplication], *, reason: str) -> int:
    count = 0
    for application in applications:
        if application.status == TutorApplication.Status.OPEN:
            reject(application, reason=reason)
            count += 1
    return count


# --- interviews (T03) -----------------------------------------------------------------------


@transaction.atomic
def propose_interview(
    application: TutorApplication,
    *,
    interviewer: Any,
    options: list[datetime] | None = None,
    minutes: int = 30,
    meeting_url: str = "",
    mode: str = Interview.Mode.TIMES,
    window_start: Any = None,
    window_end: Any = None,
) -> tuple[Interview, str]:
    """Offer times, or (G5a) a booking link over the interviewer's free time in a date
    window; the applicant picks one from the emailed link."""
    from . import interviews

    if application.status != TutorApplication.Status.OPEN:
        raise BusinessRuleViolation(_("This application is closed."))
    future: list[datetime] = []
    if mode == Interview.Mode.AVAILABILITY:
        if window_start is None or window_end is None:
            raise BusinessRuleViolation(
                _("Choose the dates to offer."),
                extra={"errors": {"window_start": [_("Required.")]}},
            )
        interviews.check_window(window_start, window_end)
        if not interviews.interviewer_slots(
            interviewer, start=window_start, end=window_end, minutes=minutes
        ):
            raise BusinessRuleViolation(
                _("The interviewer has no free time on those dates."),
                extra={"code": "no_free_slots"},
            )
    else:
        future = sorted(o for o in (options or []) if o > now())
        if not future:
            raise BusinessRuleViolation(_("Offer at least one time in the future."))
    token = secrets.token_urlsafe(24)
    interview = Interview.objects.create(
        application=application,
        interviewer=interviewer,
        options=[o.isoformat() for o in future],
        minutes=minutes,
        meeting_url=meeting_url,
        token_hash=_hash(token),
        mode=mode,
        window_start=window_start if mode == Interview.Mode.AVAILABILITY else None,
        window_end=window_end if mode == Interview.Mode.AVAILABILITY else None,
    )
    audit.record(interview, "create", {"mode": [None, mode]})
    from tutortrack.comms import services as comms

    transaction.on_commit(
        lambda: comms.notify(
            "interview_invite", (interview.pk, token), key=f"interview:{interview.pk}"
        )
    )
    return interview, token


def interview_for_token(token: str) -> Interview:
    interview = (
        Interview.objects.select_related("application").filter(token_hash=_hash(token)).first()
    )
    if interview is None:
        raise NotFound()
    return interview


@transaction.atomic
def book_interview(token: str, start: str) -> Interview:
    from . import interviews

    found = interview_for_token(token)
    interviews.lock_interviewer(found.interviewer_id)
    interview = Interview.objects.select_for_update().get(pk=found.pk)
    if interview.status != Interview.Status.PROPOSED:
        raise BusinessRuleViolation(_("This interview is already booked."))
    try:
        moment = datetime.fromisoformat(start)
    except ValueError:
        raise BusinessRuleViolation(_("Choose one of the offered times.")) from None
    if interview.mode == Interview.Mode.AVAILABILITY:
        if (
            moment.tzinfo is None
            or not interview.window_start
            or not interview.window_end
            or not interviews.is_free(interview, moment)
        ):
            raise BusinessRuleViolation(
                _("That time has just been taken. Please choose another."),
                extra={"code": "slot_taken"},
            )
    elif start not in interview.options:
        raise BusinessRuleViolation(_("Choose one of the offered times."))
    interview.start = moment
    interview.status = Interview.Status.BOOKED
    interview.save(update_fields=["start", "status", "updated_at"])
    publish(
        events.InterviewBooked(subject_id=interview.application_id, interview_id=str(interview.pk))
    )
    return interview


# --- references (T04) -----------------------------------------------------------------------


@transaction.atomic
def request_reference(
    application: TutorApplication, *, name: str, email: str, relationship: str = ""
) -> tuple[ReferenceRequest, str]:
    token = secrets.token_urlsafe(24)
    reference = ReferenceRequest.objects.create(
        application=application,
        referee_name=name or email,
        referee_email=email.lower(),
        relationship=relationship,
        token_hash=_hash(token),
    )
    publish(events.ReferenceRequested(subject_id=reference.pk, application_id=str(application.pk)))
    from tutortrack.comms import services as comms

    transaction.on_commit(
        lambda: comms.notify(
            "reference_request", (reference.pk, token), key=f"reference:{reference.pk}"
        )
    )
    return reference, token


def reference_for_token(token: str) -> ReferenceRequest:
    reference = (
        ReferenceRequest.objects.select_related("application")
        .filter(token_hash=_hash(token))
        .first()
    )
    if reference is None:
        raise NotFound()
    return reference


@transaction.atomic
def submit_reference(
    token: str, *, responses: dict[str, Any], rating: int, concerns: bool
) -> ReferenceRequest:
    reference = ReferenceRequest.objects.select_for_update().get(pk=reference_for_token(token).pk)
    if reference.status != ReferenceRequest.Status.REQUESTED:
        raise BusinessRuleViolation(_("This reference has already been given or has expired."))
    if not 1 <= rating <= 5:
        raise BusinessRuleViolation(_("Rate from 1 to 5."))
    reference.responses = {k: str(v)[:5000] for k, v in responses.items()}
    reference.rating = rating
    reference.concerns = concerns
    reference.status = ReferenceRequest.Status.RECEIVED
    reference.received_at = now()
    reference.save()
    publish(
        events.ReferenceReceived(
            subject_id=reference.pk, application_id=str(reference.application_id), concerns=concerns
        )
    )
    return reference


def remind_referee(reference_id: Any, token_hint: str = "") -> bool:
    reference = ReferenceRequest.objects.filter(pk=reference_id).first()
    if reference is None or reference.status != ReferenceRequest.Status.REQUESTED:
        return False
    from tutortrack.comms import services as comms

    comms.notify("reference_reminder", reference, key=f"reminder:{reference.pk}:{now():%Y%m%d}")
    return True


@transaction.atomic
def expire_reference(reference_id: Any) -> bool:
    updated = ReferenceRequest.objects.filter(
        pk=reference_id, status=ReferenceRequest.Status.REQUESTED
    ).update(status=ReferenceRequest.Status.EXPIRED, updated_at=now())
    return bool(updated)


# --- approval and onboarding (T05) ----------------------------------------------------------


@transaction.atomic
def approve(
    application: TutorApplication, *, user: Any = None, employment_type: str = "self_employed"
) -> TutorProfile:
    """AC FR-18-2: a tutor in ``onboarding`` from the application data, an invitation and an
    onboarding checklist."""
    from tutortrack.people import services as people

    application = TutorApplication.objects.select_for_update().get(pk=application.pk)
    if application.status != TutorApplication.Status.OPEN:
        raise BusinessRuleViolation(_("This application is closed."))
    if employment_type not in TutorProfile.Employment.values:
        raise BusinessRuleViolation(_("Choose an employment type."))
    tutor = TutorProfile.objects.filter(email=application.email).first()
    if tutor is None:
        tutor = people.create_tutor(
            email=application.email,
            first_name=application.first_name,
            last_name=application.last_name,
            phone=application.phone,
            employment_type=employment_type,
            invite=True,
        )
        if application.subjects:
            people.set_tutor_subjects(
                tutor,
                [
                    {"subject": s["subject"], "level": s.get("level", "")}
                    for s in application.subjects
                ],
            )
    with audit.track(application, action="approve"):
        application.status = TutorApplication.Status.HIRED
        application.stage = _stage(ApplicationStage.Kind.HIRED)
        application.stage_entered_at = now()
        application.decided_at = now()
        application.tutor = tutor
        application.save()
    start_onboarding(tutor)
    publish(events.ApplicationApproved(subject_id=application.pk, tutor_id=str(tutor.pk)))
    return tutor


def default_template() -> ChecklistTemplate:
    template = ChecklistTemplate.objects.filter(is_default=True).first()
    if template is None:
        template = ChecklistTemplate.objects.create(
            name=_("Tutor onboarding"), items=catalogue.CHECKLIST, is_default=True
        )
    return template


@transaction.atomic
def start_onboarding(tutor: TutorProfile) -> ChecklistInstance:
    existing = ChecklistInstance.objects.filter(tutor=tutor).first()
    if existing is not None:
        return existing
    template = (
        ChecklistTemplate.objects.filter(employment_type=tutor.employment_type).first()
        or default_template()
    )
    instance = ChecklistInstance.objects.create(
        tutor=tutor, template=template, items=template.items
    )
    publish(events.OnboardingStarted(subject_id=tutor.pk))
    return instance


def _auto_done(instance: ChecklistInstance, item: dict[str, Any]) -> bool:
    from tutortrack.payroll.models import TutorPayProfile
    from tutortrack.scheduling.models import AvailabilityTemplate

    tutor = instance.tutor
    kind = item.get("kind")
    if kind == "self_billing":
        return TutorPayProfile.objects.filter(
            tutor=tutor, self_billing_agreed_at__isnull=False
        ).exists()
    if kind == "payout":
        profile = TutorPayProfile.objects.filter(tutor=tutor).first()
        return bool(profile and (profile.bank_details or profile.stripe_payouts_enabled))
    if kind == "availability":
        return AvailabilityTemplate.objects.filter(tutor=tutor).exists()
    if kind == "profile":
        return bool(tutor.bio_public.strip())
    if kind == "document":
        return not compliance.problems(tutor)
    return False


def needs_signature(item: dict[str, Any]) -> bool:
    """Agreements the tutor signs (click-to-sign) rather than ticks: ``"sign": true`` on the
    item; templates from before gap batch G2 sign their main ``agreement`` item."""
    return item.get("kind") == "agreement" and bool(
        item.get("sign", item.get("key") == "agreement")
    )


def checklist_state(instance: ChecklistInstance) -> list[dict[str, Any]]:
    out = []
    for item in instance.items:
        done = instance.done.get(item["key"])
        auto = item.get("kind") not in ("agreement", "training", "custom")
        complete = bool(done) or (auto and _auto_done(instance, item))
        out.append(
            {
                **item,
                "done": complete,
                "done_at": (done or {}).get("at"),
                "needs_signature": needs_signature(item),
                "signature_id": (done or {}).get("signature"),
            }
        )
    return out


@transaction.atomic
def sign_agreement(tutor: TutorProfile, key: str, *, user: Any, full_name: str) -> Any:
    """The tutor signs an onboarding agreement in the tutor portal (FR-18-5): click-to-sign
    with an audit trail and a signed PDF copy (``crm.signing``) instead of "I agree"."""
    from tutortrack.crm import signing

    instance = ChecklistInstance.objects.select_for_update().get(tutor=tutor)
    item = next((i for i in instance.items if i["key"] == key), None)
    if item is None:
        raise NotFound()
    if not needs_signature(item):
        raise BusinessRuleViolation(_("This step isn't signed."))
    if key in instance.done:
        raise BusinessRuleViolation(_("You have already signed this."))
    text = str(item.get("text") or "\n\n".join(x for x in (item["label"], item.get("link")) if x))
    signature = signing.sign_agreement(
        tutor=tutor,
        key=key,
        title=str(item["label"]),
        text=text,
        signer=user,
        full_name=full_name,
    )
    complete_item(tutor, key, user=user, signature=str(signature.pk))
    return signature


@transaction.atomic
def complete_item(
    tutor: TutorProfile, key: str, *, user: Any = None, signature: str = ""
) -> ChecklistInstance:
    """The tutor ticks an agreement or training item (or staff do it for them)."""
    instance = ChecklistInstance.objects.select_for_update().get(tutor=tutor)
    item = next((i for i in instance.items if i["key"] == key), None)
    if item is None:
        raise NotFound()
    if key not in instance.done:
        entry = {"at": now().isoformat(), "by": str(getattr(user, "pk", ""))}
        if signature:
            entry["signature"] = signature
        instance.done = {**instance.done, key: entry}
        instance.save(update_fields=["done", "updated_at"])
        audit.record(instance, "item_done", {"item": [None, key]})
        publish(events.OnboardingItemDone(subject_id=tutor.pk, item=key))
    return instance


@transaction.atomic
def check_onboarding(tutor_id: Any) -> str:
    """Activate the tutor once every mandatory item is done (setting). Returns ``complete``,
    ``waiting`` or ``done`` (already finished)."""
    from tutortrack.people.services import change_tutor_status

    instance = (
        ChecklistInstance.objects.select_for_update()
        .select_related("tutor")
        .filter(tutor_id=tutor_id)
        .first()
    )
    if instance is None or instance.completed_at is not None:
        return "done"
    state = checklist_state(instance)
    if not all(i["done"] for i in state if i.get("mandatory")):
        return "waiting"
    instance.completed_at = now()
    instance.save(update_fields=["completed_at", "updated_at"])
    tutor = instance.tutor
    if get_setting("recruitment.auto_activate") and tutor.status == TutorProfile.Status.ONBOARDING:
        change_tutor_status(tutor, TutorProfile.Status.ACTIVE)
    publish(events.OnboardingCompleted(subject_id=tutor.pk))
    return "complete"


def remind_onboarding(tutor_id: Any) -> bool:
    instance = ChecklistInstance.objects.select_related("tutor").filter(tutor_id=tutor_id).first()
    if instance is None or instance.completed_at is not None:
        return False
    from tutortrack.comms import services as comms

    comms.notify("onboarding_reminder", instance.tutor, key=f"onboarding:{tutor_id}:{now():%Y%m%d}")
    return True


# --- subject competency (T09) ---------------------------------------------------------------


@transaction.atomic
def assess_subject(subject: Any, *, status: str, evidence: str, user: Any) -> Any:
    """``claimed → assessed → approved`` (or rejected) with evidence (FR-18-3)."""
    from tutortrack.people.models import TutorSubject

    if status not in TutorSubject.Competency.values:
        raise BusinessRuleViolation(_("Unknown status."))
    with audit.track(subject, action="assess"):
        subject.competency = status
        subject.evidence = evidence[:1000]
        subject.approved = status == TutorSubject.Competency.APPROVED
        subject.approved_by = user if subject.approved else None
        subject.save()
    return subject


def stuck_reminder(application_id: Any) -> bool:
    """The owner (or recruiters) hear about an application sitting in a stage too long."""
    application = TutorApplication.objects.select_related("stage").filter(pk=application_id).first()
    if application is None or application.status != TutorApplication.Status.OPEN:
        return False
    from tutortrack.comms import services as comms

    title = _("Application waiting: %(name)s") % {"name": application.full_name}
    body = _("In %(stage)s since %(date)s.") % {
        "stage": application.stage.name,
        "date": application.stage_entered_at.date(),
    }
    comms.notify(
        "staff_application_waiting",
        (title, body, f"/recruitment/{application.pk}"),
        key=f"stuck:{application.pk}:{now():%Y%m%d}",
    )
    return True


def stage_reminder_days(application_id: Any) -> int:
    application = TutorApplication.objects.select_related("stage").filter(pk=application_id).first()
    if application is None or application.status != TutorApplication.Status.OPEN:
        return 0
    return int(application.stage.reminder_days or 5)


def reference_days() -> int:
    return int(get_setting("recruitment.reference_days"))
