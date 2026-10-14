"""Review, referral, affiliate and tutor-referral writes (E25).

Other apps do the money: referral credit is an E10 ledger adjustment
(``billing.services.adjust_ledger``), the referee's discount an E06 client discount
(``catalogue.services.save_discount``), testimonials are E24 records
(``sites.services.save_testimonial``), tutor bonuses E12 pay items
(``payroll.services.create_manual_item``) and affiliate bank files E12's
(``payroll.services.external_bank_file``). Every write is audited and publishes its events
inside the transaction.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core import signing
from django.db import transaction
from django.db.models import Q, Sum
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.money import Money, sum_money
from tutortrack.core.sequences import next_number
from tutortrack.core.time import now
from tutortrack.people.models import Client, Contact, Student, TutorProfile
from tutortrack.tenancy.settings_service import get_setting

from . import commission, events, selectors
from .models import (
    Affiliate,
    AffiliateLink,
    AffiliateReferral,
    AffiliateStatement,
    CommissionItem,
    CommissionRule,
    Referral,
    ReferralCode,
    ReferralProgram,
    Review,
    ReviewRequest,
    TutorReferral,
)
from .processes import referral_workflow_id, review_workflow_id

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
OPEN_REQUESTS = (ReviewRequest.Status.PENDING, ReviewRequest.Status.REMINDED)
REVIEW_SALT = "growth.review"


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def _setting(key: str) -> Any:
    return get_setting(f"growth.{key}")


def _org_currency() -> str:
    from tutortrack.tenancy.models import Organisation

    return str(Organisation.objects.get(pk=require_organisation_id()).default_currency)


def org_today() -> date:
    from zoneinfo import ZoneInfo

    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    return now().astimezone(ZoneInfo(str(org.timezone or "UTC"))).date()


# --- codes (T03, T04, T06) ----------------------------------------------------------------------


def percent_text(value: Decimal) -> str:
    """``Decimal("10.00")`` → ``"10"``, ``Decimal("12.50")`` → ``"12.5"``."""
    text = f"{Decimal(value):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def normalise_code(code: str) -> str:
    return "".join(str(code or "").split()).upper()[:20]


def _code_taken(code: str) -> bool:
    return (
        ReferralCode.objects.filter(code=code).exists()
        or AffiliateLink.objects.filter(code=code).exists()
    )


def new_code(length: int = 8) -> str:
    for _attempt in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))
        if not _code_taken(code):
            return code
    raise BusinessRuleViolation(_("Couldn't make a unique code; try again."))


@transaction.atomic
def code_for_client(client: Client) -> ReferralCode:
    """The client's referral code (created on first use)."""
    code = ReferralCode.objects.filter(client=client).first()
    if code is None:
        code = ReferralCode.objects.create(client=client, code=new_code())
        audit.record_create(code)
    return code


@transaction.atomic
def code_for_tutor(tutor: TutorProfile) -> ReferralCode:
    code = ReferralCode.objects.filter(tutor=tutor).first()
    if code is None:
        code = ReferralCode.objects.create(tutor=tutor, code=new_code())
        audit.record_create(code)
    return code


def resolve_code(raw: str) -> ReferralCode | AffiliateLink | None:
    """An active referral code or affiliate link, or None."""
    code = normalise_code(raw)
    if not code:
        return None
    found = ReferralCode.objects.filter(code=code, active=True).first()
    if found is not None:
        return found
    return (
        AffiliateLink.objects.filter(code=code, active=True)
        .exclude(affiliate__status=Affiliate.Status.ARCHIVED)
        .select_related("affiliate")
        .first()
    )


@transaction.atomic
def record_click(raw: str) -> ReferralCode | AffiliateLink | None:
    """A visit through a referral or affiliate link (counted, not stored per visitor)."""
    from django.db.models import F

    found = resolve_code(raw)
    if found is not None:
        type(found).objects.filter(pk=found.pk).update(clicks=F("clicks") + 1)
    return found


# --- reviews (T01, T02) -------------------------------------------------------------------------


def review_token(request: ReviewRequest) -> str:
    return signing.dumps(
        str(request.pk), salt=f"{REVIEW_SALT}:{request.organisation_id}", compress=True
    )


def request_for_token(token: str) -> ReviewRequest:
    if not token or len(token) > 300:
        raise NotFound()
    try:
        pk = signing.loads(
            token,
            salt=f"{REVIEW_SALT}:{require_organisation_id()}",
            max_age=timedelta(days=200),
        )
    except signing.BadSignature:
        raise NotFound() from None
    request = (
        ReviewRequest.objects.select_related("client", "tutor", "student", "contact")
        .filter(pk=pk)
        .first()
    )
    if request is None:
        raise NotFound()
    return request


def criteria_keys() -> list[str]:
    raw = str(_setting("review_criteria") or "")
    return [c.strip().lower().replace(" ", "_")[:30] for c in raw.split(",") if c.strip()][:8]


@transaction.atomic
def request_review(
    *,
    client: Client,
    tutor: TutorProfile | None = None,
    student: Student | None = None,
    contact: Contact | None = None,
    trigger: str = ReviewRequest.Trigger.MANUAL,
    lesson_count: int = 0,
) -> ReviewRequest | None:
    """Ask a family for a review (FR-25-1). Skipped (None) when the family already has an
    open request for this tutor, or (automatic triggers) was asked about this tutor before."""
    pair = ReviewRequest.objects.filter(client=client, tutor=tutor)
    if pair.filter(status__in=OPEN_REQUESTS).exists():
        return None
    if trigger != ReviewRequest.Trigger.MANUAL and pair.filter(trigger=trigger).exists():
        return None
    request = ReviewRequest.objects.create(
        client=client,
        tutor=tutor,
        student=student,
        contact=contact or client.primary_contact or client.billing_contact,
        trigger=trigger,
        lesson_count=lesson_count,
        expires_at=now() + timedelta(days=int(_setting("review_expiry_days"))),
    )
    request.workflow_id = review_workflow_id(request.organisation_id, request.pk)
    request.save(update_fields=["workflow_id", "updated_at"])
    audit.record_create(request)
    publish(
        events.ReviewRequested(
            subject_id=request.pk,
            client_id=str(client.pk),
            tutor_id=str(tutor.pk) if tutor else None,
            trigger=trigger,
        ),
        branch_id=client.branch_id,
    )
    return request


