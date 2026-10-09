"""Payments writes (E11). Money reaches the client ledger only through billing's services
(``ledger.post`` + ``allocate_payment``); providers are called with idempotency keys
derived from our own record ids."""

from __future__ import annotations

import contextlib
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext as _

from tutortrack.billing import ledger
from tutortrack.billing import services as billing
from tutortrack.billing.models import ClientLedgerEntry, Invoice, PaymentRequest
from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict
from tutortrack.core.money import Money, sum_money
from tutortrack.core.time import now
from tutortrack.people.models import Client
from tutortrack.tenancy.settings_service import get_setting

from . import events
from .models import (
    AccountRoute,
    AutoPayConsent,
    Dispute,
    Payment,
    PaymentAllocation,
    PaymentAttempt,
    PaymentMethod,
    Provider,
    ProviderAccount,
    ProviderCustomer,
    ProviderPayout,
    ProviderWebhookEvent,
    Refund,
    SetupLink,
)
from .providers import ChargeResult, MethodDetails, ProviderError, get_provider


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def _provider_failed(exc: ProviderError) -> BusinessRuleViolation:
    return BusinessRuleViolation(
        _("The payment provider refused: %(error)s") % {"error": exc}, extra={"code": "provider"}
    )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tenant_url(path: str) -> str:
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    return f"https://{org.slug}.{settings.TENANT_BASE_DOMAIN}{path}"


# --- provider accounts (T01/T02) ----------------------------------------------------------------


def account_for(branch_id: Any = None) -> ProviderAccount | None:
    """The live Stripe account for a branch (its own, else the organisation default)."""
    live = ProviderAccount.objects.exclude(status=ProviderAccount.Status.DISCONNECTED).filter(
        provider=Provider.STRIPE
    )
    if branch_id:
        own = live.filter(branch_id=branch_id).first()
        if own is not None:
            return own
    return live.filter(branch__isnull=True).first()


def active_account_for(branch_id: Any = None) -> ProviderAccount:
    account = account_for(branch_id)
    if account is None or account.status != ProviderAccount.Status.ACTIVE:
        raise BusinessRuleViolation(
            _("Online payments aren't set up yet."), extra={"code": "payments_not_connected"}
        )
    return account


@dataclass(frozen=True)
class Onboarding:
    account: ProviderAccount
    url: str


@transaction.atomic
def connect_stripe(*, branch: Any = None, user: Any = None, email: str = "") -> Onboarding:
    """Start (or resume) Stripe Connect onboarding; returns the provider's onboarding link."""
    from tutortrack.tenancy.models import Organisation

    provider = get_provider("stripe")
    account = (
        ProviderAccount.objects.exclude(status=ProviderAccount.Status.DISCONNECTED)
        .filter(provider=Provider.STRIPE, branch=branch)
        .first()
    )
    if account is None:
        org = Organisation.objects.get(pk=require_organisation_id())
        try:
            ref = provider.create_account(country=org.country, email=email or "")
        except ProviderError as exc:
            raise _provider_failed(exc) from exc
        account = ProviderAccount.objects.create(
            provider=Provider.STRIPE, branch=branch, account_ref=ref
        )
        AccountRoute.objects.update_or_create(
            provider=Provider.STRIPE,
            account_ref=ref,
            defaults={"organisation_id": account.organisation_id},
        )
        audit.record_create(account)
    try:
        url = provider.onboarding_link(
            account.account_ref,
            return_url=tenant_url("/settings/payments?connected=1"),
            refresh_url=tenant_url("/settings/payments?refresh=1"),
        )
    except ProviderError as exc:
        raise _provider_failed(exc) from exc
    return Onboarding(account, url)


@transaction.atomic
def refresh_account(account: ProviderAccount) -> ProviderAccount:
    try:
        state = get_provider(account.provider).account_state(account.account_ref)
    except ProviderError as exc:
        raise _provider_failed(exc) from exc
    return apply_account_state(
        account,
        charges_enabled=state.charges_enabled,
        payouts_enabled=state.payouts_enabled,
        requirements=state.requirements,
        default_currency=state.default_currency,
    )


def apply_account_state(
    account: ProviderAccount,
    *,
    charges_enabled: bool,
    payouts_enabled: bool,
    requirements: list[str],
    default_currency: str = "",
) -> ProviderAccount:
    if account.status == ProviderAccount.Status.DISCONNECTED:
        return account
    was_active = account.status == ProviderAccount.Status.ACTIVE
    with audit.track(account, action="refresh"):
        account.charges_enabled = charges_enabled
        account.payouts_enabled = payouts_enabled
        account.requirements = requirements
        if default_currency:
            account.default_currency = default_currency.upper()
        if charges_enabled:
            account.status = (
                ProviderAccount.Status.RESTRICTED if requirements else ProviderAccount.Status.ACTIVE
            )
            account.connected_at = account.connected_at or now()
        else:
            account.status = (
                ProviderAccount.Status.RESTRICTED
                if account.connected_at
                else ProviderAccount.Status.PENDING
            )
        account.save()
    if account.status == ProviderAccount.Status.ACTIVE and not was_active:
        publish(events.ProviderAccountConnected(subject_id=account.pk, provider=account.provider))
    if requirements:
        publish(
            events.ProviderAccountRequirementsDue(subject_id=account.pk, requirements=requirements)
        )
    return account


