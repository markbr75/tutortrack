"""Rate resolution engine (FR-06-4; v1 in E06-T04, Phase 2 in E06-T07..T09).

``resolve_rates(context) -> RateQuote`` turns a lesson (service, duration, students,
tutors and any overrides) into per-student **charge** lines and per-tutor **pay** lines,
each with a trace explaining how the rate was chosen.

Charge precedence (most specific wins):
  1. lesson attendee override  2. job student override  3. job charge rate
  4. the client's price list  5. the service rate for the lead tutor's pay tier (when the
  ``pricing.tier_affects_charge`` setting is on)  6. service price in the lesson currency
Pay precedence:
  1. lesson tutor override  2. job tutor override  3. the tutor's personal rate for the
  service  4. the service rate for the tutor's pay tier  5. service pay rate, or a
  percentage of the lesson's charge (gross, or net of discounts: ``pricing.pay_percent_basis``)

Modifiers, in order: duration scaling per pricing unit, group pricing (per student or a
split), **premiums** (charge and pay, FR-06-6), then **discounts** (charge only, FR-06-7).
Lines priced from a lesson-level manual override are final: no premium or discount applies.

The engine is pure: everything that needs the database (price lists, tiers, rules,
holidays, a student's lesson history) arrives in ``RateContext.rules`` (a ``PricingRules``,
built by ``catalogue.pricing_rules.load_rules``). Without rules it behaves like v1.

Amounts are rounded half-up to the currency's minor unit per line (and per premium and
discount step). For a group lesson whose rate is *split*, the lesson total (with premiums)
is allocated so that the lines add up to it exactly. E08 snapshots ``RateQuote.as_dict()``
onto lesson attendees and tutors.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money, sum_money

from .models import Service, ServicePrice, TaxRate

HOUR = Decimal(60)
HUNDRED = Decimal(100)


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


# --- Phase 2 rules (all optional) ----------------------------------------------------------------


@dataclass(frozen=True)
class TierRate:
    tier_name: str
    pay_rate: Money | None = None
    charge_rate: Money | None = None


@dataclass(frozen=True)
class Premium:
    """A premium rule, already loaded (FR-06-6). Empty conditions match everything."""

    name: str
    priority: int = 0
    stackable: bool = True
    weekdays: tuple[int, ...] = ()
    time_from: time | None = None
    time_to: time | None = None
    public_holidays: bool = False
    short_notice_hours: int | None = None
    location_types: tuple[str, ...] = ()
    delivery: str = "any"
    subject_ids: tuple[str, ...] = ()
    level_ids: tuple[str, ...] = ()
    service_ids: tuple[str, ...] = ()
    min_students: int | None = None
    max_students: int | None = None
    charge_percent: Decimal | None = None
    charge_fixed: Money | None = None
    pay_percent: Decimal | None = None
    pay_fixed: Money | None = None


@dataclass(frozen=True)
class Discount:
    """A discount rule, already loaded (FR-06-7)."""

    name: str
    kind: str  # sibling | volume | first_lesson | client | scholarship | promo
    priority: int = 0
    stackable: bool = True
    percent: Decimal | None = None
    fixed_amount: Money | None = None
    fixed_price: Money | None = None
    sibling_from: int = 2
    volume_min_lessons: int | None = None
    client_id: str | None = None
    student_id: str | None = None
    service_ids: tuple[str, ...] = ()
    promo: bool = False  # only with a promo code (the loader includes it only then)


@dataclass(frozen=True)
class LessonFacts:
    """When and where the lesson is (for premium conditions)."""

    local_start: datetime | None = None
    is_holiday: bool = False
    notice_hours: Decimal | None = None  # booked this long before the start
    location_type: str = ""
    online: bool = False


@dataclass(frozen=True)
class AttendeeFacts:
    """A student's history (for discount conditions)."""

    sibling_position: int = 1  # 2 = the client's second student
    lessons_in_month: int = 0  # including this one
    first_lesson: bool = False


