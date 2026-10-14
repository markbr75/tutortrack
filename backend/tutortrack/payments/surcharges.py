"""Card surcharges and the payment methods each branch accepts (FR-11-1, gap G3).

**Methods per branch.** ``payments.enabled_methods`` (a branch-level setting) lists what a
branch takes: ``card`` (cards and wallets through Stripe), ``direct_debit`` (GoCardless or
Stripe debits), ``paypal`` and the manual methods. The pay page offers only the enabled
online providers; staff can only record enabled manual methods.

**Card surcharges.** ``payments.card_surcharge_percent`` (branch-level) passes card fees
on to the client as a *separate* line: when a client pays an invoice or payment request by
card on the pay page, the amount charged is the amount due plus the surcharge (rounded
half-up to the minor unit), and the surcharge is invoiced on its own (a ``surcharge``
charge on a separate, immediately issued invoice) and paid by the same payment. The
original invoice is never changed (financial records are immutable).

Legal limits by country (assumptions, see ADR 0037; tenants stay responsible for their own
compliance):

* **United Kingdom and the EEA:** surcharges on consumer cards are banned (UK Consumer
  Rights (Payment Surcharges) Regulations 2012 as amended in 2018; EU PSD2 art. 62(4)). We
  can't tell business cards apart, so surcharges are not allowed at all.
* **United States:** allowed up to 3% (card network cap); some states ban them (e.g.
  Connecticut, Massachusetts), which we can't check: the setting's help says so.
* **Canada:** allowed up to 2.4% (card network cap since October 2022); not in Quebec.
* **Australia:** allowed, but no more than the cost of acceptance (RBA); capped at 3% here.
* **New Zealand and elsewhere:** allowed up to 3%.

Auto-pay collections are not surcharged (the client agreed to pay the invoice amount).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils.translation import gettext as _
from rest_framework import serializers

from tutortrack.core.money import Money

ONLINE = ("card", "direct_debit", "paypal")
MANUAL = ("bank_transfer", "cash", "cheque", "other")
ALL_METHODS = (*ONLINE, *MANUAL)

EEA = frozenset(
    [
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
        "IS",
        "LI",
        "NO",
    ]
)
BANNED = EEA | {"GB"}
CAPS = {"US": Decimal("3"), "CA": Decimal("2.4"), "AU": Decimal("3"), "NZ": Decimal("3")}
DEFAULT_CAP = Decimal("3")
HUNDRED = Decimal(100)


def limit_for(country: str) -> Decimal | None:
    """The highest surcharge (percent) allowed in ``country``; ``None`` if banned."""
    code = (country or "").upper()
    if code in BANNED:
        return None
    return CAPS.get(code, DEFAULT_CAP)


def _country() -> str:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    return str(Organisation.objects.get(pk=require_organisation_id()).country)


def clean_methods(value: Any) -> list[str]:
    """Validator for ``payments.enabled_methods``."""
    if not isinstance(value, list) or not value:
        raise serializers.ValidationError(_("Choose at least one way to pay."))
    unknown = [v for v in value if v not in ALL_METHODS]
    if unknown:
        raise serializers.ValidationError(
            _("Unknown payment method: %(method)s.") % {"method": unknown[0]}
        )
    return [m for m in ALL_METHODS if m in value]


def clean_percent(value: Any) -> str:
    """Validator for ``payments.card_surcharge_percent`` (a decimal string)."""
    try:
        percent = Decimal(str(value or "0").strip())
    except InvalidOperation:
        raise serializers.ValidationError(_("Enter a percentage such as 1.5.")) from None
    if percent < 0 or percent.as_tuple().exponent < -2:  # type: ignore[operator]
        raise serializers.ValidationError(_("Enter a percentage with up to two decimals."))
    if percent:
        cap = limit_for(_country())
        if cap is None:
            raise serializers.ValidationError(
                _("Card surcharges aren't allowed for consumers in your country.")
            )
        if percent > cap:
            raise serializers.ValidationError(
                _("Card surcharges can't be more than %(cap)s%% in your country.")
                % {"cap": cap.normalize()}
            )
    return str(percent.normalize()) if percent else "0"


def _branch(branch_id: Any) -> Any:
    from tutortrack.tenancy.models import Branch

    return Branch.objects.filter(pk=branch_id).first() if branch_id else None


def enabled_methods(branch_id: Any) -> list[str]:
    from tutortrack.tenancy.settings_service import get_setting

    return list(get_setting("payments.enabled_methods", branch=_branch(branch_id)))


def surcharge_percent(branch_id: Any) -> Decimal:
    """The branch's card surcharge, never above today's legal limit (a country change or
    a lower cap after the setting was saved wins)."""
    from tutortrack.tenancy.settings_service import get_setting

    try:
        percent = Decimal(
            str(get_setting("payments.card_surcharge_percent", branch=_branch(branch_id)))
        )
    except InvalidOperation:
        return Decimal(0)
    cap = limit_for(_country())
    if cap is None or percent <= 0:
        return Decimal(0)
    return min(percent, cap)


def surcharge_for(branch_id: Any, amount: Money) -> Money:
    """The card surcharge on ``amount``, rounded half-up to the minor unit."""
    percent = surcharge_percent(branch_id)
    if not percent:
        return Money.zero(amount.currency).round_to_minor()
    return (amount * percent / HUNDRED).round_to_minor()