@transaction.atomic
def disconnect(account: ProviderAccount, *, user: Any = None) -> ProviderAccount:
    """Blocked while clients pay automatically from methods on this account (FR-11-1)."""
    on_autopay = PaymentMethod.objects.filter(
        account=account, status=PaymentMethod.Status.ACTIVE, is_default=True, client__auto_pay=True
    )
    if on_autopay.exists():
        raise BusinessRuleViolation(
            _("%(count)s clients pay automatically with this account; move them first.")
            % {"count": on_autopay.count()},
            extra={"code": "autopay_clients"},
        )
    with audit.track(account, action="disconnect"):
        account.status = ProviderAccount.Status.DISCONNECTED
        account.disconnected_at = now()
        account.save()
    publish(events.ProviderAccountDisconnected(subject_id=account.pk, provider=account.provider))
    return account


def customer_for(client: Client, account: ProviderAccount) -> str:
    existing = ProviderCustomer.objects.filter(client=client, account=account).first()
    if existing is not None:
        return existing.ref
    contact = client.billing_contact or client.primary_contact
    try:
        ref = get_provider(account.provider).create_customer(
            account.account_ref,
            name=client.display_name,
            email=contact.email if contact else "",
            ref=str(client.pk),
        )
    except ProviderError as exc:
        raise _provider_failed(exc) from exc
    ProviderCustomer.objects.create(client=client, account=account, ref=ref)
    return ref


# --- payment methods, setup links and auto-pay consent (T03) ------------------------------------


@transaction.atomic
def create_setup_link(client: Client, *, user: Any = None, days: int = 14) -> str:
    """A link the client opens to add a card or mandate (staff never type card numbers)."""
    active_account_for(client.branch_id)
    token = secrets.token_urlsafe(32)
    link = SetupLink.objects.create(
        client=client,
        token_hash=hash_token(token),
        expires_at=now() + timedelta(days=days),
        created_by=user,
    )
    audit.record_create(link)
    return tenant_url(f"/pay/setup/{token}")


def setup_link(token: str) -> SetupLink | None:
    link = (
        SetupLink.objects.select_related("client")
        .filter(token_hash=hash_token(token), used_at__isnull=True, expires_at__gt=now())
        .first()
    )
    return link


def consent_text() -> str:
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    return str(get_setting("payments.autopay_consent_text")).replace("{organisation}", org.name)


def start_setup(client: Client) -> dict[str, Any]:
    account = active_account_for(client.branch_id)
    customer = customer_for(client, account)
    try:
        intent = get_provider(account.provider).create_setup_intent(
            account.account_ref, customer=customer
        )
    except ProviderError as exc:
        raise _provider_failed(exc) from exc
    return {
        "publishable_key": get_provider(account.provider).publishable_key,
        "account": account.account_ref,
        "client_secret": intent.client_secret,
        "intent": intent.ref,
        "consent_text": consent_text(),
    }


def save_method(
    client: Client, account: ProviderAccount, details: MethodDetails, *, make_default: bool = True
) -> PaymentMethod:
    method, created = PaymentMethod.objects.get_or_create(
        client=client,
        account=account,
        provider_ref=details.ref,
        defaults={
            "type": details.type,
            "brand": details.brand,
            "last4": details.last4,
            "exp_month": details.exp_month,
            "exp_year": details.exp_year,
            "mandate_status": details.mandate_status,
        },
    )
    if method.status != PaymentMethod.Status.ACTIVE:
        method.status = PaymentMethod.Status.ACTIVE
        method.save(update_fields=["status", "updated_at"])
    has_default = PaymentMethod.objects.filter(
        client=client, is_default=True, status=PaymentMethod.Status.ACTIVE
    ).exclude(pk=method.pk)
    if make_default or not has_default.exists():
        set_default_method(method)
    if created:
        audit.record_create(method)
        publish(
            events.PaymentMethodAdded(
                subject_id=method.pk, client_id=str(client.pk), type=method.type
            )
        )
    return method


@transaction.atomic
def complete_setup(
    link: SetupLink,
    intent_ref: str,
    *,
    autopay: bool = False,
    ip_address: str | None = None,
    user_agent: str = "",
) -> PaymentMethod:
    link = SetupLink.objects.select_for_update().select_related("client").get(pk=link.pk)
    if link.used_at:
        raise BusinessRuleViolation(_("This link has already been used."))
    client = link.client
    account = active_account_for(client.branch_id)
    try:
        details = get_provider(account.provider).setup_result(account.account_ref, intent_ref)
    except ProviderError as exc:
        raise _provider_failed(exc) from exc
    if details is None:
        raise BusinessRuleViolation(_("The payment method hasn't been confirmed yet."))
    method = save_method(client, account, details)
    if autopay:
        give_consent(client, method, ip_address=ip_address, user_agent=user_agent)
    link.used_at = now()
    link.save(update_fields=["used_at", "updated_at"])
    return method


def give_consent(
    client: Client, method: PaymentMethod | None, *, ip_address: str | None, user_agent: str
) -> AutoPayConsent:
    from tutortrack.people import services as people

    consent = AutoPayConsent.objects.create(
        client=client,
        payment_method=method,
        text_version=hashlib.sha256(consent_text().encode()).hexdigest()[:12],
        text=consent_text(),
        ip_address=ip_address,
        user_agent=user_agent[:300],
        given_at=now(),
    )
    audit.record_create(consent)
    people.update_client(client, auto_pay=True)
    return consent