def review_request_state(request_id: Any) -> dict[str, Any]:
    """What ``ReviewRequestWorkflow`` needs: status and when to remind/expire."""
    request = ReviewRequest.objects.get(pk=request_id)
    reminder_at = request.created_at + timedelta(days=int(_setting("review_reminder_days")))
    return {
        "status": request.status,
        "reminder_at": min(reminder_at, request.expires_at).isoformat(),
        "expires_at": request.expires_at.isoformat(),
    }


@transaction.atomic
def send_review_request(request_id: Any, *, reminder: bool = False) -> bool:
    """Email (or text) the review link; the reminder goes once. Idempotent."""
    from tutortrack.comms import services as comms

    request = ReviewRequest.objects.select_for_update().get(pk=request_id)
    if request.status not in OPEN_REQUESTS:
        return False
    if reminder and request.reminded_at is not None:
        return False
    kind = "reminder" if reminder else "first"
    comms.notify(
        "review_request",
        (str(request.pk), review_token(request), reminder),
        key=f"review-request:{request.pk}:{kind}",
    )
    with audit.track(request, action="remind" if reminder else "send"):
        if reminder:
            request.reminded_at = now()
            request.status = ReviewRequest.Status.REMINDED
        else:
            request.sent_at = request.sent_at or now()
        request.save()
    return True


@transaction.atomic
def expire_request(request_id: Any) -> str:
    request = ReviewRequest.objects.select_for_update().get(pk=request_id)
    if request.status in OPEN_REQUESTS:
        with audit.track(request, action="expire"):
            request.status = ReviewRequest.Status.EXPIRED
            request.save(update_fields=["status", "updated_at"])
    return str(request.status)


@transaction.atomic
def cancel_request(request: ReviewRequest) -> ReviewRequest:
    from tutortrack.core.workflows import signal

    request = ReviewRequest.objects.select_for_update().get(pk=request.pk)
    if request.status not in OPEN_REQUESTS:
        raise BusinessRuleViolation(_("This request is no longer open."))
    with audit.track(request, action="cancel"):
        request.status = ReviewRequest.Status.CANCELLED
        request.save(update_fields=["status", "updated_at"])
    signal(review_workflow_id(request.organisation_id, request.pk), "cancelled")
    return request


def _check_review(rating: Any, criteria: dict[str, Any] | None, text: str) -> dict[str, int]:
    from tutortrack.sites import moderation

    try:
        value = int(rating)
    except (TypeError, ValueError):
        value = 0
    if not 1 <= value <= 5:
        raise _invalid("rating", _("Choose from 1 to 5 stars."))
    allowed = set(criteria_keys())
    out: dict[str, int] = {}
    for key, score in (criteria or {}).items():
        if key not in allowed:
            raise _invalid("criteria", _("Unknown rating criterion."))
        if score in (None, ""):
            continue
        try:
            number = int(score)
        except (TypeError, ValueError):
            number = 0
        if not 1 <= number <= 5:
            raise _invalid("criteria", _("Choose from 1 to 5 stars."))
        out[key] = number
    if len(text) > 5000:
        raise _invalid("text", _("Please keep the review under 5,000 characters."))
    if text and moderation.issues(text, contact_filter=False):
        raise _invalid("text", _("Please remove offensive language."))
    return out


def google_prompt_url(review: Review) -> str:
    """FR-25-1: 4 and 5 star reviewers are invited to review on Google too."""
    url = str(_setting("google_review_url") or "")
    return url if url and review.rating >= 4 else ""


@transaction.atomic
def submit_review(
    request: ReviewRequest,
    *,
    rating: int,
    criteria: dict[str, Any] | None = None,
    text: str = "",
    reviewer_name: str = "",
    publish_consent: bool = False,
) -> Review:
    """The family's answer to a request (public page). Goes to the moderation queue."""
    request = ReviewRequest.objects.select_for_update().get(pk=request.pk)
    if request.status not in OPEN_REQUESTS or request.expires_at <= now():
        raise BusinessRuleViolation(_("This review link has closed. Thank you anyway!"))
    scores = _check_review(rating, criteria, text)
    name = reviewer_name.strip()[:120] or (
        request.contact.first_name if request.contact else request.client.display_name
    )
    review = Review.objects.create(
        request=request,
        client=request.client,
        contact=request.contact,
        student=request.student,
        tutor=request.tutor,
        rating=int(rating),
        criteria=scores,
        text=text.strip(),
        reviewer_name=name,
        publish_consent=publish_consent,
        source=Review.Source.REQUEST,
    )
    review.google_prompted = bool(google_prompt_url(review))
    review.save(update_fields=["google_prompted", "updated_at"])
    audit.record_create(review)
    with audit.track(request, action="submit"):
        request.status = ReviewRequest.Status.SUBMITTED
        request.submitted_at = now()
        request.save(update_fields=["status", "submitted_at", "updated_at"])
    _published(review, events.ReviewSubmitted, request_id=str(request.pk))
    return review


def _published(review: Review, event: Any, **extra: Any) -> None:
    publish(
        event(
            subject_id=review.pk,
            client_id=str(review.client_id),
            tutor_id=str(review.tutor_id) if review.tutor_id else None,
            rating=review.rating,
            **extra,
        ),
        branch_id=review.client.branch_id,
    )


@transaction.atomic
def create_review(
    *,
    client: Client,
    rating: int,
    tutor: TutorProfile | None = None,
    student: Student | None = None,
    contact: Contact | None = None,
    criteria: dict[str, Any] | None = None,
    text: str = "",
    reviewer_name: str = "",
    publish_consent: bool = False,
    source: str = Review.Source.STAFF,
) -> Review:
    """A review typed in by staff (e.g. from an email) or left in the portal."""
    scores = _check_review(rating, criteria, text)
    if not reviewer_name.strip():
        raise _invalid("reviewer_name", _("Say how the reviewer wants to be named."))
    review = Review.objects.create(
        client=client,
        contact=contact,
        student=student,
        tutor=tutor,
        rating=int(rating),
        criteria=scores,
        text=text.strip(),
        reviewer_name=reviewer_name.strip()[:120],
        publish_consent=publish_consent,
        source=source,
    )
    audit.record_create(review)
    _published(review, events.ReviewSubmitted, request_id=None)
    return review


