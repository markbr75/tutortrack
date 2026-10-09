"""Rate resolution engine v1 (FR-06-4, E06-T04).

``resolve_rates(context) -> RateQuote`` turns a lesson (service, duration, students,
tutors and any overrides) into per-student **charge** lines and per-tutor **pay** lines,
each with a trace explaining how the rate was chosen.

Charge precedence (most specific wins):
  1. lesson attendee override  2. job student override  3. job charge rate
  4. service price in the lesson currency (service default or a ``ServicePrice``)
Pay precedence:
  1. lesson tutor override  2. job tutor override
  3. service pay rate, or a percentage of the lesson's charge

Client price lists, pay tiers, tutor personal rates, premiums and discounts are Phase 2
(E06-T07..T09) and slot in between these steps.

Amounts are rounded half-up to the currency's minor unit per line. For a group lesson whose
rate is *split*, the lesson total is allocated so that the lines add up to it exactly.
E08 snapshots ``RateQuote.as_dict()`` onto lesson attendees and tutors.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money, sum_money

from .models import Service, ServicePrice, TaxRate

HOUR = Decimal(60)


@dataclass(frozen=True)
class AttendeeInput:
    student_id: str
    client_id: str | None = None
    rate_override: Money | None = None  # set on this lesson for this student
    job_rate_override: Money | None = None  # set on the job for this student (E07)


@dataclass(frozen=True)
class TutorInput:
    tutor_id: str
    rate_override: Money | None = None  # set on this lesson for this tutor
    job_rate_override: Money | None = None  # set on the job for this tutor (E07)


@dataclass(frozen=True)
class RateContext:
    service: Service
    duration_minutes: int
    attendees: Sequence[AttendeeInput]
    tutors: Sequence[TutorInput] = ()
    currency: str | None = None  # defaults to the service currency
    job_charge_rate: Money | None = None  # the job's rate for every student (E07)


@dataclass
class ChargeLine:
    student_id: str
    client_id: str | None
    unit: str
    rate: Money
    quantity: Decimal
    amount: Money
    tax_rate_id: str | None
    tax_percent: Decimal
    tax_amount: Money
    trace: list[str] = field(default_factory=list)


@dataclass
class PayLine:
    tutor_id: str
    unit: str
    rate: Money | None
    quantity: Decimal
    amount: Money
    trace: list[str] = field(default_factory=list)


@dataclass
class RateQuote:
    currency: str
    duration_minutes: int
    charges: list[ChargeLine]
    pay: list[PayLine]

    @property
    def total_charge(self) -> Money:
        return sum_money((line.amount for line in self.charges), self.currency)

    @property
    def total_pay(self) -> Money:
        return sum_money((line.amount for line in self.pay), self.currency)

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe snapshot (stored on lessons by E08)."""

        def money(value: Money | None) -> dict[str, str] | None:
            return None if value is None else value.to_dict()

        return {
            "currency": self.currency,
            "duration_minutes": self.duration_minutes,
            "total_charge": money(self.total_charge),
            "total_pay": money(self.total_pay),
            "charges": [
                {
                    "student_id": c.student_id,
                    "client_id": c.client_id,
                    "unit": c.unit,
                    "rate": money(c.rate),
                    "quantity": str(c.quantity),
                    "amount": money(c.amount),
                    "tax_rate_id": c.tax_rate_id,
                    "tax_percent": str(c.tax_percent),
                    "tax_amount": money(c.tax_amount),
                    "trace": c.trace,
                }
                for c in self.charges
            ],
            "pay": [
                {
                    "tutor_id": p.tutor_id,
                    "unit": p.unit,
                    "rate": money(p.rate),
                    "quantity": str(p.quantity),
                    "amount": money(p.amount),
                    "trace": p.trace,
                }
                for p in self.pay
            ],
        }


# --- helpers ------------------------------------------------------------------------------------

UNIT_SUFFIX: dict[str, str] = {
    Service.PricingUnit.PER_HOUR: "/h",
    Service.PricingUnit.PER_LESSON: "/lesson",
    Service.PricingUnit.PER_STUDENT_PER_LESSON: "/student/lesson",
    Service.PricingUnit.PER_MONTH: "/month",
    Service.PricingUnit.PER_TERM: "/term",
}


