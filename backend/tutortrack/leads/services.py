"""Leads (E17): capture enquiries (forms, API, email, phone), work them through a pipeline,
book trial lessons, convert them into clients and jobs, and run the waitlist.

Every new enquiry creates (or links to) a prospect client with its contact and ``lead``
students in one transaction, then publishes ``enquiry.received``; the follow-up workflow
sends the acknowledgement, notifies the owner and watches the stage SLA.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from django.db import transaction
from django.db.models import Count, Q
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.people.models import Client, Contact, Student
from tutortrack.tenancy.settings_service import get_setting

from . import events, forms
from .models import (
    AssignmentRule,
    Enquiry,
    EnquiryStageHistory,
    Form,
    FormSubmission,
    Pipeline,
    PipelineStage,
    WaitlistEntry,
)

logger = structlog.get_logger(__name__)

DEFAULT_STAGES = (
    ("New", "open", 10, 24),
    ("Contacted", "open", 30, 72),
    ("Trial booked", "open", 60, None),
    ("Trial done", "open", 80, 48),
    ("Won", "won", 100, None),
    ("Lost", "lost", 0, None),
)


# --- pipelines (T02) ------------------------------------------------------------------------


def default_pipeline() -> Pipeline:
    pipeline = Pipeline.objects.filter(is_default=True, active=True).first()
    if pipeline is not None:
        return pipeline
    with transaction.atomic():
        pipeline = Pipeline.objects.create(name=_("Enquiries"), is_default=True)
        for order, (name, kind, probability, sla) in enumerate(DEFAULT_STAGES):
            PipelineStage.objects.create(
                pipeline=pipeline,
                name=name,
                kind=kind,
                order=order,
                probability=probability,
                sla_hours=sla,
            )
    return pipeline


def _stage(pipeline: Pipeline, kind: str) -> PipelineStage:
    stage = pipeline.stages.filter(kind=kind).order_by("order").first()
    if stage is None:
        raise BusinessRuleViolation(_("The pipeline has no %(kind)s stage.") % {"kind": kind})
    return stage


@transaction.atomic
def save_pipeline(
    *,
    name: str,
    stages: list[dict[str, Any]],
    pipeline: Pipeline | None = None,
    is_default: bool = False,
) -> Pipeline:
    """Create or update a pipeline and its stages (exactly one Won and one Lost stage)."""
    kinds = [s.get("kind", "open") for s in stages]
    if kinds.count("won") != 1 or kinds.count("lost") != 1 or "open" not in kinds:
        raise BusinessRuleViolation(_("A pipeline needs open stages, one Won and one Lost."))
    if pipeline is None:
        pipeline = Pipeline.objects.create(name=name[:100], is_default=is_default)
    else:
        pipeline.name = name[:100]
        pipeline.save(update_fields=["name", "updated_at"])
    if is_default:
        Pipeline.objects.exclude(pk=pipeline.pk).update(is_default=False)
        Pipeline.objects.filter(pk=pipeline.pk).update(is_default=True)
    keep = []
    for order, data in enumerate(stages):
        values = {
            "name": str(data["name"])[:60],
            "kind": data.get("kind", "open"),
            "order": order,
            "probability": int(data.get("probability") or 0),
            "sla_hours": data.get("sla_hours"),
            "colour": str(data.get("colour", ""))[:7],
        }
        stage = pipeline.stages.filter(pk=str(data["id"])).first() if data.get("id") else None
        if stage is None:
            stage = PipelineStage.objects.create(pipeline=pipeline, **values)
        else:
            for key, value in values.items():
                setattr(stage, key, value)
            stage.save()
        keep.append(stage.pk)
    removed = pipeline.stages.exclude(pk__in=keep)
    if Enquiry.objects.filter(stage__in=removed).exists():
        raise BusinessRuleViolation(_("Move enquiries out of a stage before removing it."))
    removed.delete()
    audit.record(pipeline, "save", {"stages": [None, len(keep)]})
    return pipeline


# --- assignment (T02) -----------------------------------------------------------------------


def _assign(pipeline: Pipeline, branch_id: Any, subjects: list[str]) -> Any:
    from tutortrack.identity.models import User

    rules = (
        AssignmentRule.objects.select_for_update()
        .filter(active=True)
        .filter(Q(pipeline__isnull=True) | Q(pipeline=pipeline))
        .filter(Q(branch__isnull=True) | Q(branch_id=branch_id))
    )
    wanted = {s.lower() for s in subjects}
    for rule in rules:
        if rule.subject and rule.subject.lower() not in wanted:
            continue
        if not rule.owners:
            continue
        owner_id = rule.owners[rule.next_index % len(rule.owners)]
        rule.next_index = (rule.next_index + 1) % len(rule.owners)
        rule.save(update_fields=["next_index", "updated_at"])
        return User.objects.filter(pk=owner_id, is_active=True).first()
    return None


# --- capture (T01, T03) ---------------------------------------------------------------------


def find_existing_contact(email: str, phone: str) -> Contact | None:
    """Duplicate detection: an existing contact with the same email (or phone)."""
    from tutortrack.comms.channels import normalise_phone

    if email:
        found = Contact.objects.filter(email__iexact=email.strip()).select_related("client").first()
        if found is not None:
            return found
    if phone:
        wanted = normalise_phone(phone)
        for contact in Contact.objects.exclude(phone="").select_related("client")[:5000]:
            if normalise_phone(contact.phone) == wanted:
                return contact
    return None


def _students_for(client: Client, wanted: list[dict[str, Any]]) -> list[Student]:
    from tutortrack.people.services import create_student

    out = []
    existing = list(client.students.all())
    for data in wanted:
        first = str(data.get("first_name", "")).strip()
        if not first:
            continue
        match = next((s for s in existing if s.first_name.lower() == first.lower()), None)
        if match is None:
            match = create_student(
                client,
                status=Student.Status.LEAD,
                first_name=first[:100],
                last_name=str(data.get("last_name") or client.display_name.split(" ")[-1])[:100],
                subjects=data.get("subjects") or [],
            )
        out.append(match)
    return out


@transaction.atomic
def create_enquiry(
    *,
    contact: dict[str, Any],
    students: list[dict[str, Any]] | None = None,
    source: str = Enquiry.Source.MANUAL,
    source_detail: str = "",
    pipeline: Pipeline | None = None,
    owner: Any = None,
    subjects: list[dict[str, str]] | None = None,
    notes: str = "",
    utm: dict[str, Any] | None = None,
    submission: FormSubmission | None = None,
    branch: Any = None,
    value_estimate: Money | None = None,
    expected_start: Any = None,
    client: dict[str, Any] | None = None,
    priority: str = Enquiry.Priority.NORMAL,
) -> Enquiry:
    """FR-17-1 AC: one transaction creates (or links) the prospect client, contact and lead
    students and the enquiry at the first stage; notifications follow asynchronously."""
    from tutortrack.people.services import quick_add_family

    email = str(contact.get("email", "")).strip().lower()
    phone = str(contact.get("phone", "")).strip()
    if not email and not phone:
        raise BusinessRuleViolation(
            _("Give an email address or phone number."),
            extra={"errors": {"email": [_("Email or phone required.")]}},
        )
    if not str(contact.get("first_name", "")).strip():
        raise BusinessRuleViolation(
            _("Give the contact's first name."), extra={"errors": {"first_name": [_("Required.")]}}
        )
    students = students or []
    existing = find_existing_contact(email, phone)
    if existing is not None:
        family = existing.client
        person = existing
        linked = _students_for(family, students)
    else:
        client_data = {"status": Client.Status.PROSPECT, **(client or {})}
        if client_data.get("postcode"):
            client_data["billing_address"] = {"postcode": client_data.pop("postcode")}
        if branch is not None:
            client_data["branch"] = branch
        contact_data = {
            k: str(contact.get(k, "")).strip()[:100]
            for k in ("first_name", "last_name", "phone")
            if contact.get(k)
        }
        contact_data["email"] = email
        family, person, linked = quick_add_family(
            contact=contact_data,
            students=[
                {
                    "status": Student.Status.LEAD,
                    **{k: v for k, v in s.items() if k in ("first_name", "last_name", "subjects")},
                }
                for s in students
                if str(s.get("first_name", "")).strip()
            ],
            client=client_data,
        )
    pipeline = pipeline or default_pipeline()
    first = pipeline.stages.filter(kind=PipelineStage.Kind.OPEN).order_by("order").first()
    if first is None:
        raise BusinessRuleViolation(_("The pipeline has no open stages."))
    subjects = subjects or [s for st in students for s in (st.get("subjects") or [])]
    names = ", ".join(sorted({s["subject"] for s in subjects if s.get("subject")}))
    person_name = f"{person.first_name} {person.last_name}".strip()
    enquiry = Enquiry(
        title=(f"{person_name} - {names}" if names else person_name)[:200],
        client=family,
        contact=person,
        pipeline=pipeline,
        stage=first,
        stage_entered_at=now(),
        subjects=subjects,
        notes=notes,
        source=source,
        source_detail=source_detail[:200],
        utm=utm or {},
        submission=submission,
        expected_start=expected_start,
        priority=priority,
        branch_id=family.branch_id,
    )
    if value_estimate is not None:
        enquiry.currency = value_estimate.currency
        enquiry.value_estimate = value_estimate
    enquiry.owner = owner or _assign(pipeline, family.branch_id, [s["subject"] for s in subjects])
    enquiry.save()
    enquiry.students.set(linked)
    EnquiryStageHistory.objects.create(enquiry=enquiry, to_stage=first)
    audit.record_create(enquiry)
    publish(
        events.EnquiryReceived(
            subject_id=enquiry.pk,
            client_id=str(family.pk),
            source=source,
            owner_id=str(enquiry.owner_id) if enquiry.owner_id else None,
        ),
        branch_id=enquiry.branch_id,
    )
    if enquiry.owner_id:
        publish(
            events.EnquiryAssigned(
                subject_id=enquiry.pk, client_id=str(family.pk), owner_id=str(enquiry.owner_id)
            ),
            branch_id=enquiry.branch_id,
        )
    return enquiry


def _summary(extra: dict[str, Any]) -> str:
    return "\n".join(f"{k}: {v}" for k, v in extra.items() if v not in (None, "", []))


@transaction.atomic
def submit_form(
    form: Form,
    data: dict[str, Any],
    *,
    ip: str | None = None,
    user_agent: str = "",
    utm: dict[str, Any] | None = None,
    honeypot: str = "",
) -> dict[str, Any]:
    """A public submission (FR-17-1, FR-17-7). Spam (the hidden field filled in) is stored
    and silently accepted."""
    if not form.published:
        raise NotFound()
    clean_utm = {
        k: str(v)[:300]
        for k, v in (utm or {}).items()
        if k
        in (
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "referrer",
            "landing_page",
            "gclid",
            "fbclid",
        )
    }
    submission = FormSubmission.objects.create(
        form=form,
        data=data,
        ip=ip,
        user_agent=user_agent[:300],
        utm=clean_utm,
        spam=bool(honeypot),
    )
    if honeypot:
        return {"submission": submission, "enquiry": None, "pay_url": ""}
    answers = forms.clean_submission(form.schema, data)
    mapped = forms.map_answers(form.schema, answers)
    publish(
        events.FormSubmitted(subject_id=submission.pk, form_id=str(form.pk), form_type=form.type)
    )
    if form.type == Form.Type.REGISTRATION and form.settings.get("create_active", True):
        return _register(form, submission, mapped)
    notes = "\n\n".join(
        p for p in (str(mapped.enquiry.get("notes", "")), _summary(mapped.extra)) if p
    )
    pipeline = None
    if form.settings.get("pipeline"):
        pipeline = Pipeline.objects.filter(pk=form.settings["pipeline"]).first()
    enquiry = create_enquiry(
        contact=mapped.contact,
        students=mapped.students,
        source=Enquiry.Source.FORM,
        source_detail=form.name,
        pipeline=pipeline,
        notes=notes,
        utm=clean_utm,
        submission=submission,
        branch=form.branch,
        client=mapped.client,
        subjects=forms._subjects(mapped.enquiry.get("subjects")) or None,
    )
    FormSubmission.objects.filter(pk=submission.pk).update(
        created_records={"enquiry": str(enquiry.pk), "client": str(enquiry.client_id)}
    )
    return {"submission": submission, "enquiry": enquiry, "pay_url": ""}


def _register(form: Form, submission: FormSubmission, mapped: forms.Mapped) -> dict[str, Any]:
    """Registration: an active client and students straight away, plus the registration fee
    as a payment request (FR-17-7)."""
    from tutortrack.people.services import quick_add_family

    contact = {
        k: v
        for k, v in mapped.contact.items()
        if k in ("first_name", "last_name", "email", "phone")
    }
    if not contact.get("email") and not contact.get("phone"):
        raise BusinessRuleViolation(_("Give an email address or phone number."))
    client_data: dict[str, Any] = {"status": Client.Status.ACTIVE}
    if mapped.client.get("postcode"):
        client_data["billing_address"] = {"postcode": mapped.client["postcode"]}
    if form.branch_id:
        client_data["branch_id"] = form.branch_id
    family, person, students = quick_add_family(
        contact=contact,
        students=[
            {
                "status": Student.Status.ACTIVE,
                **{k: v for k, v in s.items() if k in ("first_name", "last_name", "subjects")},
            }
            for s in mapped.students
        ],
        client=client_data,
    )
    pay_url = ""
    fee = form.settings.get("fee")
    if fee and Decimal(str(fee.get("amount", "0"))) > 0:
        from tutortrack.billing.services import create_payment_request

        request = create_payment_request(
            client=family,
            amount=Money(Decimal(str(fee["amount"])), fee.get("currency") or family.currency),
            description=_("Registration fee"),
        )
        pay_url = (
            f"{family.organisation.base_url}/pay/{request.pay_token}" if request.pay_token else ""
        )
    FormSubmission.objects.filter(pk=submission.pk).update(
        created_records={
            "client": str(family.pk),
            "contact": str(person.pk),
            "students": [str(s.pk) for s in students],
        }
    )
    return {"submission": submission, "enquiry": None, "pay_url": pay_url, "client": family}


@transaction.atomic
def enquiry_from_email(*, from_email: str, from_name: str, subject: str, body: str) -> Enquiry:
    first, _sep, last = (from_name or from_email.split("@")[0]).partition(" ")
    return create_enquiry(
        contact={"first_name": first or from_email, "last_name": last, "email": from_email},
        source=Enquiry.Source.EMAIL,
        source_detail=subject[:200],
        notes=f"{subject}\n\n{body}".strip()[:5000],
    )


# --- working enquiries (T02, T04) -----------------------------------------------------------


def _signal(enquiry: Enquiry, name: str) -> None:
    from tutortrack.core.models import WorkflowLink
    from tutortrack.core.workflows import signal_now

    from .processes import enquiry_workflow_id

    wid = enquiry_workflow_id(enquiry.organisation_id, enquiry.pk)

    def send() -> None:
        if WorkflowLink.objects.filter(workflow_id=wid, status="running").exists():
            signal_now(wid, name)

    transaction.on_commit(send)


def _enter(enquiry: Enquiry, stage: PipelineStage, user: Any) -> None:
    previous = enquiry.stage
    seconds = max(0, int((now() - enquiry.stage_entered_at).total_seconds()))
    EnquiryStageHistory.objects.create(
        enquiry=enquiry,
        from_stage=previous,
        to_stage=stage,
        changed_by=user,
        seconds_in_previous=seconds,
    )
    enquiry.stage = stage
    enquiry.stage_entered_at = now()
    enquiry.sla_breached_at = None
    if enquiry.first_response_at is None:
        enquiry.first_response_at = now()
    publish(
        events.EnquiryStageChanged(
            subject_id=enquiry.pk,
            client_id=str(enquiry.client_id),
            from_stage=str(previous.pk),
            to_stage=str(stage.pk),
        ),
        branch_id=enquiry.branch_id,
    )


@transaction.atomic
def move(enquiry: Enquiry, stage: PipelineStage, *, user: Any = None) -> Enquiry:
    enquiry = Enquiry.objects.select_for_update().select_related("stage").get(pk=enquiry.pk)
    if enquiry.status != Enquiry.Status.OPEN:
        raise BusinessRuleViolation(_("This enquiry is closed."))
    if stage.pipeline_id != enquiry.pipeline_id:
        raise BusinessRuleViolation(_("That stage is in another pipeline."))
    if stage.kind == PipelineStage.Kind.WON:
        raise BusinessRuleViolation(
            _("Convert the enquiry to mark it won."), extra={"code": "convert_required"}
        )
    if stage.kind == PipelineStage.Kind.LOST:
        raise BusinessRuleViolation(
            _("Give a reason to mark it lost."), extra={"code": "reason_required"}
        )
    if stage.pk == enquiry.stage_id:
        return enquiry
    with audit.track(enquiry, action="move"):
        _enter(enquiry, stage, user)
        enquiry.save()
    _signal(enquiry, "stage_changed")
    return enquiry


EDITABLE = {"owner", "priority", "subjects", "notes", "value_estimate", "expected_start", "title"}


@transaction.atomic
def update_enquiry(enquiry: Enquiry, **changes: Any) -> Enquiry:
    unknown = set(changes) - EDITABLE
    if unknown:
        raise BusinessRuleViolation(f"Unknown enquiry fields: {', '.join(sorted(unknown))}")
    old_owner = enquiry.owner_id
    with audit.track(enquiry, action="update"):
        for key, value in changes.items():
            if key == "value_estimate" and value is not None:
                enquiry.currency = value.currency
            setattr(enquiry, key, value)
        enquiry.save()
    if "owner" in changes and enquiry.owner_id != old_owner:
        publish(
            events.EnquiryAssigned(
                subject_id=enquiry.pk,
                client_id=str(enquiry.client_id),
                owner_id=str(enquiry.owner_id) if enquiry.owner_id else None,
            ),
            branch_id=enquiry.branch_id,
        )
    return enquiry


@transaction.atomic
def lose(
    enquiry: Enquiry, *, reason: str, note: str = "", nurture: bool = False, user: Any = None
) -> Enquiry:
    reasons = list(get_setting("leads.lost_reasons") or [])
    if reason not in reasons:
        raise BusinessRuleViolation(_("Choose a reason."), extra={"errors": {"reason": reasons}})
    enquiry = Enquiry.objects.select_for_update().select_related("stage").get(pk=enquiry.pk)
    if enquiry.status != Enquiry.Status.OPEN:
        raise BusinessRuleViolation(_("This enquiry is closed."))
    with audit.track(enquiry, action="lose"):
        _enter(enquiry, _stage(enquiry.pipeline, PipelineStage.Kind.LOST), user)
        enquiry.status = Enquiry.Status.LOST
        enquiry.lost_reason = reason
        enquiry.lost_note = note[:500]
        enquiry.lost_at = now()
        enquiry.save()
    if nurture:
        from tutortrack.crm.models import Tag
        from tutortrack.crm.services import apply_tag

        tag, _created = Tag.objects.get_or_create(name="nurture")
        apply_tag(tag, "people.client", [str(enquiry.client_id)])
    publish(
        events.EnquiryLost(subject_id=enquiry.pk, client_id=str(enquiry.client_id), reason=reason),
        branch_id=enquiry.branch_id,
    )
    _signal(enquiry, "closed")
    return enquiry


# --- trial lessons (T05) --------------------------------------------------------------------


@transaction.atomic
def book_trial(
    enquiry: Enquiry,
    *,
    start: datetime,
    end: datetime,
    service: Any,
    tutor: Any = None,
    price: Money | None = None,
    user: Any = None,
) -> Enquiry:
    """A trial lesson for the enquiry's students (free when ``price`` is zero)."""
    from tutortrack.scheduling import services as scheduling

    enquiry = Enquiry.objects.select_for_update().get(pk=enquiry.pk)
    students = list(enquiry.students.all())
    if not students:
        raise BusinessRuleViolation(_("Add a student to the enquiry first."))
    attendees = [
        {"student": s, **({"charge_rate_override": price} if price is not None else {})}
        for s in students
    ]
    result = scheduling.create_lesson(
        start=start,
        end=end,
        service=service,
        attendees=attendees,
        tutors=[{"tutor": tutor}] if tutor is not None else [],
        title=_("Trial: %(names)s") % {"names": ", ".join(s.first_name for s in students)},
        branch=enquiry.branch,
        override_conflicts=True,
    )
    Student.objects.filter(pk__in=[s.pk for s in students], status=Student.Status.LEAD).update(
        status=Student.Status.TRIAL
    )
    with audit.track(enquiry, action="book_trial"):
        enquiry.trial_lesson = result.lesson
        booked = enquiry.pipeline.stages.filter(name__iexact="Trial booked").first()
        if booked is not None and enquiry.stage_id != booked.pk:
            _enter(enquiry, booked, user)
        enquiry.save()
    publish(
        events.TrialLessonBooked(subject_id=enquiry.pk, lesson_id=str(result.lesson.pk)),
        branch_id=enquiry.branch_id,
    )
    _signal(enquiry, "stage_changed")
    return enquiry