@dataclass
class PricingRules:
    price_lists: dict[str, tuple[Money, str]] = field(default_factory=dict)  # client id
    tier_rates: dict[str, TierRate] = field(default_factory=dict)  # tutor id
    tier_affects_charge: bool = False
    tutor_rates: dict[str, Money] = field(default_factory=dict)  # tutor id
    premiums: Sequence[Premium] = ()
    discounts: Sequence[Discount] = ()
    facts: LessonFacts = field(default_factory=LessonFacts)
    attendee_facts: dict[str, AttendeeFacts] = field(default_factory=dict)  # student id
    pay_percent_basis: str = "gross"  # or "net" (after discounts)


@dataclass(frozen=True)
class RateContext:
    service: Service
    duration_minutes: int
    attendees: Sequence[AttendeeInput]
    tutors: Sequence[TutorInput] = ()
    currency: str | None = None  # defaults to the service currency
    job_charge_rate: Money | None = None  # the job's rate for every student (E07)
    rules: PricingRules | None = None


@dataclass
class Adjustment:
    name: str
    amount: Money  # positive for premiums, negative for discounts

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "amount": self.amount.to_dict()}


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
    premiums: list[Adjustment] = field(default_factory=list)
    discounts: list[Adjustment] = field(default_factory=list)

    @property
    def undiscounted_amount(self) -> Money:
        """The amount before discounts (shown with discount lines when they are not netted)."""
        return sum_money((d.amount for d in self.discounts), self.amount.currency) * -1 + (
            self.amount
        )


@dataclass
class PayLine:
    tutor_id: str
    unit: str
    rate: Money | None
    quantity: Decimal
    amount: Money
    trace: list[str] = field(default_factory=list)
    premiums: list[Adjustment] = field(default_factory=list)


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
        """JSON-safe snapshot (stored on lessons by E08).

        Each charge line carries ``discounts`` and ``undiscounted_amount``: billing (E10)
        either nets them (``amount``) or shows them as separate negative lines, per the
        ``pricing.discount_display`` setting."""

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
                    "undiscounted_amount": money(c.undiscounted_amount),
                    "tax_rate_id": c.tax_rate_id,
                    "tax_percent": str(c.tax_percent),
                    "tax_amount": money(c.tax_amount),
                    "premiums": [p.as_dict() for p in c.premiums],
                    "discounts": [d.as_dict() for d in c.discounts],
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
                    "premiums": [x.as_dict() for x in p.premiums],
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


def _same_currency(value: Money | None, currency: str) -> Money | None:
    return value if value is not None and value.currency == currency else None


# --- rule matching ------------------------------------------------------------------------------


def _pick(matches: list[Any]) -> list[Any]:
    """Stacking (FR-06-6/7): highest priority first; a non-stackable rule that comes
    first applies alone, otherwise every stackable match applies."""
    ordered = sorted(matches, key=lambda r: (-r.priority, r.name))
    if not ordered:
        return []
    if not ordered[0].stackable:
        return ordered[:1]
    return [r for r in ordered if r.stackable]


def premium_applies(p: Premium, context: RateContext, facts: LessonFacts) -> bool:
    service = context.service
    n = len(context.attendees)
    if p.service_ids and str(service.pk) not in p.service_ids:
        return False
    if p.subject_ids and str(service.subject_id) not in p.subject_ids:
        return False
    if p.level_ids and str(service.level_id) not in p.level_ids:
        return False
    if p.min_students is not None and n < p.min_students:
        return False
    if p.max_students is not None and n > p.max_students:
        return False
    if p.delivery == "online" and not facts.online:
        return False
    if p.delivery == "in_person" and facts.online:
        return False
    if p.location_types and facts.location_type not in p.location_types:
        return False
    if p.public_holidays and not facts.is_holiday:
        return False
    if p.short_notice_hours is not None and (
        facts.notice_hours is None or facts.notice_hours >= p.short_notice_hours
    ):
        return False
    local = facts.local_start
    if p.weekdays and (local is None or local.weekday() not in p.weekdays):
        return False
    if p.time_from is not None or p.time_to is not None:
        if local is None:
            return False
        start = local.time().replace(tzinfo=None)
        begin, finish = p.time_from or time.min, p.time_to or time.max
        inside = begin <= start < finish if begin <= finish else (start >= begin or start < finish)
        if not inside:
            return False
    return True