@transaction.atomic
def moderate(review: Review, *, action: str, user: Any = None) -> Review:
    """Approve or hide (FR-25-1 moderation). Approving a 4-5 star review the family agreed
    to publish makes it a testimonial when ``growth.auto_testimonial`` is on."""
    if action not in ("approve", "hide"):
        raise _invalid("action", _("Approve or hide the review."))
    review = (
        Review.objects.select_for_update(of=("self",)).select_related("client").get(pk=review.pk)
    )
    target = Review.Status.APPROVED if action == "approve" else Review.Status.HIDDEN
    if review.status == target:
        return review
    with audit.track(review, action=action):
        review.status = target
        review.moderated_at = now()
        review.moderated_by = user
        review.save()
    if target == Review.Status.APPROVED:
        _published(review, events.ReviewPublished)
        if review.publish_consent and review.rating >= 4 and _setting("auto_testimonial"):
            publish_testimonial(review)
    elif review.testimonial_id:
        unpublish_testimonial(review)
    return review


@transaction.atomic
def respond(review: Review, *, response: str, user: Any = None) -> Review:
    """A public reply from the business (shown with the review)."""
    text = response.strip()
    if len(text) > 2000:
        raise _invalid("response", _("Please keep the reply under 2,000 characters."))
    with audit.track(review, action="respond"):
        review.response = text
        review.responded_at = now() if text else None
        review.save(update_fields=["response", "responded_at", "updated_at"])
    return review


def _testimonial_role(review: Review) -> str:
    if review.tutor_id and review.tutor is not None:
        return _("Review of %(tutor)s") % {
            "tutor": review.tutor.display_name or review.tutor.first_name
        }
    return ""


@transaction.atomic
def publish_testimonial(review: Review) -> Review:
    """Show an approved review on the website (E24 ``<tt-reviews>`` and testimonials)."""
    from tutortrack.sites import services as sites

    review = (
        Review.objects.select_for_update(of=("self",)).select_related("tutor").get(pk=review.pk)
    )
    if review.status != Review.Status.APPROVED:
        raise BusinessRuleViolation(_("Approve the review first."))
    if not review.publish_consent:
        raise BusinessRuleViolation(_("The reviewer didn't agree to publication."))
    if not review.text:
        raise BusinessRuleViolation(_("Only reviews with a comment can be testimonials."))
    current = review.testimonial
    testimonial = sites.save_testimonial(
        current,
        quote=review.text[:2000],
        author=review.reviewer_name,
        role=_testimonial_role(review)[:120],
        rating=review.rating,
        tutor=review.tutor,
        published=True,
    )
    if current is None:
        with audit.track(review, action="publish_testimonial"):
            review.testimonial = testimonial
            review.save(update_fields=["testimonial", "updated_at"])
    return review


@transaction.atomic
def unpublish_testimonial(review: Review) -> Review:
    from tutortrack.sites import services as sites

    if review.testimonial is not None:
        sites.save_testimonial(review.testimonial, published=False)
    return review


def lesson_completed(attendees: list[dict[str, Any]], tutors: list[dict[str, Any]]) -> list[Any]:
    """FR-25-1: after N completed lessons with a tutor, ask the family for a review."""
    from tutortrack.scheduling.selectors import completed_lesson_count

    threshold = int(_setting("review_after_lessons"))
    if threshold <= 0:
        return []
    made = []
    attended = {
        (str(a["client_id"]), str(a["student_id"]))
        for a in attendees
        if a.get("client_id") and a.get("outcome") in ("present", "late", "", None)
    }
    for client_id, student_id in sorted(attended):
        for row in tutors:
            count = completed_lesson_count(client_id=client_id, tutor_id=row["tutor_id"])
            if count < threshold:
                continue
            client = Client.objects.filter(pk=client_id, archived_at__isnull=True).first()
            tutor = TutorProfile.objects.filter(pk=row["tutor_id"]).first()
            if client is None or tutor is None:
                continue
            request = request_review(
                client=client,
                tutor=tutor,
                student=Student.objects.filter(pk=student_id).first(),
                trigger=ReviewRequest.Trigger.LESSONS,
                lesson_count=count,
            )
            if request is not None:
                made.append(request)
    return made


def trial_completed(enquiry_id: Any) -> ReviewRequest | None:
    """FR-25-1: a review request after a trial lesson (E17 ``trial_lesson.completed``)."""
    if not _setting("review_after_trial"):
        return None
    found = selectors.enquiry_people(enquiry_id)
    if found is None:
        return None
    client, tutor, student = found
    return request_review(
        client=client, tutor=tutor, student=student, trigger=ReviewRequest.Trigger.TRIAL
    )


# --- referral programme (T03) -------------------------------------------------------------------


def _check_percent(name: str, value: Any) -> None:
    if value is not None and not Decimal(0) < Decimal(value) <= Decimal(100):
        raise _invalid(name, _("Percentages run from 0 to 100."))


@transaction.atomic
def save_program(program: ReferralProgram | None, **data: Any) -> ReferralProgram:
    created = program is None
    program = program or ReferralProgram()
    _check_percent("referee_discount_percent", data.get("referee_discount_percent"))
    reward = data.pop("referrer_reward", None)
    with audit.track(program):
        for key, value in data.items():
            setattr(program, key, value)
        if reward is not None:
            if not reward.is_positive():
                raise _invalid("referrer_reward", _("Enter the reward."))
            program.currency = reward.currency
            program.referrer_reward = reward.round_to_minor()
        if created and reward is None:
            raise _invalid("referrer_reward", _("Enter the reward."))
        if not program.name.strip():
            raise _invalid("name", _("Name the programme."))
        program.save()
    if created:
        audit.record_create(program)
    return program


def active_program() -> ReferralProgram | None:
    if not _setting("referrals_enabled"):
        return None
    return ReferralProgram.objects.filter(active=True).order_by("-created_at").first()


def _has_paid(client_id: Any, *, since: datetime | None = None) -> bool:
    return selectors.succeeded_payments(client_id, since=since).exists()


@transaction.atomic
def create_referral(
    *,
    referrer: Client,
    referee: Client,
    source: str = Referral.Source.LINK,
    code: ReferralCode | None = None,
    enquiry_id: str = "",
    note: str = "",
) -> Referral:
    """FR-25-2: a new family referred by an existing one."""
    program = active_program()
    if program is None:
        raise BusinessRuleViolation(_("There is no active referral programme."))
    if referrer.pk == referee.pk:
        raise _invalid("referee", _("A family can't refer itself."))
    if Referral.objects.filter(referee=referee).exists():
        raise _invalid("referee", _("This family was already referred."))
    if _has_paid(referee.pk):
        raise _invalid("referee", _("Only new families can be referred."))
    referral = Referral.objects.create(
        program=program,
        code=code,
        referrer=referrer,
        referee=referee,
        enquiry_id=str(enquiry_id or ""),
        source=source,
        deadline=now() + timedelta(days=program.deadline_days),
        note=note[:300],
    )
    referral.workflow_id = referral_workflow_id(referral.organisation_id, referral.pk)
    referral.save(update_fields=["workflow_id", "updated_at"])
    audit.record_create(referral)
    publish(
        events.ReferralCreated(
            subject_id=referral.pk,
            referrer_id=str(referrer.pk),
            referee_id=str(referee.pk),
            source=source,
        ),
        branch_id=referee.branch_id,
    )
    return referral


