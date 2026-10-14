"""Metering AI requests against the organisation's AI credits (E04 FR-04-8, E31 §2).

Each request costs whole credits computed from its token usage at the model's list price
(``PRICES``) divided by ``CREDIT_VALUE_USD``, rounded up, at least one. Cache writes and
reads are priced at their own rates, so prompt caching lowers what tenants pay.

Before a request: the organisation's monthly cap (``ai.monthly_credit_cap``) and, for
organisations on a subscription, the credit balance (allowance first, then top-ups) must
allow it, otherwise ``AICreditsExhausted`` (402). After it: the credits are consumed with
the request log as the reference. Organisations without a subscription (internal, or set
up before E04) are unmetered, as for SMS.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db.models import Sum
from django.utils.translation import gettext as _

from tutortrack.core.context import require_organisation_id
from tutortrack.core.time import now

from .exceptions import AICreditsExhausted, AIRateLimited
from .providers.base import Usage

# USD per million tokens: input, output, cache read, cache write (5-minute TTL).
PRICES: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20"), Decimal("0.20"), Decimal("5")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125")),
}
DEFAULT_PRICE = PRICES["claude-opus-5-5"]  # unknown models are priced as the dearest
CREDIT_VALUE_USD = Decimal("0.005")
MILLION = Decimal(1_000_000)


def cost_usd(model: str, usage: Usage) -> Decimal:
    price_in, price_out, price_read, price_write = PRICES.get(model, DEFAULT_PRICE)
    return (
        usage.input_tokens * price_in
        + usage.output_tokens * price_out
        + usage.cache_read_tokens * price_read
        + usage.cache_write_tokens * price_write
    ) / MILLION


def credits_for(model: str, usage: Usage) -> int:
    if not (usage.input_tokens or usage.output_tokens or usage.cache_read_tokens):
        return 0
    units = (cost_usd(model, usage) / CREDIT_VALUE_USD).to_integral_value(rounding=ROUND_CEILING)
    return max(1, int(units))


def month_start(moment: Any = None) -> date:
    moment = moment or now()
    return date(moment.year, moment.month, 1)


def used_this_month() -> int:
    from .models import AIUsage

    total = AIUsage.objects.filter(period=month_start()).aggregate(total=Sum("credits"))["total"]
    return int(total or 0)


def _metered() -> bool:
    from tutortrack.subscriptions.models import Subscription

    return Subscription.objects.exists()


def credit_summary() -> dict[str, Any]:
    from tutortrack.subscriptions import credits
    from tutortrack.subscriptions.models import CreditType
    from tutortrack.tenancy.settings_service import get_setting

    cap = int(get_setting("ai.monthly_credit_cap") or 0)
    summary: dict[str, Any] = {
        "metered": _metered(),
        "used_this_month": used_this_month(),
        "monthly_cap": cap or None,
        "balance": None,
        "allowance": None,
    }
    if summary["metered"]:
        account = credits.account(CreditType.AI)
        summary["balance"] = account.balance
        summary["allowance"] = account.allowance
    return summary


def ensure_available() -> None:
    """Raise ``AICreditsExhausted`` when the cap or the balance leaves nothing to spend."""
    from tutortrack.subscriptions import credits
    from tutortrack.subscriptions.models import CreditType
    from tutortrack.tenancy.settings_service import get_setting

    cap = int(get_setting("ai.monthly_credit_cap") or 0)
    if cap and used_this_month() >= cap:
        raise AICreditsExhausted(
            _("Your organisation has used its AI limit for this month (%(cap)s credits).")
            % {"cap": cap},
            extra={"limit": "ai.monthly_credit_cap", "allowed": cap},
        )
    if not _metered():
        return
    account = credits.account(CreditType.AI)
    if account.balance <= 0 and not account.allow_overage:
        raise AICreditsExhausted(
            _(
                "You have no AI credits left. Buy more from Billing & plan, or wait for "
                "next month's allowance."
            ),
            extra={"limit": "ai_credits", "balance": account.balance},
        )


def charge(amount: int, *, ref: str) -> int:
    """Consume ``amount`` credits (or what is left, when overage is off); returns the
    number taken."""
    if amount <= 0 or not _metered():
        return amount
    from tutortrack.subscriptions import credits
    from tutortrack.subscriptions.models import CreditType

    if credits.consume(CreditType.AI, amount, ref=ref):
        return amount
    left = max(credits.account(CreditType.AI).balance, 0)
    if left and credits.consume(CreditType.AI, left, ref=ref):
        return left
    return 0


def check_rate(user: Any) -> None:
    """At most ``AI["USER_REQUESTS_PER_MINUTE"]`` requests per person and organisation."""
    limit = int(settings.AI.get("USER_REQUESTS_PER_MINUTE") or 0)
    if not limit or user is None:
        return
    minute = int(time.time() // 60)
    key = f"ai-rate:{require_organisation_id()}:{getattr(user, 'pk', user)}:{minute}"
    cache.add(key, 0, 90)
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.set(key, 1, 90)
        count = 1
    if count > limit:
        raise AIRateLimited(retry_after=60 - int(time.time()) % 60)