def discount_applies(
    d: Discount, context: RateContext, attendee: AttendeeInput, facts: AttendeeFacts
) -> bool:
    if d.service_ids and str(context.service.pk) not in d.service_ids:
        return False
    if d.kind == "sibling":
        return facts.sibling_position >= max(d.sibling_from, 2)
    if d.kind == "volume":
        return d.volume_min_lessons is not None and facts.lessons_in_month >= d.volume_min_lessons
    if d.kind == "first_lesson":
        return facts.first_lesson
    if d.kind == "client":
        return d.client_id is not None and d.client_id == attendee.client_id
    if d.kind == "scholarship":
        return (d.student_id is not None and d.student_id == attendee.student_id) or (
            d.client_id is not None and d.client_id == attendee.client_id
        )
    return d.kind == "promo"  # the loader only includes the code's rule


def _premium_step(amount: Money, percent: Decimal | None, fixed: Money | None) -> Money:
    step = Money.zero(amount.currency)
    if percent:
        step = step + (amount * (percent / HUNDRED)).round_to_minor()
    if fixed is not None:
        step = step + fixed.round_to_minor()
    return step


def _percent_label(name: str, percent: Decimal | None, fixed: Money | None, sign: str) -> str:
    parts = []
    if percent:
        parts.append(f"{sign}{_plain(percent)}%")
    if fixed is not None:
        parts.append(f"{sign}{fixed.round_to_minor().format()}")
    return f"{name} {' '.join(parts)}".strip()


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

    rules = context.rules or PricingRules()
    premiums = _pick([p for p in rules.premiums if premium_applies(p, context, rules.facts)])
    default_charge, default_pay, pay_percent = base_prices(service, currency)
    charges = _charge_lines(context, rules, currency, default_charge, premiums)
    if rules.pay_percent_basis == "net":
        basis = sum_money((c.amount for c in charges), currency)
    else:
        basis = sum_money((c.undiscounted_amount for c in charges), currency)
    pay = _pay_lines(context, rules, currency, default_pay, pay_percent, basis, premiums)
    return RateQuote(currency, context.duration_minutes, charges, pay)


def _charge_rate(
    context: RateContext,
    rules: PricingRules,
    a: AttendeeInput,
    currency: str,
    default: Money,
) -> tuple[Money, str, bool]:
    """(rate, trace label, is_manual_override) by charge precedence."""
    unit = context.service.pricing_unit
    if a.rate_override is not None:
        return a.rate_override, describe(_("lesson rate"), a.rate_override, unit), True
    if a.job_rate_override is not None:
        return (
            a.job_rate_override,
            describe(_("student's job rate"), a.job_rate_override, unit),
            False,
        )
    if context.job_charge_rate is not None:
        return (
            context.job_charge_rate,
            describe(_("job rate"), context.job_charge_rate, unit),
            False,
        )
    listed = rules.price_lists.get(a.client_id or "")
    if listed is not None and listed[0].currency == currency:
        label = _("%(list)s price") % {"list": listed[1]}
        return listed[0], describe(label, listed[0], unit), False
    if rules.tier_affects_charge and context.tutors:
        tier = rules.tier_rates.get(context.tutors[0].tutor_id)
        rate = _same_currency(tier.charge_rate, currency) if tier else None
        if tier is not None and rate is not None:
            label = _("%(tier)s tier rate") % {"tier": tier.tier_name}
            return rate, describe(label, rate, unit), False
    return default, describe(_("service rate"), default, unit), False