@transaction.atomic
def record_trial_outcome(
    enquiry: Enquiry, *, outcome: str, feedback: str = "", user: Any = None
) -> Enquiry:
    if outcome not in Enquiry.TrialOutcome.values:
        raise BusinessRuleViolation(_("Choose an outcome."))
    enquiry = Enquiry.objects.select_for_update().select_related("stage").get(pk=enquiry.pk)
    with audit.track(enquiry, action="trial_outcome"):
        enquiry.trial_outcome = outcome
        enquiry.trial_feedback = feedback[:5000]
        done = enquiry.pipeline.stages.filter(name__iexact="Trial done").first()
        if (
            done is not None
            and enquiry.status == Enquiry.Status.OPEN
            and enquiry.stage_id != done.pk
        ):
            _enter(enquiry, done, user)
        enquiry.save()
    publish(
        events.TrialLessonCompleted(subject_id=enquiry.pk, outcome=outcome),
        branch_id=enquiry.branch_id,
    )
    _signal(enquiry, "stage_changed")
    return enquiry


# --- conversion (T06) -----------------------------------------------------------------------


@transaction.atomic
def convert(
    enquiry: Enquiry,
    *,
    jobs: list[dict[str, Any]],
    invite_to_portal: bool = False,
    payment_setup_link: bool = False,
    user: Any = None,
) -> dict[str, Any]:
    """Client and students become active, jobs are created, and the enquiry is won
    (FR-17-5). Optional portal invitation and card setup link."""
    from tutortrack.jobs import services as job_services
    from tutortrack.people import services as people

    enquiry = (
        Enquiry.objects.select_for_update().select_related("stage", "client").get(pk=enquiry.pk)
    )
    if enquiry.status != Enquiry.Status.OPEN:
        raise BusinessRuleViolation(_("This enquiry is closed."))
    client = enquiry.client
    if client.status != Client.Status.ACTIVE:
        people.update_client(client, status=Client.Status.ACTIVE)
    for student in enquiry.students.exclude(status=Student.Status.ACTIVE):
        people.change_student_status(student, Student.Status.ACTIVE)
    created = []
    for spec in jobs:
        tutors = [{"tutor": spec["tutor"]}] if spec.get("tutor") else []
        students = spec.get("students") or list(enquiry.students.all())
        created.append(
            job_services.create_job(
                client=client,
                service=spec["service"],
                students=[{"student": s} for s in students],
                tutors=tutors,
                status="active" if tutors else "seeking_tutor",
            )
        )
    with audit.track(enquiry, action="convert"):
        _enter(enquiry, _stage(enquiry.pipeline, PipelineStage.Kind.WON), user)
        enquiry.status = Enquiry.Status.WON
        enquiry.won_at = now()
        enquiry.converted_job_ids = [str(j.pk) for j in created]
        enquiry.save()
    out: dict[str, Any] = {"enquiry": enquiry, "jobs": created, "setup_url": "", "invited": False}
    if invite_to_portal and enquiry.contact is not None and enquiry.contact.email:
        people.invite_to_portal(enquiry.contact)
        out["invited"] = True
    if payment_setup_link:
        from tutortrack.payments.services import create_setup_link

        try:
            out["setup_url"] = create_setup_link(client, user=user)
        except BusinessRuleViolation as exc:
            logger.info("leads.setup_link_unavailable", reason=str(exc))
    publish(
        events.EnquiryWon(
            subject_id=enquiry.pk, client_id=str(client.pk), job_ids=enquiry.converted_job_ids
        ),
        branch_id=enquiry.branch_id,
    )
    _signal(enquiry, "closed")
    return out