@transaction.atomic
def set_autopay(client: Client, enabled: bool, *, user: Any = None) -> Client:
    """Staff can switch auto-pay off; switching it on needs the client's own consent."""
    from tutortrack.people import services as people

    if enabled:
        consent = AutoPayConsent.objects.filter(client=client, withdrawn_at__isnull=True).first()
        if consent is None:
            raise BusinessRuleViolation(
                _("The client must agree to auto-pay themselves (send them a setup link)."),
                extra={"code": "consent_required"},
            )
        if not default_method(client):
            raise BusinessRuleViolation(_("The client has no saved payment method."))
    else:
        AutoPayConsent.objects.filter(client=client, withdrawn_at__isnull=True).update(
            withdrawn_at=now()
        )
    people.update_client(client, auto_pay=enabled)
    return client


def default_method(client: Client) -> PaymentMethod | None:
    return (
        PaymentMethod.objects.select_related("account")
        .filter(client=client, is_default=True, status=PaymentMethod.Status.ACTIVE)
        .exclude(account__status=ProviderAccount.Status.DISCONNECTED)
        .first()
    )


@transaction.atomic
def set_default_method(method: PaymentMethod) -> PaymentMethod:
    """Choosing the default is how a client moves between providers or methods (FR-11-2)."""
    PaymentMethod.objects.filter(client_id=method.client_id, is_default=True).exclude(
        pk=method.pk
    ).update(is_default=False)
    if not method.is_default:
        method.is_default = True
        method.save(update_fields=["is_default", "updated_at"])
    return method


@transaction.atomic
def remove_method(method: PaymentMethod, *, user: Any = None) -> PaymentMethod:
    from tutortrack.people import services as people

    with contextlib.suppress(ProviderError):  # already gone there: still remove it here
        get_provider(method.account.provider).detach_method(
            method.account.account_ref, method.provider_ref
        )
    with audit.track(method, action="remove"):
        method.status = PaymentMethod.Status.REMOVED
        method.is_default = False
        method.save(update_fields=["status", "is_default", "updated_at"])
    client = method.client
    others = PaymentMethod.objects.filter(client=client, status=PaymentMethod.Status.ACTIVE)
    if others.exists() and not others.filter(is_default=True).exists():
        newest = others.order_by("-created_at").first()
        if newest is not None:
            set_default_method(newest)
    elif not others.exists() and client.auto_pay:
        people.update_client(client, auto_pay=False)
    publish(events.PaymentMethodRemoved(subject_id=method.pk, client_id=str(client.pk)))
    return method


# --- payments and allocation (T04) --------------------------------------------------------------


def allocated(payment: Payment) -> Money:
    total = payment.allocations.aggregate(t=Sum("amount_amount"))["t"] or Decimal(0)
    return Money(total, payment.currency).round_to_minor()


def unallocated(payment: Payment) -> Money:
    """What is left of a payment for invoices (refunds come out of it first)."""
    return payment.amount - payment.refunded - allocated(payment)


def _post(payment: Payment, user: Any = None) -> None:
    ledger.post(
        payment.client,
        ClientLedgerEntry.Type.PAYMENT,
        -payment.amount,
        ref=payment,
        description=_("Payment %(ref)s")
        % {"ref": payment.reference or payment.get_method_display()},
        occurred_at=payment.received_at,
        user=user,
    )


def _allocate_one(payment: Payment, invoice: Invoice, amount: Money) -> None:
    if invoice.client_id != payment.client_id:
        raise _invalid("allocations", _("Allocate only to this client's invoices."))
    if invoice.currency != payment.currency:
        raise _invalid("allocations", _("The invoice is in a different currency."))
    billing.allocate_payment(invoice, amount)
    PaymentAllocation.objects.create(
        payment=payment, invoice=invoice, currency=payment.currency, amount=amount
    )


def allocate(payment: Payment, allocations: list[tuple[Invoice, Money]]) -> None:
    left = unallocated(payment)
    total = sum_money((a for _i, a in allocations), payment.currency)
    if total > left:
        raise _invalid("allocations", _("That's more than is left of the payment."))
    for invoice, amount in allocations:
        if amount.is_positive():
            _allocate_one(payment, invoice, amount)


def auto_allocate(payment: Payment) -> list[Invoice]:
    """Oldest open invoices first; anything left becomes client credit (FR-11-6)."""
    paid = []
    for invoice in Invoice.objects.filter(
        client_id=payment.client_id, currency=payment.currency, status__in=Invoice.OPEN
    ).order_by("due_date", "issue_date", "created_at"):
        left = unallocated(payment)
        if not left.is_positive():
            break
        amount = min(left, invoice.balance_due)
        if amount.is_positive():
            _allocate_one(payment, invoice, amount)
            paid.append(invoice)
    return paid


def _finish(payment: Payment, invoice_ids: list[str]) -> None:
    publish(
        events.PaymentSucceeded(
            subject_id=payment.pk,
            client_id=str(payment.client_id),
            amount=payment.amount.to_dict(),
            method=payment.method,
            invoice_ids=invoice_ids,
        ),
        branch_id=payment.branch_id,
    )
    if get_setting("payments.send_receipts"):
        org_id, payment_id = payment.organisation_id, payment.pk
        transaction.on_commit(lambda: _receipt_later(org_id, payment_id))


def _receipt_later(organisation_id: Any, payment_id: Any) -> None:
    from .tasks import send_receipt

    send_receipt.delay(organisation_id=str(organisation_id), payment_id=str(payment_id))