def referral_state(referral_id: Any) -> dict[str, Any]:
    """What ``ReferralRewardWorkflow`` needs (a snapshot at its start)."""
    referral = Referral.objects.select_related("program").get(pk=referral_id)
    return {
        "status": referral.status,
        "deadline": referral.deadline.isoformat(),
        "milestone": referral.program.milestone,
    }


def milestone_reached(referral_id: Any) -> bool:
    """First paid invoice (any successful payment) or N completed lessons."""
    from tutortrack.scheduling.selectors import completed_lesson_count

    referral = Referral.objects.select_related("program").get(pk=referral_id)
    if referral.program.milestone == ReferralProgram.Milestone.LESSONS:
        needed = max(1, referral.program.milestone_lessons)
        return completed_lesson_count(client_id=referral.referee_id) >= needed
    return _has_paid(referral.referee_id)


def _referral_event(referral: Referral, event: Any, **extra: Any) -> None:
    publish(
        event(
            subject_id=referral.pk,
            referrer_id=str(referral.referrer_id),
            referee_id=str(referral.referee_id),
            **extra,
        ),
        branch_id=referral.referee.branch_id,
    )


@transaction.atomic
def convert_referral(referral_id: Any) -> str:
    referral = (
        Referral.objects.select_for_update(of=("self",))
        .select_related("referee")
        .get(pk=referral_id)
    )
    if referral.status != Referral.Status.PENDING:
        return str(referral.status)
    with audit.track(referral, action="convert"):
        referral.status = Referral.Status.CONVERTED
        referral.converted_at = now()
        referral.save(update_fields=["status", "converted_at", "updated_at"])
    _referral_event(referral, events.ReferralConverted)
    return str(referral.status)


def _emails(client: Client) -> set[str]:
    out = set()
    for contact in client.contacts.all():
        email = (contact.email or "").strip().lower()
        if "@" in email:
            local, domain = email.split("@", 1)
            local = local.split("+", 1)[0]
            if domain in ("gmail.com", "googlemail.com"):
                local, domain = local.replace(".", ""), "gmail.com"
            out.add(f"{local}@{domain}")
    return out


def _phones(client: Client) -> set[str]:
    out = set()
    for contact in client.contacts.all():
        for raw in (contact.mobile, contact.phone):
            digits = "".join(ch for ch in raw or "" if ch.isdigit())
            if len(digits) >= 7:
                out.add(digits[-9:])
    return out


def _address(client: Client) -> tuple[str, str] | None:
    address = client.billing_address
    if address is None or not address.postcode:
        return None
    postcode = "".join(address.postcode.split()).upper()
    return (postcode, "".join((address.line1 or "").split()).lower())


def fraud_flags(referral: Referral) -> list[str]:
    """FR-25-2 fraud guards: the same email, phone, address or card on both families,
    and the referrer's reward limit for the period."""
    referrer, referee = referral.referrer, referral.referee
    flags = []
    if _emails(referrer) & _emails(referee):
        flags.append("same_email")
    if _phones(referrer) & _phones(referee):
        flags.append("same_phone")
    address = _address(referee)
    if address is not None and address == _address(referrer):
        flags.append("same_address")
    if selectors.payment_fingerprints(referrer.pk) & selectors.payment_fingerprints(referee.pk):
        flags.append("same_payment_method")
    program = referral.program
    if program.max_rewards_per_period:
        since = now() - timedelta(days=program.period_days)
        rewarded = Referral.objects.filter(
            referrer=referrer, status=Referral.Status.REWARDED, rewarded_at__gte=since
        ).count()
        if rewarded >= program.max_rewards_per_period:
            flags.append("reward_limit")
    return flags


@transaction.atomic
def reward_referral(referral_id: Any, *, force: bool = False, user: Any = None) -> str:
    """Fraud checks, then the referrer's credit (E10) and the referee's discount (E06).
    Idempotent; a referral held by the checks waits for staff (``force``)."""
    from tutortrack.billing import services as billing
    from tutortrack.catalogue import services as catalogue

    referral = (
        Referral.objects.select_for_update(of=("self",))
        .select_related("program", "referrer", "referee")
        .get(pk=referral_id)
    )
    allowed = {Referral.Status.CONVERTED} | ({Referral.Status.BLOCKED} if force else set())
    if referral.status not in allowed:
        return str(referral.status)
    flags = [] if force else fraud_flags(referral)
    if flags:
        with audit.track(referral, action="block"):
            referral.status = Referral.Status.BLOCKED
            referral.fraud_flags = flags
            referral.save(update_fields=["status", "fraud_flags", "updated_at"])
        return str(referral.status)
    program = referral.program
    reward = program.referrer_reward.round_to_minor()
    label = (
        _("Referral reward: a free lesson for referring %(name)s")
        if program.referrer_reward_kind == ReferralProgram.RewardKind.FREE_LESSON
        else _("Referral reward for referring %(name)s")
    ) % {"name": referral.referee.display_name}
    billing.adjust_ledger(referral.referrer, -reward, reason=label, user=user)
    billing.apply_credit_to_open_invoices(referral.referrer, reward.currency, user=user)
    discount_id = ""
    if program.referee_discount_percent:
        today = org_today()
        rule = catalogue.save_discount(
            None,
            name=_("Referral welcome discount")[:150],
            kind="client",
            client=referral.referee,
            percent=program.referee_discount_percent,
            valid_from=today,
            valid_to=today + timedelta(days=program.referee_discount_days),
        )
        discount_id = str(rule.pk)
    with audit.track(referral, action="reward"):
        referral.status = Referral.Status.REWARDED
        referral.rewarded_at = now()
        referral.referrer_credit = reward
        referral.referee_discount_id = discount_id
        if force and referral.fraud_flags:
            referral.note = (
                _("Approved by staff despite: %(flags)s")
                % {"flags": ", ".join(referral.fraud_flags)}
            )[:300]
        referral.save()
    _referral_event(
        referral,
        events.ReferralRewarded,
        credit=reward.to_dict(),
        referee_discount=bool(discount_id),
    )
    return str(referral.status)