# --- SLA and acknowledgements (TW1) ---------------------------------------------------------


def sla_status(enquiry_id: Any) -> dict[str, Any]:
    enquiry = Enquiry.objects.select_related("stage").filter(pk=enquiry_id).first()
    if enquiry is None or enquiry.status != Enquiry.Status.OPEN:
        return {"open": False}
    hours = enquiry.stage.sla_hours
    deadline = enquiry.stage_entered_at + timedelta(hours=hours) if hours else None
    return {
        "open": True,
        "stage": str(enquiry.stage_id),
        "deadline": deadline.isoformat() if deadline else "",
        "breached": enquiry.sla_breached_at is not None,
    }


@transaction.atomic
def breach_sla(enquiry_id: Any, stage_id: str) -> bool:
    from tutortrack.comms import services as comms

    enquiry = (
        Enquiry.objects.select_for_update().select_related("stage").filter(pk=enquiry_id).first()
    )
    if enquiry is None or enquiry.status != Enquiry.Status.OPEN:
        return False
    if str(enquiry.stage_id) != stage_id or enquiry.sla_breached_at is not None:
        return False
    enquiry.sla_breached_at = now()
    enquiry.save(update_fields=["sla_breached_at", "updated_at"])
    publish(
        events.EnquirySlaBreached(
            subject_id=enquiry.pk, client_id=str(enquiry.client_id), stage=enquiry.stage.name
        ),
        branch_id=enquiry.branch_id,
    )
    title = _("Enquiry waiting too long: %(title)s") % {"title": enquiry.title}
    body = _("It has been in %(stage)s longer than %(hours)s hours.") % {
        "stage": enquiry.stage.name,
        "hours": enquiry.stage.sla_hours,
    }
    comms.notify(
        "staff_enquiry_sla",
        (title, body, f"/leads/{enquiry.pk}"),
        key=f"sla:{enquiry.pk}:{stage_id}",
    )
    return True