def _book(
    payment: Payment,
    *,
    invoice: Invoice | None,
    allocations: list[tuple[Invoice, Money]] | None,
    user: Any = None,
) -> None:
    """Money received: ledger, then allocation (or the payment request's credit)."""
    if payment.payment_request_id:
        billing.pay_payment_request(
            payment.payment_request,  # type: ignore[arg-type]
            payment.amount,
            user=user,
            occurred_at=payment.received_at,
        )
        _finish(payment, [])
        return
    _post(payment, user)
    if allocations is not None:
        allocate(payment, allocations)
        ids = [str(i.pk) for i, _a in allocations]
    elif invoice is not None and invoice.is_open:
        amount = min(payment.amount, invoice.balance_due)
        _allocate_one(payment, invoice, amount)
        ids = [str(invoice.pk)]
        if get_setting("billing.auto_apply_credit"):
            ids += [str(i.pk) for i in auto_allocate(payment)]
    else:
        ids = [str(i.pk) for i in auto_allocate(payment)]
    _finish(payment, ids)


@transaction.atomic
def record_manual_payment(
    *,
    client: Client,
    amount: Money,
    method: str,
    received_at: datetime | None = None,
    reference: str = "",
    notes: str = "",
    allocations: list[tuple[Invoice, Money]] | None = None,
    payment_request: PaymentRequest | None = None,
    user: Any = None,
) -> Payment:
    """Bank transfer, cash, cheque or other (FR-11-5). Without ``allocations`` the money
    pays the oldest open invoices; the rest is credit."""
    if not amount.is_positive():
        raise _invalid("amount", _("Record a positive amount."))
    if method not in Payment.Method.values or method == Payment.Method.CARD:
        raise _invalid("method", _("Card payments are taken through the payment page."))
    if payment_request is not None and payment_request.client_id != client.pk:
        raise _invalid("payment_request", _("That request is for another client."))
    payment = Payment.objects.create(
        client=client,
        branch_id=client.branch_id,
        currency=amount.currency,
        amount=amount.round_to_minor(),
        method=method,
        provider=Provider.MANUAL,
        status=Payment.Status.SUCCEEDED,
        source=Payment.Source.MANUAL,
        received_at=received_at or now(),
        reference=reference[:120],
        notes=notes,
        payment_request=payment_request,
        recorded_by=user,
    )
    audit.record_create(payment)
    _book(payment, invoice=None, allocations=allocations, user=user)
    return payment


@transaction.atomic
def reallocate(
    payment: Payment, allocations: list[tuple[Invoice, Money]], *, user: Any = None
) -> Payment:
    """Replace a payment's allocations (audited, FR-11-6)."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status not in {Payment.Status.SUCCEEDED, Payment.Status.PARTIALLY_REFUNDED}:
        raise BusinessRuleViolation(_("Only received payments can be allocated."))
    before = {str(k): str(v) for k, v in _by_invoice(payment).items()}
    for invoice_id, amount in _by_invoice(payment).items():
        if amount.is_positive():
            invoice = Invoice.objects.get(pk=invoice_id)
            billing.unallocate_payment(invoice, amount)
            PaymentAllocation.objects.create(
                payment=payment, invoice=invoice, currency=payment.currency, amount=-amount
            )
    allocate(payment, allocations)
    audit.record(
        payment,
        "reallocate",
        {"allocations": [before, {str(i.pk): str(a.amount) for i, a in allocations}]},
    )
    return payment


def _by_invoice(payment: Payment) -> dict[Any, Money]:
    out: dict[Any, Money] = {}
    for row in payment.allocations.all():
        out[row.invoice_id] = out.get(row.invoice_id, Money.zero(payment.currency)) + row.amount
    return out


def _method_kind(details_type: str) -> str:
    return Payment.Method.CARD if details_type == "card" else Payment.Method.DIRECT_DEBIT


@transaction.atomic
def record_provider_payment(
    *,
    account: ProviderAccount,
    client: Client,
    amount: Money,
    provider_ref: str,
    method_type: str = "card",
    payment_method: PaymentMethod | None = None,
    source: str = Payment.Source.PAY_PAGE,
    invoice: Invoice | None = None,
    payment_request: PaymentRequest | None = None,
    fee: Money | None = None,
) -> Payment:
    """A provider payment that succeeded (idempotent on the provider reference)."""
    existing = Payment.objects.filter(provider=account.provider, provider_ref=provider_ref).first()
    if existing is not None:
        if existing.status == Payment.Status.PENDING:
            return confirm_pending(existing, fee=fee)
        return existing
    payment = Payment.objects.create(
        client=client,
        branch_id=client.branch_id,
        currency=amount.currency,
        amount=amount,
        fee=fee,
        net=(amount - fee) if fee else None,
        method=_method_kind(method_type),
        provider=account.provider,
        account=account,
        provider_ref=provider_ref,
        payment_method=payment_method,
        status=Payment.Status.SUCCEEDED,
        source=source,
        received_at=now(),
        reference=provider_ref,
        payment_request=payment_request,
    )
    _book(payment, invoice=invoice, allocations=None)
    return payment


def _pending(
    *,
    account: ProviderAccount,
    invoice: Invoice,
    method: PaymentMethod,
    result: ChargeResult,
    amount: Money,
) -> Payment:
    payment, _created = Payment.objects.get_or_create(
        provider=account.provider,
        provider_ref=result.ref,
        defaults={
            "client_id": invoice.client_id,
            "branch_id": invoice.branch_id,
            "currency": amount.currency,
            "amount": amount,
            "method": _method_kind(method.type),
            "account": account,
            "payment_method": method,
            "status": Payment.Status.PENDING,
            "source": Payment.Source.AUTO_PAY,
            "reference": result.ref,
        },
    )
    publish(
        events.PaymentPending(
            subject_id=payment.pk, client_id=str(payment.client_id), amount=amount.to_dict()
        )
    )
    return payment


@transaction.atomic
def confirm_pending(payment: Payment, *, fee: Money | None = None) -> Payment:
    """A pending debit was confirmed: now it pays the invoice it was collected for."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != Payment.Status.PENDING:
        return payment
    payment.status = Payment.Status.SUCCEEDED
    payment.received_at = now()
    if fee is not None:
        payment.fee, payment.net = fee, payment.amount - fee
    payment.save()
    attempt = PaymentAttempt.objects.filter(provider_ref=payment.provider_ref).first()
    _book(payment, invoice=attempt.invoice if attempt else None, allocations=None)
    if attempt is not None:
        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            status=PaymentAttempt.Status.SUCCEEDED, payment=payment
        )
    return payment