@transaction.atomic
def expire_referral(referral_id: Any) -> str:
    referral = Referral.objects.select_for_update().get(pk=referral_id)
    if referral.status == Referral.Status.PENDING:
        with audit.track(referral, action="expire"):
            referral.status = Referral.Status.EXPIRED
            referral.save(update_fields=["status", "updated_at"])
    return str(referral.status)


@transaction.atomic
def cancel_referral(referral: Referral, *, reason: str = "") -> Referral:
    from tutortrack.core.workflows import signal

    referral = Referral.objects.select_for_update().get(pk=referral.pk)
    if referral.status not in (
        Referral.Status.PENDING,
        Referral.Status.CONVERTED,
        Referral.Status.BLOCKED,
    ):
        raise BusinessRuleViolation(_("This referral can't be cancelled now."))
    with audit.track(referral, action="cancel"):
        referral.status = Referral.Status.CANCELLED
        referral.note = reason[:300]
        referral.save(update_fields=["status", "note", "updated_at"])
    signal(referral_workflow_id(referral.organisation_id, referral.pk), "cancel")
    return referral


@transaction.atomic
def approve_blocked(referral: Referral, *, user: Any = None) -> Referral:
    """Staff decided the fraud flags were a false alarm: reward anyway."""
    if referral.status != Referral.Status.BLOCKED:
        raise BusinessRuleViolation(_("Only referrals held by the fraud checks need this."))
    reward_referral(referral.pk, force=True, user=user)
    referral.refresh_from_db()
    return referral


# --- attribution (T03, T04, T06) ----------------------------------------------------------------


def attribute_enquiry(enquiry_id: Any) -> Any:
    """``enquiry.received`` with ``utm.ref``: a referral (client code), a tutor's client
    referral (tutor code) or an affiliate client (affiliate link)."""
    found = selectors.enquiry_ref(enquiry_id)
    if found is None:
        return None
    client, ref = found
    target = resolve_code(ref)
    if target is None:
        return None
    with transaction.atomic():
        if isinstance(target, AffiliateLink):
            return attribute_to_affiliate(
                target.affiliate, client=client, link=target, enquiry_id=str(enquiry_id)
            )
        if target.tutor is not None:
            if TutorReferral.objects.filter(client=client).exists():
                return None
            return record_tutor_referral(
                referrer=target.tutor, kind=TutorReferral.Kind.CLIENT, client=client
            )
        referrer = target.client
        if referrer is None or referrer.pk == client.pk or active_program() is None:
            return None
        if Referral.objects.filter(referee=client).exists() or _has_paid(client.pk):
            return None
        return create_referral(
            referrer=referrer,
            referee=client,
            code=target,
            source=Referral.Source.LINK,
            enquiry_id=str(enquiry_id),
        )


def attribute_application(application_id: Any) -> TutorReferral | None:
    """``application.submitted`` with a tutor's code (FR-25-4, E18 attribution)."""
    found = selectors.application_ref(application_id)
    if found is None:
        return None
    name, ref = found
    target = resolve_code(ref)
    if not isinstance(target, ReferralCode) or target.tutor is None:
        return None
    if TutorReferral.objects.filter(application_id=str(application_id)).exists():
        return None
    with transaction.atomic():
        return record_tutor_referral(
            referrer=target.tutor,
            kind=TutorReferral.Kind.TUTOR,
            application_id=str(application_id),
            referred_name=name,
        )


# --- affiliates (T04) ---------------------------------------------------------------------------


AFFILIATE_FIELDS = (
    "kind",
    "name",
    "email",
    "phone",
    "status",
    "currency",
    "payout_method",
    "payee_name",
    "notes",
)


@transaction.atomic
def save_affiliate(
    affiliate: Affiliate | None, *, bank: dict[str, Any] | None = None, **data: Any
) -> Affiliate:
    from tutortrack.payroll import banking

    created = affiliate is None
    affiliate = affiliate or Affiliate()
    with audit.track(affiliate):
        for key in AFFILIATE_FIELDS:
            if key in data:
                setattr(affiliate, key, data[key])
        if not affiliate.currency:
            affiliate.currency = _org_currency()
        if not str(affiliate.name).strip():
            raise _invalid("name", _("Enter the affiliate's name."))
        if not affiliate.email:
            raise _invalid("email", _("Enter an email address."))
        affiliate.email = affiliate.email.strip().lower()
        if bank is not None:
            country = str(data.get("bank_country") or affiliate.bank_country or "GB").upper()
            details = banking.clean(
                country, {"account_name": affiliate.payee_name or affiliate.name, **bank}
            )
            affiliate.bank_country = country
            affiliate.bank_details = banking.dumps(details)
            affiliate.bank_hint = banking.hint(details)
        if (
            affiliate.payout_method == Affiliate.PayoutMethod.BANK_FILE
            and not affiliate.bank_details
        ):
            raise _invalid("bank", _("Add bank details to pay by bank transfer."))
        affiliate.save()
    if created:
        audit.record_create(affiliate)
        save_link(None, affiliate=affiliate, name=_("Main link"))
    return affiliate


@transaction.atomic
def invite_affiliate(affiliate: Affiliate) -> Any:
    """A login to the affiliate portal (role Affiliate; linked when they accept)."""
    from tutortrack.identity import services as identity

    if affiliate.user_id is not None:
        raise BusinessRuleViolation(_("This affiliate already has a login."))
    invitation = identity.invite(
        affiliate.email,
        role="affiliate",
        target_type="growth.affiliate",
        target_id=str(affiliate.pk),
    )
    audit.record(affiliate, "invite", {"email": [None, affiliate.email]})
    return invitation


@transaction.atomic
def link_affiliate_user(affiliate_id: str, user: Any) -> Affiliate | None:
    affiliate = Affiliate.objects.filter(pk=affiliate_id).first()
    if affiliate is not None and affiliate.user_id is None:
        with audit.track(affiliate, action="link_user"):
            affiliate.user = user
            affiliate.save(update_fields=["user", "updated_at"])
    return affiliate