def acknowledge(enquiry_id: Any) -> bool:
    """The automatic reply to the family and the owner's notification."""
    from tutortrack.comms import services as comms

    enquiry = Enquiry.objects.select_related("contact", "owner").filter(pk=enquiry_id).first()
    if enquiry is None:
        return False
    if get_setting("leads.acknowledge") and enquiry.contact is not None:
        comms.notify("enquiry_acknowledgement", enquiry, key=f"ack:{enquiry.pk}")
    if enquiry.owner_id:
        comms.notify("enquiry_assigned", enquiry, key=f"assigned:{enquiry.pk}:{enquiry.owner_id}")
    return True


def trial_follow_up(enquiry_id: Any) -> bool:
    from tutortrack.comms import services as comms

    enquiry = Enquiry.objects.filter(pk=enquiry_id).first()
    if enquiry is None or enquiry.status != Enquiry.Status.OPEN or enquiry.trial_outcome:
        return False
    title = _("How did the trial go? %(title)s") % {"title": enquiry.title}
    comms.notify(
        "staff_enquiry_sla",
        (title, _("Record the trial outcome."), f"/leads/{enquiry.pk}"),
        key=f"trial:{enquiry.pk}",
    )
    return True


# --- waitlist (T07) -------------------------------------------------------------------------


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def add_to_waitlist(
    *,
    student: Student,
    subject: str = "",
    level: str = "",
    tutor: Any = None,
    service: Any = None,
    notes: str = "",
) -> WaitlistEntry:
    entry = WaitlistEntry.objects.create(
        student=student,
        subject=subject[:100],
        level=level[:100],
        tutor=tutor,
        service=service,
        notes=notes,
        branch_id=student.branch_id,
    )
    if student.status in (Student.Status.LEAD, Student.Status.PAUSED, Student.Status.FINISHED):
        from tutortrack.people.services import change_student_status

        change_student_status(student, Student.Status.WAITING)
    audit.record_create(entry)
    return entry