@transaction.atomic
def fail_pending(payment: Payment, *, code: str, message: str) -> Payment:
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != Payment.Status.PENDING:
        return payment
    payment.status = Payment.Status.FAILED
    payment.failure_code, payment.failure_message = code[:60], message[:300]
    payment.save()
    PaymentAttempt.objects.filter(provider_ref=payment.provider_ref).update(
        status=PaymentAttempt.Status.FAILED, failure_code=code[:60], failure_message=message[:300]
    )
    return payment


# --- auto-pay collection (T06; called by PaymentCollectionWorkflow) -----------------------------


def should_autopay(invoice_id: Any) -> bool:
    invoice = Invoice.objects.select_related("client").filter(pk=invoice_id).first()
    if invoice is None or not invoice.is_open or not invoice.balance_due.is_positive():
        return False
    if not invoice.client.auto_pay:
        return False
    method = default_method(invoice.client)
    return bool(method and method.account.status == ProviderAccount.Status.ACTIVE)


def collection_running(invoice: Invoice) -> bool:
    from tutortrack.core.models import WorkflowLink

    from .processes import collect_workflow_id

    wid = collect_workflow_id(invoice.organisation_id, invoice.pk)
    return WorkflowLink.objects.filter(workflow_id=wid, status="running").exists()


def start_collection(invoice: Invoice) -> None:
    """``POST /invoices/{id}/collect``: charge the default method now. The workflow is the
    invoice's collection lock: a second attempt while one is in flight is refused."""
    from tutortrack.core.workflows import start_now

    from .processes import CollectInput, PaymentCollectionWorkflow, collect_workflow_id

    if collection_running(invoice):
        raise Conflict(
            _("A payment is already being collected for this invoice."),
            extra={"code": "collection_in_progress"},
        )
    if not invoice.is_open or not invoice.balance_due.is_positive():
        raise BusinessRuleViolation(_("Nothing is owed on this invoice."))
    if default_method(invoice.client) is None:
        raise BusinessRuleViolation(_("The client has no saved payment method."))
    run = start_now(
        PaymentCollectionWorkflow,
        CollectInput(organisation_id=str(invoice.organisation_id), invoice_id=str(invoice.pk)),
        id=collect_workflow_id(invoice.organisation_id, invoice.pk),
        subject=("invoice", str(invoice.pk)),
        branch_id=invoice.branch_id,
    )
    if run is None:
        raise Conflict(
            _("A payment is already being collected for this invoice."),
            extra={"code": "collection_in_progress"},
        )


def attempt_collection(invoice_id: Any, number: int, idempotency_key: str) -> str:
    """One collection attempt: ``succeeded``, ``processing``, ``action_required``,
    ``failed``, ``settled`` (nothing owed) or ``no_method``."""
    previous = PaymentAttempt.objects.filter(idempotency_key=idempotency_key).first()
    if previous is not None:  # the activity is being retried
        return str(previous.status)
    invoice = Invoice.objects.select_related("client").filter(pk=invoice_id).first()
    if invoice is None or not invoice.is_open or not invoice.balance_due.is_positive():
        return "settled"
    method = default_method(invoice.client)
    if method is None or method.account.status != ProviderAccount.Status.ACTIVE:
        return "no_method"
    account = method.account
    customer = customer_for(invoice.client, account)
    amount = invoice.balance_due
    result = get_provider(account.provider).charge(
        account.account_ref,
        customer=customer,
        method=method.provider_ref,
        amount=amount,
        metadata={"invoice_id": str(invoice.pk), "organisation_id": str(invoice.organisation_id)},
        idempotency_key=idempotency_key,
    )
    status = {
        "succeeded": PaymentAttempt.Status.SUCCEEDED,
        "processing": PaymentAttempt.Status.PROCESSING,
        "requires_action": PaymentAttempt.Status.ACTION_REQUIRED,
    }.get(result.status, PaymentAttempt.Status.FAILED)
    with transaction.atomic():
        attempt = PaymentAttempt.objects.create(
            invoice=invoice,
            payment_method=method,
            number=number,
            idempotency_key=idempotency_key,
            status=status,
            provider_ref=result.ref,
            failure_code=result.failure_code[:60],
            failure_message=result.failure_message[:300],
        )
        if status == PaymentAttempt.Status.SUCCEEDED:
            payment = record_provider_payment(
                account=account,
                client=invoice.client,
                amount=amount,
                provider_ref=result.ref,
                method_type=method.type,
                payment_method=method,
                source=Payment.Source.AUTO_PAY,
                invoice=invoice,
                fee=result.fee,
            )
            PaymentAttempt.objects.filter(pk=attempt.pk).update(payment=payment)
        elif status == PaymentAttempt.Status.PROCESSING:
            payment = _pending(
                account=account, invoice=invoice, method=method, result=result, amount=amount
            )
            PaymentAttempt.objects.filter(pk=attempt.pk).update(payment=payment)
    return str(status)