def describe(label: str, rate: Money, unit: str) -> str:
    shown = rate if rate.is_rounded() else rate.round_to_minor()
    return f"{label} {shown.format()}{UNIT_SUFFIX.get(unit, '')}"


def _plain(value: Decimal | None) -> str:
    """60.00 -> "60", 12.50 -> "12.5"."""
    text = f"{value or 0:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _quantity(unit: str, duration_minutes: int) -> Decimal:
    if unit == Service.PricingUnit.PER_HOUR:
        return Decimal(duration_minutes) / HOUR
    if unit in {Service.PricingUnit.PER_MONTH, Service.PricingUnit.PER_TERM}:
        return Decimal(0)  # billed by the subscription (E10), not per lesson
    return Decimal(1)


def _check_rate(name: str, value: Money | None, currency: str) -> None:
    if value is None:
        return
    if value.currency != currency:
        raise BusinessRuleViolation(
            _("%(name)s must be in %(currency)s.") % {"name": name, "currency": currency}
        )
    if value.is_negative():
        raise BusinessRuleViolation(_("Rates can't be negative."))


def base_prices(service: Service, currency: str) -> tuple[Money, Money | None, Decimal | None]:
    """The service's charge rate, pay rate and pay percent in ``currency`` (FR-06-12)."""
    if currency == service.currency:
        return service.charge_rate, service.pay_rate, service.pay_percent
    price = ServicePrice.objects.filter(service=service, currency=currency).first()
    if price is None:
        raise BusinessRuleViolation(
            _("%(service)s has no price in %(currency)s.")
            % {"service": service.name, "currency": currency}
        )
    return price.charge_rate, price.pay_rate, price.pay_percent


def _tax(service: Service) -> tuple[TaxRate | None, bool]:
    from tutortrack.tenancy.settings_service import get_setting

    rate = service.tax_rate or TaxRate.objects.filter(is_default=True, active=True).first()
    return rate, bool(get_setting("billing.prices_include_tax"))


def tax_on(amount: Money, percent: Decimal, inclusive: bool) -> Money:
    """Tax in ``amount`` (inclusive prices) or on top of it (exclusive), rounded half-up."""
    if not percent:
        return Money.zero(amount.currency)
    if inclusive:
        return (amount - amount / (1 + percent / 100)).round_to_minor()
    return (amount * (percent / 100)).round_to_minor()


# --- engine -------------------------------------------------------------------------------------


def resolve_rates(context: RateContext) -> RateQuote:
    service = context.service
    currency = (context.currency or service.currency).upper()
    if context.duration_minutes <= 0:
        raise BusinessRuleViolation(_("A lesson needs a duration."))
    if not context.attendees:
        raise BusinessRuleViolation(_("A lesson needs at least one student."))
    if len(context.attendees) > service.max_students:
        raise BusinessRuleViolation(
            _("%(service)s takes at most %(n)s students.")
            % {"service": service.name, "n": service.max_students}
        )
    _check_rate(_("The job rate"), context.job_charge_rate, currency)
    for a in context.attendees:
        _check_rate(_("The student's rate"), a.rate_override, currency)
        _check_rate(_("The student's job rate"), a.job_rate_override, currency)
    for t in context.tutors:
        _check_rate(_("The tutor's rate"), t.rate_override, currency)
        _check_rate(_("The tutor's job rate"), t.job_rate_override, currency)

    default_charge, default_pay, pay_percent = base_prices(service, currency)
    charges = _charge_lines(context, currency, default_charge)
    total = sum_money((c.amount for c in charges), currency)
    pay = _pay_lines(context, currency, default_pay, pay_percent, total)
    return RateQuote(currency, context.duration_minutes, charges, pay)