@transaction.atomic
def save_link(
    link: AffiliateLink | None, *, affiliate: Affiliate | None = None, **data: Any
) -> AffiliateLink:
    created = link is None
    link = link or AffiliateLink(affiliate=affiliate)
    if "code" in data:
        code = normalise_code(data.pop("code"))
        if code and code != link.code:
            if len(code) < 4:
                raise _invalid("code", _("Codes have at least 4 characters."))
            if _code_taken(code):
                raise _invalid("code", _("That code is already in use."))
            link.code = code
    if not link.code:
        link.code = new_code()
    with audit.track(link):
        for key in ("name", "landing_path", "active"):
            if key in data:
                setattr(link, key, data[key])
        path = str(link.landing_path or "/")
        if not path.startswith("/") or path.startswith("//"):
            raise _invalid("landing_path", _("Use a path on your website, like /maths."))
        link.save()
    if created:
        audit.record_create(link)
    return link


@transaction.atomic
def attribute_to_affiliate(
    affiliate: Affiliate,
    *,
    client: Client,
    link: AffiliateLink | None = None,
    enquiry_id: str = "",
    source: str = AffiliateReferral.Source.LINK,
) -> AffiliateReferral | None:
    """A client brought by an affiliate (first affiliate wins; None if already attributed)."""
    if affiliate.status != Affiliate.Status.ACTIVE:
        return None
    if AffiliateReferral.objects.filter(client=client).exists():
        return None
    referral = AffiliateReferral.objects.create(
        affiliate=affiliate,
        client=client,
        link=link,
        source=source,
        attributed_at=now(),
        enquiry_id=enquiry_id,
    )
    audit.record_create(referral)
    return referral


def assign_client(affiliate: Affiliate, client: Client) -> AffiliateReferral:
    """Staff attribute a client to an affiliate by hand."""
    referral = attribute_to_affiliate(
        affiliate, client=client, source=AffiliateReferral.Source.STAFF
    )
    if referral is None:
        raise _invalid(
            "client",
            _("This client already belongs to an affiliate, or the affiliate isn't active."),
        )
    return referral


# --- commission (T05) ---------------------------------------------------------------------------


@transaction.atomic
def save_rule(rule: CommissionRule | None, **data: Any) -> CommissionRule:
    created = rule is None
    rule = rule or CommissionRule()
    bounty = data.pop("bounty", None)
    if "tiers" in data:
        try:
            data["tiers"] = commission.validate_tiers(data["tiers"])
        except (ValueError, InvalidOperation) as exc:
            raise _invalid(
                "tiers", _("Tiers need a number of clients (1 or more) and a rate.")
            ) from exc
    with audit.track(rule):
        for key in ("affiliate", "name", "kind", "active", "percent", "tiers", "duration_months"):
            if key in data:
                setattr(rule, key, data[key])
        if rule.kind == CommissionRule.Kind.PERCENT:
            if rule.percent is None or not Decimal(0) < Decimal(rule.percent) <= Decimal(100):
                raise _invalid("percent", _("Percentages run from 0 to 100."))
        else:
            if bounty is None and rule.bounty is None:
                raise _invalid("bounty", _("Enter the bounty."))
        if bounty is not None:
            if not bounty.is_positive():
                raise _invalid("bounty", _("Enter the bounty."))
            rule.currency = bounty.currency
            rule.bounty = bounty.round_to_minor()
        if not str(rule.name).strip():
            raise _invalid("name", _("Name the rule."))
        rule.save()
    if created:
        audit.record_create(rule)
    return rule


def rules_for(affiliate: Affiliate) -> list[CommissionRule]:
    """Per-affiliate overrides replace the defaults, kind by kind."""
    rules = list(
        CommissionRule.objects.filter(active=True).filter(
            Q(affiliate=affiliate) | Q(affiliate__isnull=True)
        )
    )
    own_kinds = {r.kind for r in rules if r.affiliate_id is not None}
    return [r for r in rules if r.affiliate_id is not None or r.kind not in own_kinds]


def converted_clients(affiliate: Affiliate) -> int:
    return AffiliateReferral.objects.filter(affiliate=affiliate, converted_at__isnull=False).count()


def _commission_event(item: CommissionItem, event: Any) -> None:
    publish(
        event(
            subject_id=item.pk,
            affiliate_id=str(item.affiliate_id),
            client_id=str(item.client_id) if item.client_id else None,
            amount=item.amount.to_dict(),
            kind=item.kind,
        )
    )


def _item(**fields: Any) -> CommissionItem:
    amount = fields.pop("amount")
    item = CommissionItem(
        currency=amount.currency, earned_at=fields.pop("earned_at", now()), **fields
    )
    item.amount = amount
    item.save()
    audit.record_create(item)
    return item


@transaction.atomic
def record_payment_commission(payment_id: Any) -> list[CommissionItem]:
    """FR-25-3: commission on a referred client's collected payment (``payment.succeeded``):
    a percentage within the rule's window and, on the client's first payment, the bounty.
    Idempotent per payment and rule."""
    payment = selectors.payment_info(payment_id)
    if payment is None:
        return []
    referral = (
        AffiliateReferral.objects.select_for_update(of=("self",))
        .select_related("affiliate")
        .filter(client_id=payment["client_id"])
        .first()
    )
    if referral is None or referral.affiliate.status != Affiliate.Status.ACTIVE:
        return []
    affiliate = referral.affiliate
    first_payment = referral.converted_at is None
    if first_payment:
        with audit.track(referral, action="convert"):
            referral.converted_at = payment["received_at"]
            referral.save(update_fields=["converted_at", "updated_at"])
    amount: Money = payment["amount"]
    made = []
    for rule in rules_for(affiliate):
        if rule.kind == CommissionRule.Kind.PERCENT:
            if not commission.in_window(
                referral.attributed_at, rule.duration_months, payment["received_at"]
            ):
                continue
            key = f"payment:{payment_id}:{rule.pk}"
            if CommissionItem.objects.filter(source_key=key).exists():
                continue
            rate = commission.tier_percent(
                Decimal(rule.percent or 0), rule.tiers, converted_clients(affiliate)
            )
            value = commission.commission_for(amount, rate)
            if value.is_zero():
                continue
            made.append(
                _item(
                    affiliate=affiliate,
                    referral=referral,
                    client_id=payment["client_id"],
                    rule=rule,
                    kind=CommissionItem.Kind.COMMISSION,
                    source_key=key,
                    payment_id=str(payment_id),
                    base=amount,
                    rate=rate,
                    amount=value,
                    earned_at=payment["received_at"],
                    description=_("%(rate)s%% of payment %(ref)s")
                    % {"rate": percent_text(rate), "ref": payment["reference"]},
                )
            )
        elif rule.bounty is not None and first_payment:
            key = f"bounty:{referral.pk}:{rule.pk}"
            if CommissionItem.objects.filter(source_key=key).exists():
                continue
            made.append(
                _item(
                    affiliate=affiliate,
                    referral=referral,
                    client_id=payment["client_id"],
                    rule=rule,
                    kind=CommissionItem.Kind.BOUNTY,
                    source_key=key,
                    payment_id=str(payment_id),
                    amount=rule.bounty.round_to_minor(),
                    earned_at=payment["received_at"],
                    description=_("Bounty for a new client"),
                )
            )
    for item in made:
        _commission_event(item, events.CommissionEarned)
    return made


