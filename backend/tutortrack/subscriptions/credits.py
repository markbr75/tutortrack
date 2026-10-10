"""SMS and AI credits (FR-04-8): a monthly allowance from the plan, top-ups bought through
Stripe (with an optional automatic top-up), consumption by E13 (SMS) and E31 (AI), and a
hard stop or overage per the organisation's choice.

The allowance is used first and resets each billing period; purchased credits carry over.
Overage (when allowed) makes the purchased balance negative and is charged at the next
reset at the smallest pack's rate.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import structlog
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import entitlements
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.money import Money
from tutortrack.core.time import now

from .catalogue import CURRENCIES
from .events import CreditsLow
from .gateway import ChargeResult, CheckoutResult, GatewayError, get_gateway
from .models import CreditAccount, CreditPurchase, CreditType, UsageCreditLedger

logger = structlog.get_logger(__name__)


def _prices(*values: str) -> dict[str, str]:
    return dict(zip(CURRENCIES, values, strict=True))


PACKS: dict[str, dict[int, dict[str, str]]] = {
    CreditType.SMS: {
        500: _prices("20.00", "25.00", "23.00", "40.00", "34.00", "43.00"),
        2000: _prices("70.00", "88.00", "80.00", "140.00", "120.00", "150.00"),
    },
    CreditType.AI: {
        1000: _prices("10.00", "12.00", "11.00", "20.00", "17.00", "21.00"),
        5000: _prices("40.00", "50.00", "46.00", "80.00", "68.00", "86.00"),
    },
}
ALLOWANCE_LIMIT: dict[str, str] = {CreditType.SMS: "sms_credits_monthly"}
HOME_SMS_COUNTRIES = {"GB", "IE", "US", "CA"}  # 1 credit a segment; elsewhere 2


def pack_price(credit_type: str, credits: int, currency: str) -> Money:
    try:
        return Money(Decimal(PACKS[credit_type][credits][currency]), currency)
    except KeyError:
        raise BusinessRuleViolation(_("Choose one of the available packs.")) from None


def account(credit_type: str, *, lock: bool = False) -> CreditAccount:
    acct, _created = CreditAccount.objects.get_or_create(credit_type=credit_type)
    if lock:
        acct = CreditAccount.objects.select_for_update().get(pk=acct.pk)
    return acct


def _entry(acct: CreditAccount, delta: int, reason: str, ref: str = "") -> None:
    UsageCreditLedger.objects.create(
        credit_type=acct.credit_type, delta=delta, reason=reason, ref=ref[:120],
        balance_after=acct.balance,
    )  # fmt: skip


def _currency() -> str:
    from .services import current

    subscription = current()
    return subscription.currency if subscription else "GBP"


@transaction.atomic
def reset_allowances(*, ref: str) -> None:
    """Start of a period: expire the unused allowance, grant the plan's, settle overage."""
    for credit_type in CreditType.values:
        acct = account(credit_type, lock=True)
        if acct.included_balance:
            expired = acct.included_balance
            acct.included_balance = 0
            _entry(acct, -expired, UsageCreditLedger.Reason.EXPIRY, ref)
        limit_key = ALLOWANCE_LIMIT.get(credit_type)
        allowance = (entitlements.limit(limit_key) if limit_key else 0) or 0
        acct.allowance = allowance
        acct.included_balance = allowance
        acct.used_this_period = 0
        acct.period_started_at = now()
        acct.low_notified = False
        if allowance:
            _entry(acct, allowance, UsageCreditLedger.Reason.GRANT, ref)
        if acct.purchased_balance < 0:
            _settle_overage(acct, ref)
        acct.save()


def _settle_overage(acct: CreditAccount, ref: str) -> None:
    from .services import current

    owed = -acct.purchased_balance
    currency = _currency()
    smallest = min(PACKS[acct.credit_type])
    rate = pack_price(acct.credit_type, smallest, currency).amount / smallest
    amount = Money((rate * owed).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), currency)
    subscription = current()
    if subscription is None or not subscription.stripe_customer_id:
        return
    result = get_gateway().charge(
        customer=subscription.stripe_customer_id, amount=amount,
        description=_("%(count)s extra credits used") % {"count": owed},
        idempotency_key=f"overage-{acct.pk}-{ref}",
    )  # fmt: skip
    if result.paid:
        acct.purchased_balance = 0
        _entry(acct, owed, UsageCreditLedger.Reason.ADJUSTMENT, f"overage:{result.ref}")
    else:
        logger.warning("subscriptions.overage_charge_failed", message=result.message)


@transaction.atomic
def consume(credit_type: str, amount: int, *, ref: str = "") -> bool:
    """Take ``amount`` credits; False (nothing taken) when there aren't enough and
    overage is off."""
    acct = account(credit_type, lock=True)
    if acct.balance < amount and not acct.allow_overage:
        return False
    from_included = min(acct.included_balance, amount)
    acct.included_balance -= from_included
    acct.purchased_balance -= amount - from_included
    acct.used_this_period += amount
    _entry(acct, -amount, UsageCreditLedger.Reason.CONSUMPTION, ref)
    if acct.balance < acct.low_threshold:
        if not acct.low_notified:
            acct.low_notified = True
            _low(acct)
        if acct.auto_top_up:
            org_id = require_organisation_id()
            transaction.on_commit(lambda: _auto_top_up_later(org_id, credit_type))
    acct.save()
    return True