def _charge_lines(
    context: RateContext,
    rules: PricingRules,
    currency: str,
    default: Money,
    premiums: list[Premium],
) -> list[ChargeLine]:
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
    charge_premiums = [
        p for p in premiums if p.charge_percent or _same_currency(p.charge_fixed, currency)
    ]

    picked = [_charge_rate(context, rules, a, currency, default) for a in attendees]
    applied: list[list[Adjustment]] = [[] for _a in attendees]
    if split and len({r for r, _l, _m in picked}) == 1:
        # Everyone has the same rate: price the whole lesson (with premiums) and split it
        # exactly, so the lines add up to the lesson total.
        total = (picked[0][0] * quantity).round_to_minor()
        lesson_premiums: list[Adjustment] = []
        if quantity and not picked[0][2]:
            base = total
            for p in charge_premiums:
                step = _premium_step(
                    base, p.charge_percent, _same_currency(p.charge_fixed, currency)
                )
                total = total + step
                lesson_premiums.append(Adjustment(p.name, step))
        amounts = total.allocate([1] * n)
        for i in range(n):
            shares = [adj.amount.allocate([1] * n)[i] for adj in lesson_premiums]
            applied[i] = [
                Adjustment(adj.name, share)
                for adj, share in zip(lesson_premiums, shares, strict=True)
            ]
    else:
        amounts = []
        for i, (rate, _label, manual) in enumerate(picked):
            amount = (
                (rate * quantity / n).round_to_minor()
                if split
                else ((rate * quantity).round_to_minor())
            )
            if quantity and not manual:
                base = amount
                for p in charge_premiums:
                    fixed = _same_currency(p.charge_fixed, currency)
                    if fixed is not None and split:
                        fixed = fixed / n
                    step = _premium_step(base, p.charge_percent, fixed)
                    amount = amount + step
                    applied[i].append(Adjustment(p.name, step))
            amounts.append(amount)

    lines = []
    for i, (a, (rate, label, manual), amount) in enumerate(
        zip(attendees, picked, amounts, strict=True)
    ):
        trace = [label]
        if unit == Service.PricingUnit.PER_HOUR:
            trace.append(_("%(minutes)s minutes") % {"minutes": context.duration_minutes})
        if split:
            trace.append(_("split between %(n)s students") % {"n": n})
        if quantity == 0:
            trace.append(_("billed by subscription, not per lesson"))
        for p in charge_premiums[: len(applied[i])]:
            fixed = _same_currency(p.charge_fixed, currency)
            trace.append(_percent_label(p.name, p.charge_percent, fixed, "+"))
        discounts: list[Adjustment] = []
        if quantity and not manual:
            amount, discounts = _apply_discounts(context, rules, a, amount, currency, trace)
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
                premiums=applied[i],
                discounts=discounts,
            )
        )
    return lines


def _apply_discounts(
    context: RateContext,
    rules: PricingRules,
    a: AttendeeInput,
    amount: Money,
    currency: str,
    trace: list[str],
) -> tuple[Money, list[Adjustment]]:
    facts = rules.attendee_facts.get(a.student_id, AttendeeFacts())
    matching = _pick([d for d in rules.discounts if discount_applies(d, context, a, facts)])
    applied: list[Adjustment] = []
    base = amount
    for d in matching:
        before = amount
        price = _same_currency(d.fixed_price, currency)
        if price is not None:
            amount = min(amount, price.round_to_minor())
            trace.append(_("%(name)s price %(price)s") % {"name": d.name, "price": price.format()})
        if d.percent:
            amount = amount - (base * (d.percent / HUNDRED)).round_to_minor()
        fixed = _same_currency(d.fixed_amount, currency)
        if fixed is not None:
            amount = amount - fixed.round_to_minor()
        if amount.is_negative():
            amount = Money.zero(currency)
        if d.percent or fixed is not None:
            trace.append(_percent_label(d.name, d.percent, fixed, "-"))
        if amount != before:
            applied.append(Adjustment(d.name, amount - before))
    return amount, applied


