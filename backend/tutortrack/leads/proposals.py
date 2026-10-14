"""Proposals with online acceptance (FR-17-3, E17-T09): the write side and the PDF.

Staff write a proposal on an enquiry: introduction, suggested tutors (E19 public cards),
schedule, priced lines (rounded half-up per line) and an optional deposit. ``send()``
signs a link (``/proposals/<token>``), emails it with the PDF attached and publishes
``proposal.sent``, which starts ``ProposalWorkflow`` (reminder, then expiry). The family
reads it, may pick a tutor and accepts by typing their name: ``accept()`` converts the
enquiry (client and students active, a job per service, FR-17-5), offers the job to the
chosen tutor (E19 flow) and, with a deposit, creates an E10 payment request whose E11 pay
link the page opens next.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog
from django.core import signing
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.money import Money
from tutortrack.core.sequences import next_number
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import events
from .models import Enquiry, Proposal

logger = structlog.get_logger(__name__)
SALT = "proposal"
OPEN = (Proposal.Status.SENT,)
MAX_LINES = 30


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


# --- pricing ------------------------------------------------------------------------------------


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise _invalid(field_name, _("Enter a number.")) from None
    if not number.is_finite():
        raise _invalid(field_name, _("Enter a number."))
    return number


def price_lines(raw: list[dict[str, Any]], currency: str) -> tuple[list[dict[str, Any]], Money]:
    """Validate lines and price them: ``amount = quantity * unit price`` rounded half-up to
    the currency's minor unit per line; the total is the sum of the rounded lines."""
    from tutortrack.catalogue.models import Service

    if len(raw) > MAX_LINES:
        raise _invalid("lines", _("Use at most %(n)s lines.") % {"n": MAX_LINES})
    out: list[dict[str, Any]] = []
    total = Money.zero(currency)
    for row in raw:
        service = None
        if row.get("service"):
            service = Service.objects.filter(pk=row["service"]).first()
            if service is None:
                raise _invalid("lines", _("Unknown service."))
        description = str(row.get("description") or (service.name if service else "")).strip()
        if not description:
            raise _invalid("lines", _("Describe each line."))
        quantity = _decimal(row.get("quantity", 1), "lines")
        unit = _decimal(row.get("unit_price", 0), "lines")
        if quantity <= 0 or quantity > 1000:
            raise _invalid("lines", _("Quantities run from more than 0 to 1000."))
        if unit < 0:
            raise _invalid("lines", _("Prices can't be negative."))
        amount = (Money(unit, currency) * quantity).round_to_minor()
        total = total + amount
        out.append(
            {
                "service": str(service.pk) if service else None,
                "description": description[:300],
                "quantity": str(quantity.normalize()),
                "unit_price": str(Money(unit, currency).round_to_minor().amount),
                "amount": str(amount.amount),
            }
        )
    return out, total


# --- drafting -----------------------------------------------------------------------------------


def _tutor_ids(raw: list[Any]) -> list[str]:
    from tutortrack.people.models import TutorProfile

    ids = [str(t) for t in raw]
    found = {
        str(pk)
        for pk in TutorProfile.objects.filter(pk__in=ids, archived_at__isnull=True).values_list(
            "pk", flat=True
        )
    }
    if set(ids) - found:
        raise _invalid("tutors", _("Unknown tutor."))
    return list(dict.fromkeys(ids))


@transaction.atomic
def save_proposal(
    enquiry: Enquiry,
    *,
    proposal: Proposal | None = None,
    title: str = "",
    introduction: str = "",
    schedule: str = "",
    terms: str | None = None,
    lines: list[dict[str, Any]] | None = None,
    tutors: list[Any] | None = None,
    currency: str = "",
    deposit: Any = None,
    valid_days: int | None = None,
    contact: Any = None,
) -> Proposal:
    """Create a draft, or update one (only drafts can change)."""
    if proposal is not None and proposal.status != Proposal.Status.DRAFT:
        raise BusinessRuleViolation(_("Only draft proposals can be changed."))
    currency = currency or (proposal.currency if proposal else "") or enquiry.client.currency
    priced, total = price_lines(lines or [], currency)
    deposit_money = None
    if deposit not in (None, ""):
        deposit_money = Money(_decimal(deposit, "deposit"), currency).round_to_minor()
        if not deposit_money.is_positive():
            deposit_money = None
        elif deposit_money > total:
            raise _invalid("deposit", _("The deposit can't be more than the total."))
    if contact is not None and contact.client_id != enquiry.client_id:
        raise _invalid("contact", _("Choose a contact of this family."))
    values = {
        "title": (title or enquiry.title)[:200],
        "introduction": introduction,
        "schedule": schedule,
        "terms": str(get_setting("leads.proposal_terms") or "") if terms is None else terms,
        "lines": priced,
        "tutors": _tutor_ids(tutors or []),
        "currency": currency,
        "valid_days": int(valid_days or get_setting("leads.proposal_valid_days")),
        "contact": contact or enquiry.contact,
    }
    if proposal is None:
        proposal = Proposal(
            enquiry=enquiry,
            branch_id=enquiry.branch_id,
            number=next_number("proposal", prefix="PRO-"),
            **values,
        )
        proposal.total = total
        proposal.deposit = deposit_money
        proposal.save()
        audit.record_create(proposal)
        return proposal
    with audit.track(proposal, action="update"):
        for key, value in values.items():
            setattr(proposal, key, value)
        proposal.total = total
        proposal.deposit = deposit_money
        proposal.save()
    return proposal


