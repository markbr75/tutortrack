"""Load the Phase 2 pricing rules for one lesson (E06-T07..T09).

``load_rules(...)`` reads price lists, pay tiers, tutor rates, premium and discount rules
and holiday calendars, and returns the ``rates.PricingRules`` the (pure) engine applies.
E08 calls it when pricing a lesson, passing each student's lesson history; the quote API
calls it for previews.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import Q

from . import rates
from .models import (
    DiscountRule,
    Holiday,
    PremiumRule,
    PriceListClient,
    PriceListItem,
    PromoCode,
    Service,
    ServiceTierRate,
    TutorPayTierAssignment,
    TutorServiceRate,
)


def _valid_on(day: date) -> Q:
    return (Q(valid_from__isnull=True) | Q(valid_from__lte=day)) & (
        Q(valid_to__isnull=True) | Q(valid_to__gte=day)
    )


def _ids(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(str(v) for v in values or ())


def _rate(instance: Any, name: str) -> Any:
    return getattr(instance, name) if getattr(instance, f"{name}_amount") is not None else None


def holiday_dates(branch_id: Any, start: date, end: date, *, skipping: bool = False) -> set[date]:
    """Dates in active holiday calendars for the organisation or ``branch_id``.
    ``skipping`` limits it to calendars that lesson series skip."""
    qs = Holiday.objects.filter(
        date__gte=start,
        date__lte=end,
        calendar__active=True,
    ).filter(Q(calendar__branch__isnull=True) | Q(calendar__branch_id=branch_id))
    if skipping:
        qs = qs.filter(calendar__skip_lessons=True)
    return set(qs.values_list("date", flat=True))


def has_date_rules() -> bool:
    """Whether any rule could price two occurrences of a series differently."""
    return (
        PremiumRule.objects.filter(active=True).exists()
        or DiscountRule.objects.filter(active=True).exclude(kind=DiscountRule.Kind.PROMO).exists()
        or TutorPayTierAssignment.objects.exists()
        or PriceListClient.objects.exists()
    )


def tier_for(tutor_id: Any, on: date) -> TutorPayTierAssignment | None:
    return (
        TutorPayTierAssignment.objects.select_related("tier")
        .filter(tutor_id=tutor_id, effective_from__lte=on)
        .order_by("-effective_from")
        .first()
    )


def premium_from(rule: PremiumRule) -> rates.Premium:
    return rates.Premium(
        name=rule.name,
        priority=rule.priority,
        stackable=rule.stackable,
        weekdays=tuple(int(d) for d in rule.weekdays or ()),
        time_from=rule.time_from,
        time_to=rule.time_to,
        public_holidays=rule.public_holidays,
        short_notice_hours=rule.short_notice_hours,
        location_types=_ids(rule.location_types),
        delivery=rule.delivery,
        subject_ids=_ids(rule.subjects),
        level_ids=_ids(rule.levels),
        service_ids=_ids(rule.services),
        min_students=rule.min_students,
        max_students=rule.max_students,
        charge_percent=rule.charge_percent,
        charge_fixed=_rate(rule, "charge_fixed") if rule.currency else None,
        pay_percent=rule.pay_percent,
        pay_fixed=_rate(rule, "pay_fixed") if rule.currency else None,
    )


def discount_from(rule: DiscountRule) -> rates.Discount:
    return rates.Discount(
        name=rule.name,
        kind=rule.kind,
        priority=rule.priority,
        stackable=rule.stackable,
        percent=rule.percent,
        fixed_amount=_rate(rule, "fixed_amount") if rule.currency else None,
        fixed_price=_rate(rule, "fixed_price") if rule.currency else None,
        sibling_from=rule.sibling_from,
        volume_min_lessons=rule.volume_min_lessons,
        client_id=str(rule.client_id) if rule.client_id else None,
        student_id=str(rule.student_id) if rule.student_id else None,
        service_ids=_ids(rule.services),
        promo=rule.kind == DiscountRule.Kind.PROMO,
    )


def sibling_positions(student_ids: Iterable[Any]) -> dict[str, int]:
    """Each student's position among their client's (non-archived) students, oldest
    record first: 1 for the first child, 2 for the second..."""
    from tutortrack.people.models import Student

    wanted = set()
    for value in student_ids:
        try:
            wanted.add(str(uuid.UUID(str(value))))
        except ValueError:
            continue  # a new student (online booking) has no family yet
    clients = Student.objects.filter(pk__in=wanted).values_list("client_id", flat=True)
    positions: dict[str, int] = {}
    family: dict[Any, int] = {}
    for pk, client_id in (
        Student.objects.filter(client_id__in=clients, archived_at__isnull=True)
        .order_by("client_id", "created_at", "pk")
        .values_list("pk", "client_id")
    ):
        family[client_id] = family.get(client_id, 0) + 1
        if str(pk) in wanted:
            positions[str(pk)] = family[client_id]
    return positions


def load_rules(
    *,
    service: Service,
    currency: str,
    start: datetime | None,
    timezone: str | None = None,
    branch_id: Any = None,
    location: Any = None,
    online: bool = False,
    attendees: Sequence[rates.AttendeeInput] = (),
    tutors: Sequence[rates.TutorInput] = (),
    booked_at: datetime | None = None,
    promo_code: PromoCode | None = None,
    history: dict[str, tuple[bool, int]] | None = None,  # student: (first lesson, in month)
) -> rates.PricingRules:
    from tutortrack.core.time import now
    from tutortrack.tenancy.settings_service import get_setting

    local = start.astimezone(ZoneInfo(timezone)) if start and timezone else start
    day = local.date() if local else now().date()

    price_lists: dict[str, tuple[Any, str]] = {}
    client_ids = {a.client_id for a in attendees if a.client_id}
    if client_ids:
        links = (
            PriceListClient.objects.filter(
                client_id__in=client_ids,
                price_list__active=True,
                price_list__currency=currency,
            )
            .filter(
                (Q(price_list__valid_from__isnull=True) | Q(price_list__valid_from__lte=day))
                & (Q(price_list__valid_to__isnull=True) | Q(price_list__valid_to__gte=day))
            )
            .select_related("price_list")
            .order_by("-price_list__created_at")
        )
        items = {
            item.price_list_id: item
            for item in PriceListItem.objects.filter(
                service=service, price_list__in={link.price_list_id for link in links}
            )
        }
        for link in links:
            item = items.get(link.price_list_id)
            if item is not None and str(link.client_id) not in price_lists:
                price_lists[str(link.client_id)] = (item.charge_rate, link.price_list.name)

    tier_rates: dict[str, rates.TierRate] = {}
    tutor_rates: dict[str, Any] = {}
    tutor_ids = [t.tutor_id for t in tutors]
    if tutor_ids and service.pk:
        for tutor_id in tutor_ids:
            assignment = tier_for(tutor_id, day)
            if assignment is None:
                continue
            row = ServiceTierRate.objects.filter(service=service, tier=assignment.tier).first()
            if row is not None:
                tier_rates[tutor_id] = rates.TierRate(
                    assignment.tier.name, _rate(row, "pay_rate"), _rate(row, "charge_rate")
                )
        for row in TutorServiceRate.objects.filter(service=service, tutor_id__in=tutor_ids):
            tutor_rates[str(row.tutor_id)] = row.pay_rate

    premiums = [premium_from(r) for r in PremiumRule.objects.filter(_valid_on(day), active=True)]
    discount_rules = list(
        DiscountRule.objects.filter(_valid_on(day), active=True).exclude(
            kind=DiscountRule.Kind.PROMO
        )
    )
    if promo_code is not None and promo_code.discount.active:
        discount_rules.append(promo_code.discount)
    discounts = [discount_from(r) for r in discount_rules]

    facts = rates.LessonFacts(
        local_start=local,
        is_holiday=bool(local and holiday_dates(branch_id, day, day)),
        notice_hours=(
            Decimal((start - booked_at).total_seconds()) / 3600 if start and booked_at else None
        ),
        location_type=getattr(location, "type", "") or ("online" if online else ""),
        online=online,
    )
    positions = sibling_positions(a.student_id for a in attendees) if discounts else {}
    attendee_facts = {
        a.student_id: rates.AttendeeFacts(
            sibling_position=positions.get(a.student_id, 1),
            first_lesson=(history or {}).get(a.student_id, (False, 0))[0],
            lessons_in_month=(history or {}).get(a.student_id, (False, 0))[1],
        )
        for a in attendees
    }
    return rates.PricingRules(
        price_lists=price_lists,
        tier_rates=tier_rates,
        tier_affects_charge=bool(get_setting("pricing.tier_affects_charge")),
        tutor_rates=tutor_rates,
        premiums=premiums,
        discounts=discounts,
        facts=facts,
        attendee_facts=attendee_facts,
        pay_percent_basis=str(get_setting("pricing.pay_percent_basis")),
    )