def _charge_lines(context: RateContext, currency: str, default: Money) -> list[ChargeLine]:
    service = context.service
    unit = service.pricing_unit
    quantity = _quantity(unit, context.duration_minutes)
    attendees = list(context.attendees)
    n = len(attendees)
    split = (
        n > 1
        and service.group_charge == Service.GroupCharge.SPLIT
        and unit in {Service.PricingUnit.PER_HOUR, Service.PricingUnit.PER_LESSON}
    )
    tax_rate, inclusive = _tax(service)
    percent = tax_rate.percent if tax_rate else Decimal(0)

    rates: list[tuple[Money, str]] = []
    for a in attendees:
        if a.rate_override is not None:
            rates.append((a.rate_override, describe(_("lesson rate"), a.rate_override, unit)))
        elif a.job_rate_override is not None:
            rates.append(
                (a.job_rate_override, describe(_("student's job rate"), a.job_rate_override, unit))
            )
        elif context.job_charge_rate is not None:
            rates.append(
                (context.job_charge_rate, describe(_("job rate"), context.job_charge_rate, unit))
            )
        else:
            rates.append((default, describe(_("service rate"), default, unit)))

    if split and len({r for r, _label in rates}) == 1:
        # Everyone has the same rate: split the lesson total exactly.
        amounts = (rates[0][0] * quantity).allocate([1] * n)
    elif split:
        amounts = [(rate * quantity / n).round_to_minor() for rate, _label in rates]
    else:
        amounts = [(rate * quantity).round_to_minor() for rate, _label in rates]

    lines = []
    for a, (rate, label), amount in zip(attendees, rates, amounts, strict=True):
        trace = [label]
        if unit == Service.PricingUnit.PER_HOUR:
            trace.append(_("%(minutes)s minutes") % {"minutes": context.duration_minutes})
        if split:
            trace.append(_("split between %(n)s students") % {"n": n})
        if quantity == 0:
            trace.append(_("billed by subscription, not per lesson"))
        lines.append(
            ChargeLine(
                student_id=a.student_id,
                client_id=a.client_id,
                unit=unit,
                rate=rate,
                quantity=quantity,
                amount=amount,
                tax_rate_id=str(tax_rate.pk) if tax_rate else None,
                tax_percent=percent,
                tax_amount=tax_on(amount, percent, inclusive),
                trace=trace,
            )
        )
    return lines


def _pay_lines(
    context: RateContext,
    currency: str,
    default: Money | None,
    percent: Decimal | None,
    total_charge: Money,
) -> list[PayLine]:
    service = context.service
    unit = service.pay_unit
    quantity = _quantity(unit, context.duration_minutes)
    tutors = list(context.tutors)
    lines: list[PayLine] = []
    # Percentage pay is shared between the lesson's tutors that have no explicit rate.
    by_percent = (
        [t for t in tutors if t.rate_override is None and t.job_rate_override is None]
        if default is None and percent is not None
        else []
    )
    shares = (
        (total_charge * (percent / 100)).allocate([1] * len(by_percent))
        if by_percent and percent is not None
        else []
    )
    share_of = dict(zip((t.tutor_id for t in by_percent), shares, strict=True))
    for t in tutors:
        if t.rate_override is not None:
            rate: Money = t.rate_override
            trace = [describe(_("lesson pay rate"), t.rate_override, unit)]
        elif t.job_rate_override is not None:
            rate = t.job_rate_override
            trace = [describe(_("tutor's job rate"), t.job_rate_override, unit)]
        elif default is not None:
            rate = default
            trace = [describe(_("service pay rate"), default, unit)]
        elif t.tutor_id in share_of:
            amount = share_of[t.tutor_id]
            trace = [_("%(percent)s%% of the lesson charge") % {"percent": _plain(percent)}]
            if len(by_percent) > 1:
                trace.append(_("shared between %(n)s tutors") % {"n": len(by_percent)})
            lines.append(PayLine(t.tutor_id, "percent", None, Decimal(1), amount, trace))
            continue
        else:
            lines.append(
                PayLine(
                    t.tutor_id, unit, None, quantity, Money.zero(currency), [_("no pay rate set")]
                )
            )
            continue
        if unit == Service.PayUnit.PER_HOUR:
            trace.append(_("%(minutes)s minutes") % {"minutes": context.duration_minutes})
        lines.append(
            PayLine(t.tutor_id, unit, rate, quantity, (rate * quantity).round_to_minor(), trace)
        )
    return lines