# --- tokens -------------------------------------------------------------------------------------


def token_for(proposal: Proposal) -> str:
    return signing.dumps(str(proposal.pk), salt=f"{SALT}:{proposal.organisation_id}", compress=True)


def for_token(token: str) -> Proposal:
    if not token or len(token) > 300:
        raise NotFound()
    try:
        pk = signing.loads(
            token, salt=f"{SALT}:{require_organisation_id()}", max_age=timedelta(days=200)
        )
    except signing.BadSignature:
        raise NotFound() from None
    proposal = (
        Proposal.objects.select_related("enquiry", "enquiry__client", "contact")
        .filter(pk=pk)
        .exclude(status__in=[Proposal.Status.DRAFT, Proposal.Status.WITHDRAWN])
        .first()
    )
    if proposal is None:
        raise NotFound()
    return proposal


def state(proposal: Proposal) -> str:
    """``sent`` turns into ``expired`` the moment the deadline passes (the workflow then
    records it)."""
    if (
        proposal.status == Proposal.Status.SENT
        and proposal.expires_at
        and proposal.expires_at <= now()
    ):
        return str(Proposal.Status.EXPIRED)
    return str(proposal.status)


# --- sending ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Notice:
    """The notification subject: the proposal (loaded again for the PDF attachment), its
    signed link token and whether this is the reminder."""

    pk: str
    token: str
    reminder: bool = False


@transaction.atomic
def send(proposal: Proposal, *, user: Any = None) -> Proposal:
    from tutortrack.comms import services as comms

    proposal = Proposal.objects.select_for_update().get(pk=proposal.pk)
    if proposal.status != Proposal.Status.DRAFT:
        raise BusinessRuleViolation(_("This proposal has already been sent."))
    if not proposal.lines:
        raise _invalid("lines", _("Add at least one priced line."))
    if proposal.contact is None:
        raise _invalid("contact", _("Choose who receives the proposal."))
    with audit.track(proposal, action="send"):
        proposal.status = Proposal.Status.SENT
        proposal.sent_at = now()
        proposal.expires_at = now() + timedelta(days=proposal.valid_days)
        proposal.save()
    _to_proposal_stage(proposal.enquiry, user)
    publish(
        events.ProposalSent(
            subject_id=proposal.pk,
            enquiry_id=str(proposal.enquiry_id),
            expires_at=proposal.expires_at.isoformat(),
        ),
        branch_id=proposal.branch_id,
    )
    comms.notify_on_commit(
        "proposal_sent",
        Notice(str(proposal.pk), token_for(proposal)),
        key=f"proposal:{proposal.pk}",
    )
    return proposal


def _to_proposal_stage(enquiry: Enquiry, user: Any) -> None:
    """Move the enquiry to a stage called "Proposal" when the pipeline has one."""
    from . import services

    if enquiry.status != Enquiry.Status.OPEN:
        return
    stage = enquiry.pipeline.stages.filter(name__iexact="Proposal", kind="open").first()
    if stage is not None and stage.pk != enquiry.stage_id:
        services.move(enquiry, stage, user=user)


def remind(proposal_id: Any) -> bool:
    """The reminder before expiry (once; the workflow calls it)."""
    from tutortrack.comms import services as comms

    proposal = Proposal.objects.filter(pk=proposal_id).first()
    if proposal is None or state(proposal) != Proposal.Status.SENT:
        return False
    comms.notify(
        "proposal_sent",
        Notice(str(proposal.pk), token_for(proposal), reminder=True),
        key=f"proposal-reminder:{proposal.pk}",
    )
    return True