def position(entry: WaitlistEntry) -> int:
    ahead = WaitlistEntry.objects.filter(
        status=WaitlistEntry.Status.WAITING,
        subject=entry.subject,
        branch_id=entry.branch_id,
        created_at__lt=entry.created_at,
    ).count()
    return ahead + 1


@transaction.atomic
def offer_place(entry: WaitlistEntry, *, details: str, hours: int | None = None) -> str:
    """Offer the place with a time-limited accept link; returns the raw token."""
    entry = WaitlistEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.status != WaitlistEntry.Status.WAITING:
        raise BusinessRuleViolation(_("This student isn't waiting."))
    hours = hours or int(get_setting("leads.waitlist_offer_hours"))
    token = secrets.token_urlsafe(24)
    with audit.track(entry, action="offer"):
        entry.status = WaitlistEntry.Status.OFFERED
        entry.offer_details = details[:500]
        entry.offer_token_hash = _hash(token)
        entry.offered_at = now()
        entry.offer_expires_at = now() + timedelta(hours=hours)
        entry.save()
    publish(
        events.WaitlistPlaceOffered(
            subject_id=entry.pk,
            student_id=str(entry.student_id),
            expires_at=entry.offer_expires_at.isoformat(),
        ),
        branch_id=entry.branch_id,
    )
    from tutortrack.comms import services as comms

    transaction.on_commit(
        lambda: comms.notify(
            "waitlist_offer", (entry.pk, token), key=f"offer:{entry.pk}:{token[:8]}"
        )
    )
    return token