def method_is_debit(invoice_id: Any) -> bool:
    invoice = Invoice.objects.select_related("client").filter(pk=invoice_id).first()
    method = default_method(invoice.client) if invoice else None
    return bool(method and method.is_debit)


@transaction.atomic
def collection_failed(
    invoice_id: Any, number: int, *, final: bool, dedupe_key: str | None = None
) -> None:
    from tutortrack.people import services as people

    invoice = Invoice.objects.select_related("client").filter(pk=invoice_id).first()
    if invoice is None:
        return
    attempt = PaymentAttempt.objects.filter(invoice=invoice, number=number).first()
    publish(
        events.PaymentFailed(
            subject_id=invoice.pk,
            client_id=str(invoice.client_id),
            attempt=number,
            failure_code=attempt.failure_code if attempt else "",
            final=final,
        ),
        branch_id=invoice.branch_id,
        dedupe_key=dedupe_key,
    )
    if final and get_setting("payments.pause_autopay_after_failure") and invoice.client.auto_pay:
        people.update_client(invoice.client, auto_pay=False)


# --- refunds and disputes (T07) -----------------------------------------------------------------


def _credit_note_for(invoice: Invoice, amount: Money, reason: str, user: Any) -> Any:
    lines = []
    left = amount
    for line in invoice.lines.order_by("-position"):
        if not left.is_positive():
            break
        take = min(left, line.gross - line.credited)
        if take.is_positive():
            lines.append({"line": line, "amount": take})
            left = left - take
    if not lines:
        return None
    return billing.create_credit_note(
        invoice, reason=reason, application="invoice", lines=lines, user=user
    )


@transaction.atomic
def refund_payment(
    payment: Payment,
    *,
    amount: Money | None = None,
    reason: str,
    credit_note: bool = False,
    user: Any = None,
) -> Refund:
    """Refund to the original method (card) or record a manual refund (FR-11-7). Unused
    credit is refunded first; then the money comes off the most recent invoices, which a
    credit note can cancel (``credit_note``) or leave owing."""
    payment = (
        Payment.objects.select_for_update(of=("self",))
        .select_related("account", "client")
        .get(pk=payment.pk)
    )
    if payment.status not in {Payment.Status.SUCCEEDED, Payment.Status.PARTIALLY_REFUNDED}:
        raise BusinessRuleViolation(_("Only received payments can be refunded."))
    if not reason.strip():
        raise _invalid("reason", _("Give a reason."))
    refundable = payment.amount - payment.refunded
    amount = (amount or refundable).round_to_minor()
    if not amount.is_positive() or amount > refundable:
        raise _invalid("amount", _("You can refund at most %(max)s.") % {"max": refundable})
    refund = Refund.objects.create(
        payment=payment, currency=payment.currency, amount=amount, reason=reason[:300],
        created_by=user,
    )  # fmt: skip
    if payment.provider != Provider.MANUAL and payment.account is not None:
        try:
            refund.provider_ref = get_provider(payment.provider).refund(
                payment.account.account_ref,
                payment_ref=payment.provider_ref,
                amount=amount,
                idempotency_key=f"refund-{refund.pk}",
            )
        except ProviderError as exc:
            raise _provider_failed(exc) from exc
    from_credit = min(amount, max(unallocated(payment), Money.zero(payment.currency)))
    from_invoices = amount - from_credit
    payment.refunded = payment.refunded + amount
    payment.status = (
        Payment.Status.REFUNDED
        if payment.refunded >= payment.amount
        else Payment.Status.PARTIALLY_REFUNDED
    )
    payment.save(update_fields=["refunded_amount", "status", "updated_at"])
    for invoice_id, paid in sorted(
        _by_invoice(payment).items(), key=lambda kv: str(kv[0]), reverse=True
    ):
        if not from_invoices.is_positive():
            break
        take = min(paid, from_invoices)
        if not take.is_positive():
            continue
        invoice = Invoice.objects.get(pk=invoice_id)
        billing.unallocate_payment(invoice, take)
        PaymentAllocation.objects.create(
            payment=payment, invoice=invoice, currency=payment.currency, amount=-take
        )
        if credit_note:
            refund.credit_note = _credit_note_for(invoice, take, reason, user)
        from_invoices = from_invoices - take
    ledger.post(
        payment.client,
        ClientLedgerEntry.Type.REFUND,
        amount,
        ref=refund,
        description=_("Refund: %(reason)s") % {"reason": reason[:200]},
        user=user,
    )
    refund.status = Refund.Status.SUCCEEDED
    refund.save()
    audit.record_create(refund)
    publish(
        events.PaymentRefunded(
            subject_id=payment.pk,
            client_id=str(payment.client_id),
            amount=amount.to_dict(),
            refund_id=str(refund.pk),
        ),
        branch_id=payment.branch_id,
    )
    return refund


@transaction.atomic
def open_dispute(
    payment: Payment, *, ref: str, amount: Money, reason: str, due: datetime | None
) -> Dispute:
    dispute, created = Dispute.objects.get_or_create(
        provider_ref=ref,
        defaults={
            "payment": payment,
            "currency": amount.currency,
            "amount": amount,
            "reason": reason[:60],
            "status": Dispute.Status.NEEDS_RESPONSE,
            "evidence_due_by": due,
        },
    )
    if created:
        Payment.objects.filter(pk=payment.pk).update(status=Payment.Status.DISPUTED)
        publish(
            events.PaymentDisputed(
                subject_id=payment.pk,
                client_id=str(payment.client_id),
                amount=amount.to_dict(),
                dispute_id=str(dispute.pk),
                evidence_due_by=due.isoformat() if due else None,
            ),
            branch_id=payment.branch_id,
        )
    return dispute