@transaction.atomic
def record_refund_clawback(payment_id: Any, refund_id: Any, refund: Money) -> list[CommissionItem]:
    """FR-25-3: a refund within ``growth.clawback_days`` of the payment takes back the
    commission at the original rate (a negative item; never more than was earned)."""
    payment = selectors.payment_info(payment_id)
    if payment is None:
        return []
    window = int(_setting("clawback_days"))
    if now() - payment["received_at"] > timedelta(days=window):
        return []
    made = []
    earned_items = CommissionItem.objects.select_for_update().filter(
        payment_id=str(payment_id), kind=CommissionItem.Kind.COMMISSION
    )
    for earned in earned_items:
        key = f"refund:{refund_id}:{earned.pk}"
        if CommissionItem.objects.filter(source_key=key).exists():
            continue
        clawed_total = CommissionItem.objects.filter(
            kind=CommissionItem.Kind.CLAWBACK, source_key__endswith=f":{earned.pk}"
        ).aggregate(t=Sum("amount_amount"))["t"] or Decimal(0)
        clawed = Money(-clawed_total, earned.currency)
        value = commission.clawback_for(refund, Decimal(earned.rate or 0), earned.amount, clawed)
        if value.is_zero():
            continue
        made.append(
            _item(
                affiliate_id=earned.affiliate_id,
                referral_id=earned.referral_id,
                client_id=earned.client_id,
                rule_id=earned.rule_id,
                kind=CommissionItem.Kind.CLAWBACK,
                source_key=key,
                payment_id=str(payment_id),
                base=refund,
                rate=earned.rate,
                amount=value,
                description=_("Refund of %(amount)s") % {"amount": refund.amount},
            )
        )
    for item in made:
        _commission_event(item, events.CommissionClawedBack)
    return made


@transaction.atomic
def adjust_commission(
    affiliate: Affiliate, *, amount: Money, description: str, user: Any = None
) -> CommissionItem:
    """A manual correction (positive or negative) for the next statement."""
    if amount.is_zero() or not description.strip():
        raise _invalid("amount", _("Give an amount and a reason."))
    item = _item(
        affiliate=affiliate,
        kind=CommissionItem.Kind.ADJUSTMENT,
        source_key=f"adjustment:{secrets.token_hex(8)}",
        amount=amount.round_to_minor(),
        description=description.strip()[:300],
    )
    _commission_event(item, events.CommissionEarned)
    return item


def _month_before(day: date) -> tuple[date, date]:
    end = day.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


@transaction.atomic
def issue_statements(
    period_end: date | None = None, *, user: Any = None
) -> list[AffiliateStatement]:
    """Statements for every affiliate with commission up to ``period_end`` (default: the
    end of last month). Items left out (newer, or a net negative total) carry forward."""
    from datetime import UTC
    from datetime import time as dtime

    period_end = period_end or _month_before(org_today())[1]
    cutoff = datetime.combine(period_end + timedelta(days=1), dtime(0), tzinfo=UTC)
    open_items = CommissionItem.objects.select_for_update().filter(
        statement__isnull=True, earned_at__lt=cutoff
    )
    groups: dict[tuple[Any, str], list[CommissionItem]] = {}
    for item in open_items.order_by("earned_at", "id"):
        groups.setdefault((item.affiliate_id, item.currency), []).append(item)
    issued = []
    for (affiliate_id, currency), items in sorted(groups.items(), key=lambda kv: str(kv[0])):
        total = sum_money((i.amount for i in items), currency)
        if not total.is_positive():
            continue
        start = min(i.earned_at for i in items).date()
        statement = AffiliateStatement(
            affiliate_id=affiliate_id,
            number=next_number("affiliate_statement", prefix="AFS-"),
            period_start=min(start, period_end),
            period_end=period_end,
            currency=currency,
            issued_at=now(),
        )
        statement.total = total
        statement.save()
        audit.record_create(statement)
        for item in items:
            item.statement = statement
            item.save(update_fields=["statement", "updated_at"])
        publish(
            events.AffiliateStatementIssued(
                subject_id=statement.pk,
                affiliate_id=str(affiliate_id),
                number=statement.number,
                total=total.to_dict(),
            )
        )
        _tell_affiliate(statement)
        issued.append(statement)
    return issued


def _tell_affiliate(statement: AffiliateStatement) -> None:
    """Email the statement after commit (the organisation is captured now)."""
    org = require_organisation_id()
    statement_id = statement.pk
    transaction.on_commit(lambda: _notify_statement(org, statement_id))


def _notify_statement(org: Any, statement_id: Any) -> None:
    from tutortrack.comms import services as comms
    from tutortrack.core.context import tenant_context

    with tenant_context(org), transaction.atomic():
        comms.notify(
            "affiliate_statement_issued", str(statement_id), key=f"statement:{statement_id}"
        )


@transaction.atomic
def mark_statement_paid(
    statement: AffiliateStatement, *, reference: str = "", user: Any = None
) -> AffiliateStatement:
    statement = AffiliateStatement.objects.select_for_update().get(pk=statement.pk)
    if statement.status == AffiliateStatement.Status.PAID:
        return statement
    with audit.track(statement, action="pay"):
        statement.status = AffiliateStatement.Status.PAID
        statement.paid_at = now()
        statement.payout_reference = reference.strip()[:100]
        statement.payout_method = statement.affiliate.payout_method
        statement.save()
    return statement