def offer_for_token(token: str) -> WaitlistEntry:
    entry = (
        WaitlistEntry.objects.select_related("student")
        .filter(offer_token_hash=_hash(token))
        .first()
    )
    if entry is None:
        raise NotFound()
    return entry


@transaction.atomic
def respond(token: str, *, accept: bool) -> WaitlistEntry:
    entry = WaitlistEntry.objects.select_for_update().get(pk=offer_for_token(token).pk)
    if entry.status != WaitlistEntry.Status.OFFERED or (
        entry.offer_expires_at and entry.offer_expires_at <= now()
    ):
        raise BusinessRuleViolation(_("This offer has expired."), extra={"code": "expired"})
    with audit.track(entry, action="accept" if accept else "decline"):
        entry.status = WaitlistEntry.Status.ACCEPTED if accept else WaitlistEntry.Status.DECLINED
        entry.responded_at = now()
        entry.save()
    event = events.WaitlistPlaceAccepted if accept else events.WaitlistPlaceDeclined
    publish(event(subject_id=entry.pk, student_id=str(entry.student_id)), branch_id=entry.branch_id)
    return entry


@transaction.atomic
def expire_offer(entry_id: Any) -> str:
    """Offer ran out: mark it expired and (setting) offer the place to the next student."""
    entry = WaitlistEntry.objects.select_for_update().filter(pk=entry_id).first()
    if entry is None or entry.status != WaitlistEntry.Status.OFFERED:
        return ""
    entry.status = WaitlistEntry.Status.EXPIRED
    entry.save(update_fields=["status", "updated_at"])
    publish(
        events.WaitlistOfferExpired(subject_id=entry.pk, student_id=str(entry.student_id)),
        branch_id=entry.branch_id,
    )
    if not get_setting("leads.waitlist_auto_cascade"):
        return ""
    return cascade(entry)