@transaction.atomic
def close_dispute(dispute: Dispute, *, won: bool) -> Dispute:
    """On loss the money is reversed on the ledger and the invoice reopens (FR-11-8)."""
    dispute = Dispute.objects.select_for_update().select_related("payment").get(pk=dispute.pk)
    if dispute.status in {Dispute.Status.WON, Dispute.Status.LOST}:
        return dispute
    payment = dispute.payment
    dispute.status = Dispute.Status.WON if won else Dispute.Status.LOST
    dispute.closed_at = now()
    dispute.save()
    if won:
        payment.status = Payment.Status.SUCCEEDED
        payment.save(update_fields=["status", "updated_at"])
    else:
        left = dispute.amount - max(unallocated(payment), Money.zero(payment.currency))
        for invoice_id, paid in _by_invoice(payment).items():
            if not left.is_positive():
                break
            take = min(paid, left)
            if take.is_positive():
                invoice = Invoice.objects.get(pk=invoice_id)
                billing.unallocate_payment(invoice, take)
                PaymentAllocation.objects.create(
                    payment=payment, invoice=invoice, currency=payment.currency, amount=-take
                )
                left = left - take
        ledger.post(
            payment.client,
            ClientLedgerEntry.Type.REFUND,
            dispute.amount,
            ref=dispute,
            description=_("Chargeback"),
        )
        payment.refunded = min(payment.amount, payment.refunded + dispute.amount)
        payment.status = Payment.Status.REFUNDED
        payment.save(update_fields=["refunded_amount", "status", "updated_at"])
    publish(
        events.PaymentDisputeClosed(
            subject_id=payment.pk,
            client_id=str(payment.client_id),
            amount=dispute.amount.to_dict(),
            dispute_id=str(dispute.pk),
            outcome=dispute.status,
        ),
        branch_id=payment.branch_id,
    )
    return dispute


# --- the pay page (T05) -------------------------------------------------------------------------


def pay_target(token: str) -> Invoice | PaymentRequest | None:
    if not token or len(token) < 20:
        return None
    invoice = Invoice.objects.select_related("client").filter(pay_token=token).first()
    if invoice is not None and invoice.status != Invoice.Status.DRAFT:
        return invoice
    return PaymentRequest.objects.select_related("client").filter(pay_token=token).first()


def amount_due(target: Invoice | PaymentRequest) -> Money:
    zero = Money.zero(target.currency).round_to_minor()
    if isinstance(target, Invoice):
        return target.balance_due if target.is_open else zero
    if target.status != PaymentRequest.Status.OPEN:
        return zero
    return target.amount - target.amount_paid


def _metadata(target: Invoice | PaymentRequest) -> dict[str, str]:
    key = "invoice_id" if isinstance(target, Invoice) else "payment_request_id"
    return {key: str(target.pk), "organisation_id": str(target.organisation_id)}


def create_pay_intent(
    target: Invoice | PaymentRequest, *, amount: Money | None = None, save_method: bool = False
) -> dict[str, Any]:
    due = amount_due(target)
    if not due.is_positive():
        raise BusinessRuleViolation(_("Nothing is owed."))
    pay = (amount or due).round_to_minor()
    if pay.currency != due.currency or not pay.is_positive() or pay > due:
        raise _invalid("amount", _("Pay up to %(due)s.") % {"due": due})
    if pay != due and not get_setting("payments.allow_partial"):
        raise _invalid("amount", _("Pay the full amount."))
    account = active_account_for(target.branch_id)
    provider = get_provider(account.provider)
    customer = customer_for(target.client, account) if save_method else None
    try:
        intent = provider.create_payment_intent(
            account.account_ref,
            amount=pay,
            customer=customer,
            save_method=save_method,
            metadata=_metadata(target),
            idempotency_key=f"pay-{target.pk}-{pay.to_minor()}-{int(save_method)}-{secrets.token_hex(4)}",
        )
    except ProviderError as exc:
        raise _provider_failed(exc) from exc
    return {
        "publishable_key": provider.publishable_key,
        "account": account.account_ref,
        "client_secret": intent.client_secret,
        "intent": intent.ref,
        "amount": pay,
    }


def confirm_pay_intent(target: Invoice | PaymentRequest, intent_ref: str) -> str:
    """The page tells us the customer finished; we check with the provider (the webhook
    does the same, whichever comes first records the payment)."""
    account = active_account_for(target.branch_id)
    provider = get_provider(account.provider)
    try:
        intent = provider.retrieve_intent(account.account_ref, intent_ref)
    except ProviderError as exc:
        raise _provider_failed(exc) from exc
    if intent.metadata != _metadata(target):
        raise _invalid("intent", _("That payment is for something else."))
    if intent.status != "succeeded" or intent.amount is None:
        return intent.status
    record_intent(account, intent.ref, intent.amount, intent.metadata, intent.payment_method)
    return "succeeded"