def statements_bank_file(
    statements: list[AffiliateStatement], *, fmt: str | None = None
) -> tuple[str, str]:
    """An E12 bank file paying the statements' affiliates (bank-transfer affiliates only)."""
    from tutortrack.payroll import banking
    from tutortrack.payroll import services as payroll

    payees = []
    for st in statements:
        affiliate = st.affiliate
        if st.status != AffiliateStatement.Status.ISSUED:
            raise _invalid("statements", _("%(number)s is already paid.") % {"number": st.number})
        if affiliate.payout_method != Affiliate.PayoutMethod.BANK_FILE:
            raise _invalid("statements", _("%(name)s is paid manually.") % {"name": affiliate.name})
        details = banking.loads(affiliate.bank_details)
        if not details:
            raise _invalid(
                "statements", _("%(name)s has no bank details.") % {"name": affiliate.name}
            )
        payees.append((affiliate.payee_name or affiliate.name, details, st.total, st.number))
    filename, content = payroll.external_bank_file(
        payees, file_id=f"affiliates-{org_today().isoformat()}", fmt=fmt
    )
    for st in statements:
        audit.record(st, "bank_file", {"file": [None, filename]})
    return filename, content


@transaction.atomic
def update_payout_details(
    affiliate: Affiliate, *, bank: dict[str, Any], payee_name: str = "", country: str = ""
) -> Affiliate:
    """The affiliate (portal) or staff change where commission is paid."""
    data: dict[str, Any] = {"payout_method": Affiliate.PayoutMethod.BANK_FILE}
    if payee_name:
        data["payee_name"] = payee_name[:140]
    if country:
        data["bank_country"] = country
    return save_affiliate(affiliate, bank=bank, **data)


# --- tutor referral bonuses (T06) ---------------------------------------------------------------


@transaction.atomic
def record_tutor_referral(
    *,
    referrer: TutorProfile,
    kind: str,
    application_id: str = "",
    referred_tutor: TutorProfile | None = None,
    client: Client | None = None,
    referred_name: str = "",
    note: str = "",
) -> TutorReferral:
    if kind == TutorReferral.Kind.CLIENT and client is None:
        raise _invalid("client", _("Choose the client."))
    if kind == TutorReferral.Kind.TUTOR and not (application_id or referred_tutor):
        raise _invalid("referred_tutor", _("Choose the tutor or application."))
    if referred_tutor is not None and referred_tutor.pk == referrer.pk:
        raise _invalid("referred_tutor", _("A tutor can't refer themselves."))
    if client is not None and TutorReferral.objects.filter(client=client).exists():
        raise _invalid("client", _("This client was already referred by a tutor."))
    if application_id and TutorReferral.objects.filter(application_id=application_id).exists():
        raise _invalid("application", _("This application was already referred."))
    referral = TutorReferral.objects.create(
        referrer=referrer,
        kind=kind,
        application_id=application_id or "",
        referred_tutor=referred_tutor,
        client=client,
        note=note[:300],
        referred_name=(
            referred_name
            or (client.display_name if client else "")
            or (referred_tutor.full_name if referred_tutor else "")
        )[:200],
    )
    audit.record_create(referral)
    return referral


def _bonus_for(referral: TutorReferral) -> Money | None:
    from tutortrack.payroll.services import currency_for

    key = (
        "tutor_referral_bonus"
        if referral.kind == TutorReferral.Kind.TUTOR
        else "tutor_client_referral_bonus"
    )
    amount = int(_setting(key))
    if amount <= 0:
        return None
    return Money(Decimal(amount), currency_for(referral.referrer))


@transaction.atomic
def pay_tutor_referral(referral: TutorReferral, *, amount: Money | None = None) -> TutorReferral:
    """The milestone was reached: the referral bonus becomes an E12 pay item (once)."""
    from tutortrack.payroll import services as payroll

    referral = (
        TutorReferral.objects.select_for_update().select_related("referrer").get(pk=referral.pk)
    )
    if referral.status != TutorReferral.Status.PENDING:
        return referral
    bonus = amount or _bonus_for(referral)
    if bonus is None or not bonus.is_positive():
        return referral
    name = referral.referred_name or _("a referral")
    item = payroll.create_manual_item(
        tutor=referral.referrer,
        kind="referral",
        description=_("Referral bonus: %(name)s") % {"name": name},
        amount=bonus.round_to_minor(),
        day=org_today(),
        source_key=f"tutor-referral:{referral.pk}",
    )
    with audit.track(referral, action="pay"):
        referral.status = TutorReferral.Status.PAID
        referral.qualified_at = now()
        referral.bonus = bonus.round_to_minor()
        referral.pay_item_id = str(item.pk)
        referral.save()
    return referral


@transaction.atomic
def reject_tutor_referral(referral: TutorReferral, *, note: str = "") -> TutorReferral:
    if referral.status != TutorReferral.Status.PENDING:
        raise BusinessRuleViolation(_("Only waiting referrals can be rejected."))
    with audit.track(referral, action="reject"):
        referral.status = TutorReferral.Status.REJECTED
        referral.note = note[:300]
        referral.save(update_fields=["status", "note", "updated_at"])
    return referral


def application_approved(application_id: Any, tutor_id: Any) -> TutorReferral | None:
    """E18 approved the referred applicant: link the tutor; pay now or after N lessons."""
    referral = TutorReferral.objects.filter(
        application_id=str(application_id), status=TutorReferral.Status.PENDING
    ).first()
    tutor = TutorProfile.objects.filter(pk=tutor_id).first()
    if referral is None or tutor is None:
        return None
    with transaction.atomic():
        if referral.referred_tutor_id is None:
            with audit.track(referral, action="link_tutor"):
                referral.referred_tutor = tutor
                referral.save(update_fields=["referred_tutor", "updated_at"])
        if int(_setting("tutor_referral_milestone_lessons")) == 0:
            return pay_tutor_referral(referral)
    return referral


def tutor_lessons_completed(tutor_ids: list[str]) -> list[TutorReferral]:
    """Referred tutors who reached the lesson milestone earn their referrer the bonus."""
    from tutortrack.scheduling.selectors import completed_lesson_count

    needed = int(_setting("tutor_referral_milestone_lessons"))
    paid = []
    for referral in TutorReferral.objects.filter(
        kind=TutorReferral.Kind.TUTOR,
        status=TutorReferral.Status.PENDING,
        referred_tutor_id__in=tutor_ids,
    ):
        if completed_lesson_count(tutor_id=referral.referred_tutor_id) >= max(needed, 1):
            paid.append(pay_tutor_referral(referral))
    return paid


def client_paid(client_id: Any) -> TutorReferral | None:
    """A client referred by a tutor paid for the first time (FR-25-4 client milestone)."""
    referral = TutorReferral.objects.filter(
        client_id=client_id, status=TutorReferral.Status.PENDING
    ).first()
    return pay_tutor_referral(referral) if referral is not None else None