def _pay_rate(
    rules: PricingRules, t: TutorInput, currency: str, default: Money | None, unit: str
) -> tuple[Money | None, list[str], bool]:
    """(rate, trace, is_manual_override) by pay precedence; None rate = use the percent."""
    if t.rate_override is not None:
        return t.rate_override, [describe(_("lesson pay rate"), t.rate_override, unit)], True
    if t.job_rate_override is not None:
        return (
            t.job_rate_override,
            [describe(_("tutor's job rate"), t.job_rate_override, unit)],
            False,
        )
    personal = _same_currency(rules.tutor_rates.get(t.tutor_id), currency)
    if personal is not None:
        return personal, [describe(_("tutor's own rate"), personal, unit)], False
    tier = rules.tier_rates.get(t.tutor_id)
    tier_rate = _same_currency(tier.pay_rate, currency) if tier else None
    if tier is not None and tier_rate is not None:
        label = _("%(tier)s tier pay rate") % {"tier": tier.tier_name}
        return tier_rate, [describe(label, tier_rate, unit)], False
    if default is not None:
        return default, [describe(_("service pay rate"), default, unit)], False
    return None, [], False


def _pay_lines(
    context: RateContext,
    rules: PricingRules,
    currency: str,
    default: Money | None,
    percent: Decimal | None,
    total_charge: Money,
    premiums: list[Premium],
) -> list[PayLine]:
    service = context.service
    unit = service.pay_unit
    quantity = _quantity(unit, context.duration_minutes)
    tutors = list(context.tutors)
    picked = {t.tutor_id: _pay_rate(rules, t, currency, default, unit) for t in tutors}
    pay_premiums = [p for p in premiums if p.pay_percent or _same_currency(p.pay_fixed, currency)]
    lines: list[PayLine] = []
    # Percentage pay is shared between the lesson's tutors that have no rate.
    by_percent = [t for t in tutors if picked[t.tutor_id][0] is None] if percent is not None else []
    shares = (
        (total_charge * (percent / 100)).allocate([1] * len(by_percent))
        if by_percent and percent is not None
        else []
    )
    share_of = dict(zip((t.tutor_id for t in by_percent), shares, strict=True))
    for t in tutors:
        rate, trace, manual = picked[t.tutor_id]
        if rate is None and t.tutor_id in share_of:
            amount = share_of[t.tutor_id]
            trace = [_("%(percent)s%% of the lesson charge") % {"percent": _plain(percent)}]
            if rules.pay_percent_basis == "net":
                trace.append(_("after discounts"))
            if len(by_percent) > 1:
                trace.append(_("shared between %(n)s tutors") % {"n": len(by_percent)})
            line = PayLine(t.tutor_id, "percent", None, Decimal(1), amount, trace)
        elif rate is None:
            lines.append(
                PayLine(
                    t.tutor_id, unit, None, quantity, Money.zero(currency), [_("no pay rate set")]
                )
            )
            continue
        else:
            if unit == Service.PayUnit.PER_HOUR:
                trace.append(_("%(minutes)s minutes") % {"minutes": context.duration_minutes})
            line = PayLine(
                t.tutor_id, unit, rate, quantity, (rate * quantity).round_to_minor(), trace
            )
        if not manual and line.amount.is_positive():
            base = line.amount
            for p in pay_premiums:
                fixed = _same_currency(p.pay_fixed, currency)
                step = _premium_step(base, p.pay_percent, fixed)
                line.amount = line.amount + step
                line.premiums.append(Adjustment(p.name, step))
                line.trace.append(_percent_label(p.name, p.pay_percent, fixed, "+"))
        lines.append(line)
    return lines