@transaction.atomic
def record_intent(
    account: ProviderAccount,
    ref: str,
    amount: Money,
    metadata: dict[str, str],
    method_ref: str = "",
) -> Payment | None:
    """Record a succeeded pay-page payment from its metadata (idempotent)."""
    invoice = request = None
    if metadata.get("invoice_id"):
        invoice = Invoice.objects.select_related("client").filter(pk=metadata["invoice_id"]).first()
    elif metadata.get("payment_request_id"):
        request = (
            PaymentRequest.objects.select_related("client")
            .filter(pk=metadata["payment_request_id"])
            .first()
        )
    target = invoice or request
    if target is None:
        return None
    method = None
    if method_ref:
        provider = get_provider(account.provider)
        try:
            details = provider.method_details(account.account_ref, method_ref)
            method = save_method(target.client, account, details, make_default=False)
        except ProviderError:
            method = None
    try:
        fee = get_provider(account.provider).fee_for(account.account_ref, ref)
    except ProviderError:
        fee = None
    return record_provider_payment(
        account=account,
        client=target.client,
        amount=amount,
        provider_ref=ref,
        method_type=method.type if method else "card",
        payment_method=method,
        invoice=invoice,
        payment_request=request,
        fee=fee,
    )


# --- webhooks (T01) and payouts (T08) -----------------------------------------------------------


def ingest_webhook(
    provider_name: str, payload: bytes, signature: str
) -> ProviderWebhookEvent | None:
    """Verify, route to the organisation and store the raw event; processing is async."""
    from tutortrack.core.context import tenant_context

    event = get_provider(provider_name).parse_webhook(payload, signature)
    route = AccountRoute.objects.filter(provider=provider_name, account_ref=event.account).first()
    if route is None:
        return None  # not one of ours (or a platform-level event we don't use)
    with tenant_context(route.organisation_id), transaction.atomic():
        row, created = ProviderWebhookEvent.objects.get_or_create(
            provider=provider_name,
            event_id=event.id,
            defaults={"type": event.type, "account_ref": event.account, "payload": event.payload},
        )
        if created:
            org_id, row_id = route.organisation_id, row.pk
            transaction.on_commit(lambda: _process_later(org_id, row_id))
    return row


def _process_later(organisation_id: Any, event_id: Any) -> None:
    from .tasks import process_webhook

    process_webhook.delay(organisation_id=str(organisation_id), event_id=str(event_id))


def _money_from(data: dict[str, Any], field: str = "amount") -> Money:
    return Money.from_minor(int(data[field]), str(data["currency"]).upper())


def _signal(workflow_id: str, name: str) -> None:
    from tutortrack.core.models import WorkflowLink
    from tutortrack.core.workflows import signal

    if WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists():
        signal(workflow_id, name)


def process_webhook_event(row: ProviderWebhookEvent) -> None:
    """Apply one stored provider event (idempotent: processed rows are skipped)."""
    if row.processed_at:
        return
    account = ProviderAccount.objects.filter(account_ref=row.account_ref).first()
    data = row.payload["data"]["object"]
    kind = row.type
    with transaction.atomic():
        if account is None:
            pass
        elif kind == "account.updated":
            apply_account_state(
                account,
                charges_enabled=bool(data.get("charges_enabled")),
                payouts_enabled=bool(data.get("payouts_enabled")),
                requirements=list((data.get("requirements") or {}).get("currently_due") or []),
                default_currency=str(data.get("default_currency") or ""),
            )
        elif kind == "payment_intent.succeeded":
            pending = Payment.objects.filter(provider_ref=data["id"]).first()
            if pending is not None:
                confirm_pending(pending)
                _signal_collection(pending, "confirmed")
            else:
                record_intent(
                    account,
                    data["id"],
                    _money_from(data, "amount_received" if "amount_received" in data else "amount"),
                    dict(data.get("metadata") or {}),
                    str(data.get("payment_method") or ""),
                )
        elif kind == "payment_intent.payment_failed":
            pending = Payment.objects.filter(provider_ref=data["id"]).first()
            if pending is not None:
                error = data.get("last_payment_error") or {}
                fail_pending(
                    pending,
                    code=str(error.get("code") or "failed"),
                    message=str(error.get("message") or ""),
                )
                _signal_collection(pending, "failed")
        elif kind == "charge.dispute.created":
            payment = Payment.objects.filter(provider_ref=data.get("payment_intent", "")).first()
            if payment is not None:
                due = (data.get("evidence_details") or {}).get("due_by")
                open_dispute(
                    payment,
                    ref=data["id"],
                    amount=_money_from(data),
                    reason=str(data.get("reason") or ""),
                    due=datetime.fromtimestamp(int(due), tz=now().tzinfo) if due else None,
                )
        elif kind == "charge.dispute.closed":
            dispute = Dispute.objects.filter(provider_ref=data["id"]).first()
            if dispute is not None:
                close_dispute(dispute, won=data.get("status") == "won")
                from .processes import dispute_workflow_id

                _signal(dispute_workflow_id(dispute.organisation_id, dispute.pk), "closed")
        elif kind == "payout.paid":
            payout, created = ProviderPayout.objects.update_or_create(
                provider_ref=data["id"],
                defaults={
                    "account": account,
                    "currency": str(data["currency"]).upper(),
                    "amount": _money_from(data),
                    "status": str(data.get("status") or "paid"),
                    "arrival_date": (
                        datetime.fromtimestamp(int(data["arrival_date"]), tz=now().tzinfo).date()
                        if data.get("arrival_date")
                        else None
                    ),
                },
            )
            if created:
                publish(events.PayoutReceived(subject_id=payout.pk, amount=payout.amount.to_dict()))
        ProviderWebhookEvent.objects.filter(pk=row.pk).update(processed_at=now())


def _signal_collection(payment: Payment, name: str) -> None:
    from .processes import collect_workflow_id

    attempt = PaymentAttempt.objects.filter(provider_ref=payment.provider_ref).first()
    if attempt is not None:
        _signal(collect_workflow_id(attempt.organisation_id, attempt.invoice_id), name)