def cascade(entry: WaitlistEntry) -> str:
    following = (
        WaitlistEntry.objects.filter(
            status=WaitlistEntry.Status.WAITING, subject=entry.subject, branch_id=entry.branch_id
        )
        .exclude(pk=entry.pk)
        .order_by("created_at")
        .first()
    )
    if following is None:
        return ""
    offer_place(following, details=entry.offer_details)
    return str(following.pk)


@transaction.atomic
def remove_from_waitlist(entry: WaitlistEntry) -> WaitlistEntry:
    with audit.track(entry, action="remove"):
        entry.status = WaitlistEntry.Status.REMOVED
        entry.save(update_fields=["status", "updated_at"])
    return entry


# --- reporting (T10) ------------------------------------------------------------------------


def funnel(pipeline: Pipeline, start: datetime, end: datetime) -> dict[str, Any]:
    """Conversion by stage, source and owner; first response; win rate; lost reasons."""
    enquiries = Enquiry.objects.filter(pipeline=pipeline, created_at__gte=start, created_at__lt=end)
    total = enquiries.count()
    reached = dict(
        EnquiryStageHistory.objects.filter(enquiry__in=enquiries)
        .values("to_stage")
        .annotate(n=Count("enquiry", distinct=True))
        .values_list("to_stage", "n")
    )
    stages = [
        {
            "stage": s.name,
            "kind": s.kind,
            "reached": reached.get(s.pk, 0),
            "rate": round(100 * reached.get(s.pk, 0) / total, 1) if total else 0.0,
        }
        for s in pipeline.stages.order_by("order")
    ]
    won = enquiries.filter(status=Enquiry.Status.WON)
    closed = enquiries.exclude(status=Enquiry.Status.OPEN).count()
    responses = [
        (e.first_response_at - e.created_at).total_seconds() / 3600
        for e in enquiries.exclude(first_response_at__isnull=True).only(
            "created_at", "first_response_at"
        )
    ]

    def breakdown(field: str) -> list[dict[str, Any]]:
        rows = (
            enquiries.values(field)
            .annotate(total=Count("id"), won=Count("id", filter=Q(status=Enquiry.Status.WON)))
            .order_by("-total")
        )
        return [{"key": str(r[field] or ""), "total": r["total"], "won": r["won"]} for r in rows]

    value: dict[str, Decimal] = {}
    for e in won.exclude(value_estimate_amount__isnull=True):
        value[e.currency] = value.get(e.currency, Decimal(0)) + e.value_estimate.amount
    return {
        "total": total,
        "stages": stages,
        "win_rate": round(100 * won.count() / closed, 1) if closed else 0.0,
        "first_response_hours": round(sum(responses) / len(responses), 1) if responses else None,
        "by_source": breakdown("source"),
        "by_owner": breakdown("owner__email"),
        "lost_reasons": list(
            enquiries.filter(status=Enquiry.Status.LOST)
            .values("lost_reason")
            .annotate(count=Count("id"))
            .order_by("-count")
        ),
        "won_value": {c: str(v) for c, v in value.items()},
    }