def _low(acct: CreditAccount) -> None:
    from .services import notify_owners

    publish(CreditsLow(subject_id=acct.pk, credit_type=acct.credit_type, balance=acct.balance))
    label = CreditType(acct.credit_type).label
    notify_owners(
        "credits", _("%(credits)s running low") % {"credits": label},
        _("%(count)s left. Top up from Billing & plan, or turn on automatic top-ups.")
        % {"count": max(acct.balance, 0)},
        key=f"{acct.credit_type}:{now():%Y%m%d%H%M}",
    )  # fmt: skip


def _auto_top_up_later(organisation_id: Any, credit_type: str) -> None:
    from .tasks import auto_top_up

    auto_top_up.delay(organisation_id=str(organisation_id), credit_type=credit_type)


def auto_top_up(credit_type: str) -> CreditPurchase | None:
    acct = account(credit_type)
    if not acct.auto_top_up or acct.balance >= acct.low_threshold:
        return None
    recent = CreditPurchase.objects.filter(
        credit_type=credit_type, automatic=True, completed_at__isnull=True,
        failed_at__isnull=True,
    )  # fmt: skip
    if recent.exists():
        return None
    purchase, _url = buy(credit_type, acct.top_up_pack, automatic=True)
    return purchase


def buy(credit_type: str, credits: int, *, automatic: bool = False) -> tuple[CreditPurchase, str]:
    """Charge the saved card for a pack; without one, return a Checkout URL instead."""
    from .services import _ensure_customer, _require, _urls

    if credit_type not in CreditType.values:
        raise BusinessRuleViolation(_("Unknown credit type."))
    subscription = _require()
    price = pack_price(credit_type, credits, subscription.currency)
    with transaction.atomic():
        purchase = CreditPurchase.objects.create(
            credit_type=credit_type, credits=credits, amount=price.amount,
            currency=price.currency, automatic=automatic,
        )  # fmt: skip
    gateway = get_gateway()
    customer = _ensure_customer(subscription)
    label = CreditType(credit_type).label
    description = _("%(count)s %(credits)s") % {"count": credits, "credits": label}
    if not subscription.stripe_subscription_id and not automatic:
        success, cancel = _urls()
        session = gateway.checkout_payment(
            customer=customer, amount=price, description=description, success_url=success,
            cancel_url=cancel,
            metadata={"organisation_id": str(subscription.organisation_id),
                      "credit_purchase": str(purchase.pk)},
        )  # fmt: skip
        return purchase, session.url
    try:
        result = gateway.charge(
            customer=customer, amount=price, description=description,
            idempotency_key=f"credits-{purchase.pk}",
        )  # fmt: skip
    except GatewayError as exc:
        result = ChargeResult(False, message=str(exc))
    if not result.paid:
        CreditPurchase.objects.filter(pk=purchase.pk).update(failed_at=now())
        if automatic:
            logger.warning("subscriptions.auto_top_up_failed", message=result.message)
            return purchase, ""
        raise BusinessRuleViolation(result.message or _("The payment didn't go through."))
    complete_purchase(purchase, result.ref)
    purchase.refresh_from_db()
    return purchase, ""


@transaction.atomic
def complete_purchase(purchase: CreditPurchase, provider_ref: str) -> CreditPurchase:
    purchase = CreditPurchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.completed_at:
        return purchase
    purchase.completed_at = now()
    purchase.provider_ref = provider_ref[:100]
    purchase.save(update_fields=["completed_at", "provider_ref", "updated_at"])
    acct = account(purchase.credit_type, lock=True)
    acct.purchased_balance += purchase.credits
    if acct.balance >= acct.low_threshold:
        acct.low_notified = False
    _entry(acct, purchase.credits, UsageCreditLedger.Reason.PURCHASE, f"purchase:{purchase.pk}")
    acct.save()
    return purchase


def complete_purchase_ref(purchase_id: str, provider_ref: str) -> None:
    purchase = CreditPurchase.objects.filter(pk=purchase_id).first() if purchase_id else None
    if purchase is not None:
        complete_purchase(purchase, provider_ref)


def complete_checkout(result: CheckoutResult) -> None:
    if result.complete:
        complete_purchase_ref(result.metadata.get("credit_purchase", ""), result.payment_ref)


@transaction.atomic
def update_settings(credit_type: str, **changes: Any) -> CreditAccount:
    allowed = {"auto_top_up", "top_up_pack", "low_threshold", "allow_overage"}
    unknown = set(changes) - allowed
    if unknown:
        raise BusinessRuleViolation(f"Unknown credit settings: {', '.join(sorted(unknown))}")
    if "top_up_pack" in changes and changes["top_up_pack"] not in PACKS[credit_type]:
        raise BusinessRuleViolation(_("Choose one of the available packs."))
    acct = account(credit_type, lock=True)
    for key, value in changes.items():
        setattr(acct, key, value)
    acct.save()
    return acct


def ledger(credit_type: str, limit: int = 50) -> list[UsageCreditLedger]:
    return list(UsageCreditLedger.objects.filter(credit_type=credit_type)[:limit])


class SmsCreditMeter:
    """Registered with ``comms.channels``: every SMS segment costs credits."""

    def consume(self, segments: int, *, country: str) -> bool:
        from .models import Subscription

        if not Subscription.objects.exists():
            return True  # no subscription (internal or pre-E04 organisations): unmetered
        cost = segments * (1 if country.upper() in HOME_SMS_COUNTRIES else 2)
        return consume(CreditType.SMS, cost, ref="sms")


def require_account(credit_type: str) -> CreditAccount:
    if credit_type not in CreditType.values:
        raise NotFound()
    return account(credit_type)
