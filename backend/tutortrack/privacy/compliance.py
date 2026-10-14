"""The tenant-facing Data Processing Agreement and the sub-processor list (E29-T11,
FR-29-8). Both are versioned in code; the documents live in ``docs/compliance/``.

When ``SUBPROCESSORS_VERSION`` changes, ``notify_subprocessor_changes`` (a Celery task,
fanned out per organisation; run after the deploy that changes the list) tells each
organisation's admins once."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import get_request_context
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now

from . import notifications
from .events import DPAAccepted
from .models import DPAAcceptance, SubprocessorNotice

DPA_VERSION = "2026-10"
DPA_EFFECTIVE = "2026-10-14"
DPA_URL = "https://tutortrack.app/legal/dpa/2026-10"
SUBPROCESSORS_VERSION = "2026-10-14.2"  # Phase 3 integrations (ADR 0032)


@dataclass(frozen=True)
class Subprocessor:
    name: str
    purpose: str
    data_categories: str
    location: str
    regions: tuple[str, ...]  # stacks that use it: uk, eu, us, au
    optional: bool = False  # only when the organisation switches the integration on


ALL = ("uk", "eu", "us", "au")
SUBPROCESSORS: tuple[Subprocessor, ...] = (
    Subprocessor(
        "Amazon Web Services",
        "Hosting, database, file storage, encryption keys (KMS), bulk email (SES)",
        "All customer data",
        "In the organisation's region (London, Frankfurt, N. Virginia, Sydney)",
        ALL,
    ),
    Subprocessor(
        "Temporal Technologies",
        "Workflow orchestration (Temporal Cloud)",
        "Record identifiers only; payloads are encrypted with our keys",
        "In the organisation's region",
        ALL,
    ),
    Subprocessor(
        "Postmark (ActiveCampaign)",
        "Transactional email",
        "Recipient name, email address, message content",
        "United States (SCCs/UK addendum)",
        ALL,
    ),
    Subprocessor(
        "Twilio",
        "SMS and WhatsApp messages",
        "Phone number, message content",
        "United States (SCCs/UK addendum)",
        ALL,
    ),
    Subprocessor(
        "Stripe",
        "Card payments and payouts",
        "Payer name, email, payment details",
        "United States and EU (SCCs/UK addendum)",
        ALL,
    ),
    Subprocessor(
        "GoCardless",
        "Direct Debit",
        "Payer name, email, bank details",
        "United Kingdom and EU",
        ("uk", "eu"),
        optional=True,
    ),
    Subprocessor(
        "PayPal",
        "PayPal payments",
        "Payer name, email, payment details",
        "Luxembourg",
        ALL,
        optional=True,
    ),
    Subprocessor(
        "Cloudflare",
        "Bot protection on public forms (Turnstile)",
        "IP address, browser signals",
        "Global edge network",
        ALL,
    ),
    Subprocessor(
        "Functional Software (Sentry)",
        "Error monitoring",
        "Technical error data; personal data is scrubbed before sending",
        "Germany (EU)",
        ALL,
    ),
    Subprocessor(
        "Google and Microsoft",
        "Calendar and video connections",
        "Lesson times, attendee emails",
        "Global (SCCs/UK addendum)",
        ALL,
        optional=True,
    ),
    Subprocessor(
        "Zoom and Lessonspace",
        "Online lesson rooms",
        "Participant names, meeting times",
        "Global (SCCs/UK addendum)",
        ALL,
        optional=True,
    ),
    Subprocessor(
        "Anthropic",
        "AI drafts, suggestions, command bar and copilot (Claude API; E31)",
        "Pseudonymised text for the AI feature in use (names, emails and phone numbers "
        "replaced where known); never safeguarding notes, encrypted fields, bank details "
        "or credentials. Not used for model training",
        "United States (SCCs/UK addendum)",
        ALL,
        optional=True,
    ),
    Subprocessor(
        "Xero and Intuit QuickBooks",
        "Accounting sync",
        "Client names, invoices, payments",
        "Global (SCCs/UK addendum)",
        ALL,
        optional=True,
    ),
    # --- Phase 3 integrations (ADR 0032); all optional ----------------------------------------
    Subprocessor(
        "Sage and FreeAgent",
        "Accounting sync (E23)",
        "Client names, invoices, payments",
        "United Kingdom, EU and United States (SCCs/UK addendum)",
        ALL,
        optional=True,
    ),
    Subprocessor(
        "Xero Payroll",
        "Employed tutors' timesheets (E23)",
        "Tutor names, hours worked",
        "Global (SCCs/UK addendum)",
        ("uk",),
        optional=True,
    ),
    Subprocessor(
        "Wise Payments",
        "Tutor payouts (E12)",
        "Tutor names, bank details, payout amounts",
        "United Kingdom, EU and United States (SCCs/UK addendum)",
        ALL,
        optional=True,
    ),
    Subprocessor(
        "uCheck (Atlantic Data)",
        "DBS background checks (E18)",
        "Tutor identity details, check results",
        "United Kingdom",
        ("uk",),
        optional=True,
    ),
    Subprocessor(
        "Checkr",
        "US background checks (E18)",
        "Tutor identity details, check results",
        "United States",
        ("us",),
        optional=True,
    ),
    Subprocessor(
        "Zoom, Daily.co and Lessonspace recordings",
        "Online lesson attendance and recordings (E22)",
        "Participant names, join and leave times, lesson recordings",
        "Global (SCCs/UK addendum)",
        ALL,
        optional=True,
    ),
    Subprocessor(
        "Google BigQuery and Snowflake",
        "Data warehouse export to the organisation's own warehouse (E26, Enterprise)",
        "Reporting data (lessons, charges, payments, pay; names of clients, students, tutors)",
        "The organisation's chosen region",
        ALL,
        optional=True,
    ),
)


def subprocessors(region: str | None = None) -> list[dict[str, Any]]:
    return [
        {**asdict(s), "regions": list(s.regions)}
        for s in SUBPROCESSORS
        if region is None or region in s.regions
    ]


# --- data processing agreement ------------------------------------------------------------------


def dpa_status() -> dict[str, Any]:
    current = DPAAcceptance.objects.filter(version=DPA_VERSION).first()
    return {
        "version": DPA_VERSION,
        "effective": DPA_EFFECTIVE,
        "url": DPA_URL,
        "accepted": current is not None,
        "acceptance": current,
        "history": list(DPAAcceptance.objects.all()[:20]),
    }


@transaction.atomic
def accept_dpa(
    *, user: Any, version: str, signer_name: str, signer_title: str = "", company_name: str
) -> DPAAcceptance:
    if version != DPA_VERSION:
        message = _("Accept the current version of the agreement.")
        raise BusinessRuleViolation(message, extra={"errors": {"version": [message]}})
    if not signer_name.strip() or not company_name.strip():
        message = _("Enter the signer's name and the company's legal name.")
        raise BusinessRuleViolation(message, extra={"errors": {"signer_name": [message]}})
    existing = DPAAcceptance.objects.filter(version=version).first()
    if existing is not None:
        return existing
    ctx = get_request_context()
    acceptance = DPAAcceptance.objects.create(
        version=version,
        accepted_by=user,
        signer_name=signer_name.strip()[:200],
        signer_title=signer_title.strip()[:200],
        company_name=company_name.strip()[:200],
        accepted_at=now(),
        ip=ctx.ip,
        user_agent=(ctx.user_agent or "")[:500],
    )
    audit.record_create(acceptance)
    publish(DPAAccepted(subject_id=acceptance.pk, dpa_version=version))
    return acceptance


# --- sub-processor change notices ---------------------------------------------------------------


@transaction.atomic
def notify_subprocessor_change() -> bool:
    """Tell the organisation in context about the current list, once per version."""
    if SubprocessorNotice.objects.filter(version=SUBPROCESSORS_VERSION).exists():
        return False
    SubprocessorNotice.objects.create(version=SUBPROCESSORS_VERSION, notified_at=now())
    notifications.send(
        "privacy_subprocessors_changed",
        (
            _("TutorTrack's list of sub-processors has changed"),
            _(
                "Review the updated list. You can object within 30 days under the data "
                "processing agreement."
            ),
            notifications.admin_link("/settings/compliance"),
        ),
        key=f"subprocessors:{SUBPROCESSORS_VERSION}",
    )
    return True