@transaction.atomic
def expire(proposal_id: Any) -> bool:
    proposal = Proposal.objects.select_for_update().filter(pk=proposal_id).first()
    if proposal is None or proposal.status != Proposal.Status.SENT:
        return False
    with audit.track(proposal, action="expire"):
        proposal.status = Proposal.Status.EXPIRED
        proposal.save(update_fields=["status", "updated_at"])
    publish(
        events.ProposalExpired(subject_id=proposal.pk, enquiry_id=str(proposal.enquiry_id)),
        branch_id=proposal.branch_id,
    )
    return True


@transaction.atomic
def withdraw(proposal: Proposal) -> Proposal:
    proposal = Proposal.objects.select_for_update().get(pk=proposal.pk)
    if proposal.status not in (Proposal.Status.DRAFT, Proposal.Status.SENT):
        raise BusinessRuleViolation(_("This proposal can't be withdrawn now."))
    was_sent = proposal.status == Proposal.Status.SENT
    with audit.track(proposal, action="withdraw"):
        proposal.status = Proposal.Status.WITHDRAWN
        proposal.save(update_fields=["status", "updated_at"])
    if was_sent:
        publish(
            events.ProposalWithdrawn(subject_id=proposal.pk, enquiry_id=str(proposal.enquiry_id)),
            branch_id=proposal.branch_id,
        )
    return proposal


# --- the family ---------------------------------------------------------------------------------


def public_view(token: str) -> dict[str, Any]:
    """What the family sees: no internal notes, tutors as public cards (E19)."""
    from tutortrack.matching.sharing import tutor_cards

    proposal = for_token(token)
    if proposal.viewed_at is None:
        Proposal.objects.filter(pk=proposal.pk, viewed_at__isnull=True).update(viewed_at=now())
    pay_url = ""
    if proposal.payment_request_id and proposal.payment_request is not None:
        request = proposal.payment_request
        if request.status != "paid" and request.pay_token:
            pay_url = f"/pay/{request.pay_token}"
    return {
        "number": proposal.number,
        "title": proposal.title,
        "status": state(proposal),
        "introduction": proposal.introduction,
        "schedule": proposal.schedule,
        "terms": proposal.terms,
        "lines": [
            {k: row[k] for k in ("description", "quantity", "unit_price", "amount")}
            for row in proposal.lines
        ],
        "currency": proposal.currency,
        "total": str(proposal.total.amount),
        "deposit": str(proposal.deposit.amount) if proposal.deposit else None,
        "expires_at": proposal.expires_at,
        "tutors": tutor_cards(proposal.tutors),
        "chosen_tutor": str(proposal.chosen_tutor_id) if proposal.chosen_tutor_id else None,
        "students": [s.preferred_name or s.first_name for s in proposal.enquiry.students.all()],
        "pay_url": pay_url,
    }


def _closed(proposal: Proposal) -> BusinessRuleViolation:
    current = state(proposal)
    if current == Proposal.Status.ACCEPTED:
        return BusinessRuleViolation(
            _("You have already accepted this proposal."), extra={"code": "accepted"}
        )
    if current == Proposal.Status.DECLINED:
        return BusinessRuleViolation(
            _("You have already declined this proposal."), extra={"code": "declined"}
        )
    return BusinessRuleViolation(_("This proposal has expired."), extra={"code": "expired"})


