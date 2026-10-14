"""Wise payouts (E12-T12, FR-12-7): sending, status tracking and webhooks.

``send`` runs inside ``services.send_payouts`` (``PayRunWorkflow`` "paying" step) for
pending payouts whose method is ``wise``: one Wise transfer per payout, in the payout's
currency, funded from the organisation's Wise balance; the transfer id becomes the
payout's ``provider_ref`` and is remembered for webhook routing.

Settlement arrives two ways, both idempotent:

* the ``transfers#state-change`` webhook (``/webhooks/wise``, RSA-signed) updates the
  payout and signals ``settled`` to the pay run's workflow;
* the workflow's daily settle check calls ``refresh`` (``payouts_outstanding``), which
  asks Wise for each processing transfer, so a lost webhook only delays settlement.

A failed or bounced transfer returns the items for the next run (``services.fail_payout``).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core.context import tenant_context
from tutortrack.integrations import routes
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import Credentials, ProviderError
from tutortrack.tenancy.settings_service import get_setting

from . import banking
from .models import PayMethod, Payout, PayRun, TutorPayProfile
from .payouts import TransferResult, wise_client

logger = structlog.get_logger(__name__)
PROVIDER = "wise"


def connection() -> IntegrationConnection | None:
    return (
        IntegrationConnection.objects.filter(provider=PROVIDER, user__isnull=True)
        .exclude(status=IntegrationConnection.Status.DISCONNECTED)
        .first()
    )


def _credentials() -> Credentials | None:
    from tutortrack.integrations import services as integrations

    conn = connection()
    return integrations.credentials(conn) if conn is not None else None


def _recipient_key(profile: TutorPayProfile, currency: str) -> str:
    raw = f"{currency}:{profile.payee_name}:{profile.bank_details}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _recipient(profile: TutorPayProfile, currency: str, creds: Credentials) -> str:
    """The tutor's Wise recipient, created again when their bank details change."""
    key = _recipient_key(profile, currency)
    if profile.wise_recipient_id and profile.wise_recipient_key == key:
        return profile.wise_recipient_id
    details = banking.loads(profile.bank_details)
    recipient = wise_client().ensure_recipient(
        creds,
        currency=currency,
        name=details.get("account_name") or profile.payee_name or profile.tutor.full_name,
        country=profile.bank_country,
        details=details,
        ref=str(profile.tutor_id),
    )
    TutorPayProfile.objects.filter(pk=profile.pk).update(
        wise_recipient_id=recipient, wise_recipient_key=key
    )
    return str(recipient)


def _apply(payout: Payout, result: TransferResult) -> bool:
    """Record a Wise result on the payout; True when it settled (paid or failed)."""
    from . import services

    if payout.status not in (Payout.Status.PENDING, Payout.Status.PROCESSING):
        return False
    if result.status == "paid":
        services._mark_payout_paid(payout, reference=result.ref, provider_ref=result.ref)
        return True
    if result.status == "failed":
        services.fail_payout(
            payout, reason=_("Wise couldn't pay this (%(state)s).") % {"state": result.message}
        )
        return True
    if payout.status != Payout.Status.PROCESSING or payout.provider_ref != result.ref:
        Payout.objects.filter(pk=payout.pk).update(
            status=Payout.Status.PROCESSING, provider_ref=result.ref
        )
    return False


def send(pay_run: PayRun) -> int:
    """Send every pending Wise payout of the run; returns how many were sent."""
    from . import services

    pending = list(
        pay_run.payouts.select_related("tutor").filter(
            status=Payout.Status.PENDING, method=PayMethod.WISE
        )
    )
    if not pending:
        return 0
    creds = _credentials()
    sent = 0
    source = str(get_setting("payroll.wise_source_currency") or "").upper()
    for payout in pending:
        profile = services.profile_for(payout.tutor)
        if creds is None:
            services.fail_payout(payout, reason=_("Wise isn't connected."))
            continue
        if not profile.bank_details:
            services.fail_payout(payout, reason=_("No bank details."))
            continue
        try:
            recipient = _recipient(profile, payout.currency, creds)
            result = wise_client().transfer(
                creds,
                recipient,
                amount=payout.amount,
                source_currency=source or payout.currency,
                reference=pay_run.number,
                idempotency_key=f"payout-{payout.pk}",
            )
        except ProviderError as exc:
            services.fail_payout(payout, reason=str(exc)[:300])
            continue
        if result.ref:
            routes.remember(PROVIDER, result.ref)
        _apply(payout, result)
        sent += 1
    return sent


def refresh(pay_run: PayRun) -> int:
    """Ask Wise about each processing transfer (the daily settle check); returns how many
    settled."""
    processing = list(
        pay_run.payouts.select_related("tutor").filter(
            status=Payout.Status.PROCESSING, method=PayMethod.WISE
        )
    )
    if not processing:
        return 0
    creds = _credentials()
    if creds is None:
        return 0
    settled = 0
    for payout in processing:
        try:
            result = wise_client().status(creds, payout.provider_ref)
        except ProviderError:
            logger.info("payroll.wise_status_unavailable", payout=str(payout.pk))
            continue
        with transaction.atomic():
            if _apply(payout, result):
                settled += 1
    return settled


def handle_webhook(body: bytes, signature: str) -> bool:
    """``transfers#state-change``: verify, route to the organisation, apply and signal the
    pay run. Returns False when the signature is wrong; unknown transfers are ignored."""
    from .payouts.wise import map_state, verify_signature

    if not verify_signature(body, signature):
        return False
    try:
        event: dict[str, Any] = json.loads(body or b"{}")
    except ValueError:
        return False
    if event.get("event_type") != "transfers#state-change":
        return True
    data = event.get("data") or {}
    transfer_id = str((data.get("resource") or {}).get("id", ""))
    state = str(data.get("current_state", ""))
    organisation_id = routes.organisation_for(PROVIDER, transfer_id) if transfer_id else None
    if organisation_id is None:
        return True
    with tenant_context(organisation_id), transaction.atomic():
        payout = (
            Payout.objects.select_for_update()
            .select_related("tutor")
            .filter(method=PayMethod.WISE, provider_ref=transfer_id)
            .first()
        )
        if payout is None:
            return True
        if _apply(payout, TransferResult(map_state(state), ref=transfer_id, message=state)):
            from . import services

            services._signal(payout.pay_run, "settled")
    return True