@transaction.atomic
def accept(
    token: str, *, name: str, tutor_id: str | None = None, ip: str | None = None
) -> tuple[Proposal, str]:
    """The family accepts: convert the enquiry, offer the chosen tutor, ask for the
    deposit. Returns the proposal and the pay link (empty without a deposit)."""
    from tutortrack.billing.services import create_payment_request
    from tutortrack.catalogue.models import Service
    from tutortrack.people.models import TutorProfile

    from . import services

    proposal = Proposal.objects.select_for_update().get(pk=for_token(token).pk)
    if state(proposal) != Proposal.Status.SENT:
        raise _closed(proposal)
    name = name.strip()
    if len(name) < 2:
        raise _invalid("name", _("Type your full name to accept."))
    tutor = None
    if tutor_id:
        if str(tutor_id) not in proposal.tutors:
            raise _invalid("tutor", _("Choose one of the tutors in the proposal."))
        tutor = TutorProfile.objects.get(pk=tutor_id)
    elif len(proposal.tutors) == 1:
        tutor = TutorProfile.objects.filter(pk=proposal.tutors[0]).first()
    enquiry = proposal.enquiry
    jobs: list[Any] = []
    if enquiry.status == Enquiry.Status.OPEN:
        service_ids = list(dict.fromkeys(r["service"] for r in proposal.lines if r.get("service")))
        specs = [{"service": s} for s in Service.objects.filter(pk__in=service_ids)]
        jobs = services.convert(enquiry, jobs=specs)["jobs"]
    if tutor is not None:
        for job in jobs:
            _offer(job, tutor)
    pay_url = ""
    request = None
    if proposal.deposit is not None and proposal.deposit.is_positive():
        request = create_payment_request(
            client=enquiry.client,
            amount=proposal.deposit,
            description=_("Deposit for proposal %(number)s") % {"number": proposal.number},
        )
        pay_url = f"/pay/{request.pay_token}" if request.pay_token else ""
    with audit.track(proposal, action="accept"):
        proposal.status = Proposal.Status.ACCEPTED
        proposal.responded_at = now()
        proposal.accepted_name = name[:200]
        proposal.accepted_ip = ip
        proposal.chosen_tutor = tutor
        proposal.job_ids = [str(j.pk) for j in jobs]
        proposal.payment_request = request
        proposal.save()
    publish(
        events.ProposalAccepted(
            subject_id=proposal.pk,
            enquiry_id=str(enquiry.pk),
            client_id=str(enquiry.client_id),
            job_ids=proposal.job_ids,
            tutor_id=str(tutor.pk) if tutor else None,
            payment_request_id=str(request.pk) if request else None,
        ),
        branch_id=proposal.branch_id,
    )
    _tell_staff(proposal, accepted=True)
    return proposal, pay_url


def _offer(job: Any, tutor: Any) -> None:
    """Offer the new job to the tutor the family chose (E19 flow); staff decide if not."""
    from tutortrack.matching import services as matching

    try:
        with transaction.atomic():
            matching.shortlist_add(job, tutor)
            matching.start_offers(job, [tutor])
    except BusinessRuleViolation as exc:
        logger.info("leads.proposal_offer_skipped", job=str(job.pk), reason=str(exc))


@transaction.atomic
def decline(token: str, *, reason: str = "") -> Proposal:
    proposal = Proposal.objects.select_for_update().get(pk=for_token(token).pk)
    if state(proposal) != Proposal.Status.SENT:
        raise _closed(proposal)
    with audit.track(proposal, action="decline"):
        proposal.status = Proposal.Status.DECLINED
        proposal.responded_at = now()
        proposal.decline_reason = reason.strip()[:500]
        proposal.save()
    publish(
        events.ProposalDeclined(subject_id=proposal.pk, enquiry_id=str(proposal.enquiry_id)),
        branch_id=proposal.branch_id,
    )
    _tell_staff(proposal, accepted=False)
    return proposal


def _tell_staff(proposal: Proposal, *, accepted: bool) -> None:
    from tutortrack.comms import services as comms

    template = (
        _("Proposal %(number)s accepted by %(name)s")
        if accepted
        else _("Proposal %(number)s declined")
    )
    title = template % {"number": proposal.number, "name": proposal.accepted_name}
    body = proposal.title if accepted else (proposal.decline_reason or proposal.title)
    payload = (title, body, f"/leads/{proposal.enquiry_id}")
    comms.notify_on_commit(
        "staff_proposal_response", payload, key=f"proposal-response:{proposal.pk}"
    )


# --- the document -------------------------------------------------------------------------------


def pdf(proposal: Proposal) -> bytes:
    """The branded proposal PDF (WeasyPrint), rendered on demand."""
    from django.template.loader import render_to_string
    from django.utils import translation
    from weasyprint import HTML

    from tutortrack.core import branding
    from tutortrack.matching.sharing import tutor_cards
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=proposal.organisation_id)
    locale = str(org.locale or "en-GB").replace("-", "_")

    def money(amount: Any) -> str:
        return Money(Decimal(str(amount)), proposal.currency).format(locale)

    with translation.override(locale.replace("_", "-")):
        html = render_to_string(
            "leads/proposal.html",
            {
                "org": org,
                "brand": branding.for_documents(org.pk),
                "proposal": proposal,
                "client_name": proposal.enquiry.client.display_name,
                "contact_name": proposal.contact.full_name if proposal.contact else "",
                "lines": [
                    {
                        **row,
                        "unit_price": money(row["unit_price"]),
                        "amount": money(row["amount"]),
                    }
                    for row in proposal.lines
                ],
                "total": money(proposal.total.amount),
                "deposit": money(proposal.deposit.amount) if proposal.deposit else "",
                "tutors": tutor_cards(proposal.tutors),
            },
        )
    return bytes(HTML(string=html).write_pdf())
