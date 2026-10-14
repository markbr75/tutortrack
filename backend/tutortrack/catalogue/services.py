"""Catalogue writes (E06). Every mutation is audited."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import models, transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.time import now

from . import events, seed_data
from .models import (
    Category,
    DiscountRule,
    Holiday,
    HolidayCalendar,
    Level,
    Location,
    PackageTemplate,
    PayTier,
    PremiumRule,
    PriceList,
    PriceListClient,
    PriceListItem,
    Product,
    PromoCode,
    PromoRedemption,
    Room,
    RoomResource,
    Service,
    ServicePrice,
    ServiceTierRate,
    Subject,
    TaxRate,
    TutorPayTierAssignment,
    TutorServiceRate,
)


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def _create(model: type[models.Model], **data: Any) -> Any:
    m2m = {k: data.pop(k) for k in list(data) if k in {"branches", "services"}}
    instance = model(**data)
    instance.save()
    for name, values in m2m.items():
        getattr(instance, name).set(values)
    audit.record_create(instance)
    return instance


def _update(instance: models.Model, changes: dict[str, Any]) -> list[str]:
    m2m = {k: changes.pop(k) for k in list(changes) if k in {"branches", "services"}}
    changed = [k for k, v in changes.items() if getattr(instance, k) != v]
    with audit.track(instance):
        for k, v in changes.items():
            setattr(instance, k, v)
        instance.save()
    for name, values in m2m.items():
        getattr(instance, name).set(values)
        changed.append(name)
    return changed


@transaction.atomic
def discard_imported_service(service: Service) -> None:
    """Delete a service an import created when the import is rolled back (E28); services
    already used by jobs or lessons are protected and kept."""
    audit.record(service, "delete", {"reason": [None, "import rolled back"]})
    try:
        with transaction.atomic():
            service.delete()
    except (models.ProtectedError, models.RestrictedError) as exc:
        raise BusinessRuleViolation(_("It is in use, so it was kept.")) from exc


# --- starter data -------------------------------------------------------------------------------


@transaction.atomic
def seed_catalogue(country: str | None = None) -> None:
    """Starter categories, subjects, levels and tax rates for the organisation in context.
    Idempotent: does nothing for parts the organisation already has."""
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    if country is None:
        country = Organisation.objects.get(pk=require_organisation_id()).country
    if not Subject.objects.exists():
        categories = {
            name: Category.objects.create(name=name, order=i)
            for i, name in enumerate(seed_data.CATEGORIES)
        }
        for i, (name, category, levels, boards) in enumerate(seed_data.subjects_for(country)):
            subject = Subject.objects.create(
                name=name, category=categories[category], order=i, exam_boards=boards
            )
            for j, lvl in enumerate(levels):
                Level.objects.create(subject=subject, name=lvl, order=j)
    if not TaxRate.objects.exists():
        for name, percent, default, reason in seed_data.tax_rates_for(country):
            TaxRate.objects.create(
                name=name,
                percent=Decimal(percent),
                is_default=default,
                exempt_reason=reason,
                country=country.upper()[:2],
            )


# --- taxonomy -----------------------------------------------------------------------------------


@transaction.atomic
def save_category(category: Category | None, **data: Any) -> Category:
    if category is None:
        return _create(Category, **data)
    _update(category, data)
    return category


@transaction.atomic
def save_subject(subject: Subject | None, **data: Any) -> Subject:
    boards = data.get("exam_boards")
    if boards is not None:
        data["exam_boards"] = sorted({str(b).strip() for b in boards if str(b).strip()})
    if subject is None:
        return _create(Subject, **data)
    _update(subject, data)
    return subject


@transaction.atomic
def save_level(level: Level | None, **data: Any) -> Level:
    if level is None:
        return _create(Level, **data)
    data.pop("subject", None)  # levels don't move between subjects
    _update(level, data)
    return level


@transaction.atomic
def set_archived(instance: Any, archived: bool) -> Any:
    """Archive or restore a category, subject, level or location. Archived items stay on
    existing records but can't be chosen for new ones."""
    with audit.track(instance, action="archive" if archived else "restore"):
        instance.archived_at = now() if archived else None
        instance.save(update_fields=["archived_at", "updated_at"])
    if isinstance(instance, Subject):
        instance.levels.filter(archived_at__isnull=archived).update(
            archived_at=instance.archived_at
        )
    return instance


# --- tax rates ----------------------------------------------------------------------------------


@transaction.atomic
def save_tax_rate(rate: TaxRate | None, **data: Any) -> TaxRate:
    percent = data.get("percent")
    if percent is not None and not (Decimal(0) <= Decimal(percent) <= Decimal(100)):
        raise _invalid("percent", _("Enter a percentage between 0 and 100."))
    if data.get("is_default"):
        others = TaxRate.objects.filter(is_default=True)
        if rate is not None:
            others = others.exclude(pk=rate.pk)
        for other in others:
            with audit.track(other):
                other.is_default = False
                other.save(update_fields=["is_default", "updated_at"])
    if rate is None:
        return _create(TaxRate, **data)
    _update(rate, data)
    return rate


def default_tax_rate() -> TaxRate | None:
    return TaxRate.objects.filter(is_default=True, active=True).first()


# --- services -----------------------------------------------------------------------------------

SERVICE_RATE_FIELDS = {"charge_rate", "pay_rate", "pay_percent"}


def _check_service(service: Service) -> None:
    if service.level is not None and service.level.subject_id != service.subject_id:
        raise _invalid("level", _("Choose a level of the service's subject."))
    if service.pay_rate is not None and service.pay_percent is not None:
        raise _invalid("pay_rate", _("Use a pay rate or a percentage of the charge, not both."))
    if service.pay_percent is not None and not (0 <= service.pay_percent <= 100):
        raise _invalid("pay_percent", _("Enter a percentage between 0 and 100."))
    if service.pay_rate is not None and service.pay_rate.currency != service.currency:
        raise _invalid("pay_rate", _("Pay and charge rates must use the same currency."))
    for name in ("charge_rate", "pay_rate"):
        value = getattr(service, name)
        if value is not None and value.is_negative():
            raise _invalid(name, _("Rates can't be negative."))
    if service.format == Service.Format.ONE_TO_ONE:
        service.max_students = 1
    elif service.max_students < 2:
        raise _invalid("max_students", _("Group services need room for at least 2 students."))
    durations = sorted({int(d) for d in service.allowed_durations or []})
    if any(d < 5 or d > 600 for d in durations):
        raise _invalid("allowed_durations", _("Durations are between 5 and 600 minutes."))
    service.allowed_durations = durations
    if durations and service.default_duration_minutes not in durations:
        raise _invalid(
            "default_duration_minutes", _("The default duration must be one of the allowed ones.")
        )


def _assign_rates(service: Service, data: dict[str, Any]) -> None:
    """Money fields carry the currency; the charge rate sets the service currency."""
    charge = data.pop("charge_rate", None)
    if charge is not None:
        service.currency = charge.currency
        service.charge_rate = charge
    if "pay_rate" in data:
        pay: Money | None = data.pop("pay_rate")
        if pay is not None and pay.currency != service.currency:
            raise _invalid("pay_rate", _("Pay and charge rates must use the same currency."))
        service.pay_rate = pay


@transaction.atomic
def create_service(**data: Any) -> Service:
    branches = data.pop("branches", [])
    if "tax_rate" not in data:
        data["tax_rate"] = default_tax_rate()
    service = Service()
    _assign_rates(service, data)
    for k, v in data.items():
        setattr(service, k, v)
    _check_service(service)
    service.save()
    service.branches.set(branches)
    audit.record_create(service)
    publish(events.ServiceCreated(subject_id=service.pk))
    return service


@transaction.atomic
def update_service(service: Service, **changes: Any) -> Service:
    branches = changes.pop("branches", None)
    old = (service.charge_rate, service.pay_rate, service.pay_percent)
    with audit.track(service):
        _assign_rates(service, changes)
        for k, v in changes.items():
            setattr(service, k, v)
        _check_service(service)
        service.save()
    if branches is not None:
        service.branches.set(branches)
    rate_changed = old != (service.charge_rate, service.pay_rate, service.pay_percent)
    fields = sorted(set(changes) | ({"rates"} if rate_changed else set()))
    publish(events.ServiceUpdated(subject_id=service.pk, fields=fields, rate_changed=rate_changed))
    return service


@transaction.atomic
def set_service_price(
    service: Service,
    *,
    charge_rate: Money,
    pay_rate: Money | None = None,
    pay_percent: Decimal | None = None,
) -> ServicePrice:
    """Price in another currency (FR-06-12). One per currency."""
    if charge_rate.currency == service.currency:
        raise _invalid("charge_rate", _("This is the service's own currency; edit the service."))
    if pay_rate is not None and pay_percent is not None:
        raise _invalid("pay_rate", _("Use a pay rate or a percentage of the charge, not both."))
    if pay_rate is not None and pay_rate.currency != charge_rate.currency:
        raise _invalid("pay_rate", _("Pay and charge rates must use the same currency."))
    price = ServicePrice.objects.filter(service=service, currency=charge_rate.currency).first()
    created = price is None
    price = price or ServicePrice(service=service)
    with audit.track(price):
        price.charge_rate = charge_rate
        price.pay_rate = pay_rate
        price.pay_percent = pay_percent
        price.save()
    if created:
        audit.record_create(price)
    return price


# --- locations, products, packages ----------------------------------------------------------------


@transaction.atomic
def save_location(location: Location | None, **data: Any) -> Location:
    from tutortrack.people.services import save_address

    address_data = data.pop("address_data", None)
    if data.get("type") == Location.Type.ONLINE and address_data:
        raise _invalid("address", _("Online locations don't have an address."))
    if location is None:
        location = Location(**data)
        location.address = save_address(None, address_data)
        location.save()
        audit.record_create(location)
        return location
    data["address"] = save_address(location.address, address_data)
    _update(location, data)
    return location


def _check_money(name: str, value: Money | None) -> None:
    if value is not None and value.is_negative():
        raise _invalid(name, _("Prices can't be negative."))


@transaction.atomic
def save_product(product: Product | None, **data: Any) -> Product:
    _check_money("price", data.get("price"))
    share = data.get("tutor_share_percent")
    if share is not None and not (0 <= share <= 100):
        raise _invalid("tutor_share_percent", _("Enter a percentage between 0 and 100."))
    if product is None:
        data.setdefault("tax_rate", default_tax_rate())
        return _create(Product, **data)
    if "price" in data:
        product.currency = data["price"].currency
    _update(product, data)
    return product


@transaction.atomic
def save_package(package: PackageTemplate | None, **data: Any) -> PackageTemplate:
    _check_money("price", data.get("price"))
    if data.get("validity_days") is not None and data.get("valid_until") is not None:
        raise _invalid("validity_days", _("Use days from purchase or an end date, not both."))
    if package is None:
        data.setdefault("tax_rate", default_tax_rate())
        return _create(PackageTemplate, **data)
    if "price" in data:
        package.currency = data["price"].currency
    _update(package, data)
    return package


# --- rooms (FR-06-10, E06-T10) ------------------------------------------------------------------


@transaction.atomic
def save_room(
    room: Room | None, *, resources: list[dict[str, Any]] | None = None, **data: Any
) -> Room:
    location = data.get("location") or (room.location if room else None)
    if location is not None and location.type == Location.Type.ONLINE:
        raise _invalid("location", _("Online locations don't have rooms."))
    name = data.get("name")
    if name is not None:
        clash = Room.objects.filter(location=location, name__iexact=name.strip())
        if room is not None:
            clash = clash.exclude(pk=room.pk)
        if clash.exists():
            raise _invalid("name", _("This location already has a room with that name."))
    if room is None:
        room = _create(Room, **data)
    else:
        data.pop("location", None)  # rooms don't move between locations
        _update(room, data)
    if resources is not None:
        names = [str(r["name"]).strip() for r in resources if str(r.get("name", "")).strip()]
        if len({n.lower() for n in names}) != len(names):
            raise _invalid("resources", _("A resource is listed twice."))
        room.resources.exclude(name__in=names).delete()
        for row in resources:
            label = str(row.get("name", "")).strip()
            if label:
                RoomResource.objects.update_or_create(
                    room=room, name=label, defaults={"quantity": int(row.get("quantity") or 1)}
                )
        audit.record(room, "update", {"resources": [None, names]})
    return room


# --- pay tiers and tutor rates (FR-06-5, E06-T07) -------------------------------------------------


@transaction.atomic
def save_pay_tier(tier: PayTier | None, **data: Any) -> PayTier:
    name = data.get("name")
    if name is not None:
        clash = PayTier.objects.filter(name__iexact=name.strip())
        if tier is not None:
            clash = clash.exclude(pk=tier.pk)
        if clash.exists():
            raise _invalid("name", _("There is already a tier with that name."))
    if tier is None:
        return _create(PayTier, **data)
    _update(tier, data)
    return tier


def _same_currency(service: Service, name: str, value: Money | None) -> None:
    if value is None:
        return
    if value.currency != service.currency:
        raise _invalid(
            name,
            _("%(service)s is priced in %(currency)s.")
            % {"service": service.name, "currency": service.currency},
        )
    if value.is_negative():
        raise _invalid(name, _("Rates can't be negative."))


@transaction.atomic
def set_tier_rate(
    service: Service,
    tier: PayTier,
    *,
    pay_rate: Money | None,
    charge_rate: Money | None = None,
) -> ServiceTierRate | None:
    """Set (or, with neither rate, remove) a service's rates for a tier."""
    _same_currency(service, "pay_rate", pay_rate)
    _same_currency(service, "charge_rate", charge_rate)
    row = ServiceTierRate.objects.filter(service=service, tier=tier).first()
    if pay_rate is None and charge_rate is None:
        if row is not None:
            audit.record(row, "delete", {"pay_rate": [str(row.pay_rate), None]})
            row.delete()
        return None
    created = row is None
    row = row or ServiceTierRate(service=service, tier=tier, currency=service.currency)
    with audit.track(row):
        row.pay_rate = pay_rate
        row.charge_rate = charge_rate
        row.save()
    if created:
        audit.record_create(row)
    publish(
        events.PricingChanged(
            subject_id=service.pk, kind="tier_rate", service_ids=[str(service.pk)]
        )
    )
    return row


TIER_CSV_COLUMNS = ["service", "tier", "pay_rate", "charge_rate", "currency"]


def tier_rates_csv() -> str:
    """The services by tiers grid as CSV (FR-06-5 bulk edit)."""
    import csv
    import io

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(TIER_CSV_COLUMNS)
    rows = {
        (r.service_id, r.tier_id): r
        for r in ServiceTierRate.objects.select_related("service", "tier")
    }
    tiers = list(PayTier.objects.filter(archived_at__isnull=True))
    for service in Service.objects.filter(active=True).order_by("name"):
        for tier in tiers:
            row = rows.get((service.pk, tier.pk))
            writer.writerow(
                [
                    service.name,
                    tier.name,
                    "" if row is None or row.pay_rate is None else f"{row.pay_rate.amount:f}",
                    "" if row is None or row.charge_rate is None else f"{row.charge_rate.amount:f}",
                    service.currency,
                ]
            )
    return out.getvalue()


@dataclass
class TierImportResult:
    updated: int = 0
    unchanged: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


def _decimal_cell(value: str) -> Decimal | None:
    from decimal import InvalidOperation

    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(_("“%(value)s” is not a number.") % {"value": value}) from exc
    if amount < 0:
        raise ValueError(_("Rates can't be negative."))
    return amount


@transaction.atomic
def import_tier_rates(text: str, *, dry_run: bool = False) -> TierImportResult:
    """Bulk-set tier rates from CSV (columns as in ``tier_rates_csv``). All rows are
    checked first; nothing is saved if any row has an error."""
    import csv
    import io

    reader = csv.DictReader(io.StringIO(text))
    missing = {"service", "tier", "pay_rate"} - set(reader.fieldnames or [])
    if missing:
        raise _invalid("file", _("Missing columns: %(c)s") % {"c": ", ".join(sorted(missing))})
    services_by_name = {s.name.lower(): s for s in Service.objects.all()}
    tiers_by_name = {t.name.lower(): t for t in PayTier.objects.all()}
    result = TierImportResult()
    planned: list[tuple[Service, PayTier, Money | None, Money | None]] = []
    for number, row in enumerate(reader, start=2):
        service = services_by_name.get((row.get("service") or "").strip().lower())
        tier = tiers_by_name.get((row.get("tier") or "").strip().lower())
        if service is None or tier is None:
            result.errors.append({"row": number, "error": _("Unknown service or tier.")})
            continue
        try:
            pay = _decimal_cell(row.get("pay_rate", ""))
            charge = _decimal_cell(row.get("charge_rate", ""))
        except ValueError as exc:
            result.errors.append({"row": number, "error": str(exc)})
            continue
        currency = (row.get("currency") or service.currency).strip().upper()
        if currency != service.currency:
            result.errors.append(
                {"row": number, "error": _("%(s)s is priced in %(c)s.") % {
                    "s": service.name, "c": service.currency}}
            )  # fmt: skip
            continue
        planned.append(
            (
                service,
                tier,
                Money(pay, currency) if pay is not None else None,
                Money(charge, currency) if charge is not None else None,
            )
        )
    if result.errors or dry_run:
        result.updated = 0 if result.errors else len(planned)
        return result
    for service, tier, pay_rate, charge_rate in planned:
        existing = ServiceTierRate.objects.filter(service=service, tier=tier).first()
        same = (existing is None and pay_rate is None and charge_rate is None) or (
            existing is not None
            and existing.pay_rate == pay_rate
            and existing.charge_rate == charge_rate
        )
        if same:
            result.unchanged += 1
            continue
        set_tier_rate(service, tier, pay_rate=pay_rate, charge_rate=charge_rate)
        result.updated += 1
    return result


@transaction.atomic
def assign_tier(
    tutor: Any,
    tier: PayTier,
    *,
    effective_from: date,
    note: str = "",
    recalculate: bool = False,
) -> TutorPayTierAssignment:
    """Put a tutor on a tier from ``effective_from``. With ``recalculate``, E08 re-prices
    the tutor's unlocked lessons on or after that date (the retroactive tool)."""
    if tier.archived_at is not None:
        raise _invalid("tier", _("This tier is archived."))
    assignment, created = TutorPayTierAssignment.objects.get_or_create(
        tutor=tutor, effective_from=effective_from, defaults={"tier": tier, "note": note[:300]}
    )
    if created:
        audit.record_create(assignment)
    else:
        with audit.track(assignment):
            assignment.tier, assignment.note = tier, note[:300]
            assignment.save()
    publish(
        events.TutorTierAssigned(
            subject_id=assignment.pk,
            tutor_id=str(tutor.pk),
            tier_id=str(tier.pk),
            effective_from=effective_from.isoformat(),
            recalculate=recalculate,
        )
    )
    return assignment


@transaction.atomic
def delete_imported_tier(tier: PayTier) -> None:
    """An E28 import is rolled back (G6): a tier it created goes while nobody is on it."""
    if tier.assignments.exists():
        raise _invalid("tier", _("Tutors are on this tier."))
    audit.record(tier, "delete", {"name": [tier.name, None]})
    ServiceTierRate.objects.filter(tier=tier).delete()
    tier.delete()


@transaction.atomic
def remove_tier_assignment(assignment: TutorPayTierAssignment) -> None:
    audit.record(assignment, "delete", {"tier": [str(assignment.tier_id), None]})
    assignment.delete()


@transaction.atomic
def set_tutor_rate(tutor: Any, service: Service, pay_rate: Money | None) -> TutorServiceRate | None:
    """A tutor's personal pay rate for a service; ``None`` removes it."""
    _same_currency(service, "pay_rate", pay_rate)
    row = TutorServiceRate.objects.filter(tutor=tutor, service=service).first()
    if pay_rate is None:
        if row is not None:
            audit.record(row, "delete", {"pay_rate": [str(row.pay_rate), None]})
            row.delete()
        return None
    created = row is None
    row = row or TutorServiceRate(tutor=tutor, service=service, currency=service.currency)
    with audit.track(row):
        row.pay_rate = pay_rate
        row.save()
    if created:
        audit.record_create(row)
    publish(
        events.PricingChanged(
            subject_id=service.pk, kind="tutor_rate", service_ids=[str(service.pk)]
        )
    )
    return row


# --- holiday calendars and premiums (FR-06-6, E06-T08) --------------------------------------------


@transaction.atomic
def save_holiday_calendar(calendar: HolidayCalendar | None, **data: Any) -> HolidayCalendar:
    if calendar is None:
        return _create(HolidayCalendar, **data)
    _update(calendar, data)
    return calendar


@transaction.atomic
def add_holiday(calendar: HolidayCalendar, *, day: date, name: str) -> Holiday:
    holiday, created = Holiday.objects.update_or_create(
        calendar=calendar, date=day, defaults={"name": name[:100]}
    )
    if created:
        audit.record_create(holiday)
    publish(events.PricingChanged(subject_id=calendar.pk, kind="holiday"))
    return holiday


@transaction.atomic
def delete_holiday(holiday: Holiday) -> None:
    audit.record(holiday, "delete", {"date": [str(holiday.date), None]})
    holiday.delete()


@transaction.atomic
def import_public_holidays(calendar: HolidayCalendar, year: int) -> int:
    """Add the country's public holidays for ``year`` (GB: England and Wales; US:
    federal). Returns how many were added."""
    from . import holidays

    added = 0
    for day, name in holidays.public_holidays(calendar.country or "GB", year):
        _holiday, created = Holiday.objects.get_or_create(
            calendar=calendar, date=day, defaults={"name": name}
        )
        added += int(created)
    if added:
        audit.record(calendar, "update", {"holidays": [None, f"{added} added for {year}"]})
    return added


def _check_window(data: dict[str, Any]) -> None:
    start, end = data.get("valid_from"), data.get("valid_to")
    if start and end and end < start:
        raise _invalid("valid_to", _("The end date is before the start date."))


def _check_percent(name: str, value: Decimal | None, *, limit: int = 1000) -> None:
    if value is not None and not (Decimal(0) <= value <= limit):
        raise _invalid(name, _("Enter a percentage between 0 and %(n)s.") % {"n": limit})


def _money_fields(rule: Any, data: dict[str, Any], names: tuple[str, ...]) -> None:
    """Fixed amounts carry the currency; all of a rule's amounts share one."""
    values = {n: data.pop(n) for n in names if n in data}
    currencies = {v.currency for v in values.values() if v is not None}
    if len(currencies) > 1:
        raise _invalid(names[0], _("Use one currency for the amounts."))
    for name, value in values.items():
        if value is not None and value.is_negative():
            raise _invalid(name, _("Amounts can't be negative."))
    if currencies:
        rule.currency = currencies.pop()
    for name, value in values.items():
        setattr(rule, f"{name}_amount", None if value is None else value.amount)


@transaction.atomic
def save_premium(rule: PremiumRule | None, **data: Any) -> PremiumRule:
    _check_window(data)
    for name in ("charge_percent", "pay_percent"):
        _check_percent(name, data.get(name))
    weekdays = data.get("weekdays")
    if weekdays is not None:
        if any(int(d) not in range(7) for d in weekdays):
            raise _invalid("weekdays", _("Days are 0 (Monday) to 6 (Sunday)."))
        data["weekdays"] = sorted({int(d) for d in weekdays})
    created = rule is None
    rule = rule or PremiumRule()
    with audit.track(rule):
        _money_fields(rule, data, ("charge_fixed", "pay_fixed"))
        for k, v in data.items():
            setattr(rule, k, v)
        fixed = [getattr(rule, f"{n}_amount") for n in ("charge_fixed", "pay_fixed")]
        if not any([rule.charge_percent, rule.pay_percent, *fixed]):
            raise _invalid("charge_percent", _("Add a charge or pay premium."))
        rule.save()
    if created:
        audit.record_create(rule)
    publish(events.PricingChanged(subject_id=rule.pk, kind="premium"))
    return rule


# --- discounts, promo codes and price lists (FR-06-7, FR-06-11, E06-T09) -------------------------


@transaction.atomic
def save_discount(rule: DiscountRule | None, **data: Any) -> DiscountRule:
    _check_window(data)
    _check_percent("percent", data.get("percent"), limit=100)
    created = rule is None
    rule = rule or DiscountRule()
    with audit.track(rule):
        _money_fields(rule, data, ("fixed_amount", "fixed_price"))
        for k, v in data.items():
            setattr(rule, k, v)
        fixed = [getattr(rule, f"{n}_amount") for n in ("fixed_amount", "fixed_price")]
        if not (rule.percent or any(v is not None for v in fixed)):
            raise _invalid("percent", _("Give a percentage, an amount off or a fixed price."))
        kind = DiscountRule.Kind
        if rule.kind == kind.VOLUME and not rule.volume_min_lessons:
            raise _invalid("volume_min_lessons", _("Say how many lessons a month qualify."))
        if rule.kind == kind.CLIENT and rule.client_id is None:
            raise _invalid("client", _("Choose the client."))
        if rule.kind == kind.SCHOLARSHIP and rule.client_id is None and rule.student_id is None:
            raise _invalid("student", _("Choose the student or client."))
        if rule.kind == kind.MULTI_CLASS and (rule.min_classes or 0) < 2:
            raise _invalid("min_classes", _("Say from how many classes in a term it applies."))
        if rule.kind == kind.SIBLING and rule.sibling_from < 2:
            raise _invalid("sibling_from", _("Siblings start from the second student."))
        rule.save()
    if created:
        audit.record_create(rule)
    publish(events.PricingChanged(subject_id=rule.pk, kind="discount"))
    return rule


def normalise_code(code: str) -> str:
    return "".join(code.split()).upper()


@transaction.atomic
def save_promo_code(promo: PromoCode | None, **data: Any) -> PromoCode:
    _check_window(data)
    if "code" in data:
        data["code"] = normalise_code(data["code"])
        if not data["code"]:
            raise _invalid("code", _("Enter a code."))
        clash = PromoCode.objects.filter(code=data["code"])
        if promo is not None:
            clash = clash.exclude(pk=promo.pk)
        if clash.exists():
            raise _invalid("code", _("That code is already in use."))
    discount = data.get("discount")
    if discount is not None and discount.kind != DiscountRule.Kind.PROMO:
        raise _invalid("discount", _("Choose a promo-code discount."))
    if promo is None:
        return _create(PromoCode, **data)
    _update(promo, data)
    return promo


class PromoInvalid(BusinessRuleViolation):
    problem_type = "promo-code-invalid"
    title = "That code can't be used"


def check_promo(code: str, *, client: Any = None, service: Service | None = None) -> PromoCode:
    """The usable promo code for this booking, or ``PromoInvalid``."""
    from tutortrack.core.time import now

    promo = (
        PromoCode.objects.select_related("discount")
        .filter(code=normalise_code(code), active=True, discount__active=True)
        .first()
    )
    message = _("This code isn't valid.")
    if promo is None:
        raise PromoInvalid(message, extra={"errors": {"promo_code": [message]}})
    today = now().date()
    expired = (promo.valid_from and today < promo.valid_from) or (
        promo.valid_to and today > promo.valid_to
    )
    used_up = promo.max_uses is not None and promo.uses >= promo.max_uses
    wrong_service = (
        service is not None
        and promo.discount.services
        and str(service.pk) not in [str(s) for s in promo.discount.services]
    )
    if expired or used_up or wrong_service:
        message = _("This code has expired or can't be used for this booking.")
        raise PromoInvalid(message, extra={"errors": {"promo_code": [message]}})
    if client is not None:
        used = promo.redemptions.filter(client=client).count()
        if promo.max_uses_per_client is not None and used >= promo.max_uses_per_client:
            message = _("You've already used this code.")
            raise PromoInvalid(message, extra={"errors": {"promo_code": [message]}})
        if promo.new_clients_only and _has_lessons(client):
            message = _("This code is for new clients.")
            raise PromoInvalid(message, extra={"errors": {"promo_code": [message]}})
    return promo


def _has_lessons(client: Any) -> bool:
    from tutortrack.scheduling.selectors import client_has_lessons

    return client_has_lessons(client)


@transaction.atomic
def redeem_promo(promo: PromoCode, *, client: Any = None, reference: str = "") -> bool:
    """Count one use (idempotent per ``reference``)."""
    _redemption, created = PromoRedemption.objects.get_or_create(
        promo_code=promo, reference=reference[:100], defaults={"client": client}
    )
    if created:
        PromoCode.objects.filter(pk=promo.pk).update(uses=models.F("uses") + 1)
        audit.record(promo, "redeem", {"reference": [None, reference[:100]]})
    return created


@transaction.atomic
def save_price_list(
    price_list: PriceList | None,
    *,
    items: list[dict[str, Any]] | None = None,
    clients: list[Any] | None = None,
    **data: Any,
) -> PriceList:
    _check_window(data)
    if price_list is None:
        price_list = _create(PriceList, **data)
    else:
        if (
            "currency" in data
            and data["currency"] != price_list.currency
            and (items is None and price_list.items.exists())
        ):
            raise _invalid("currency", _("Re-enter the prices to change the currency."))
        _update(price_list, data)
    if items is not None:
        services_seen: set[Any] = set()
        for row in items:
            rate: Money = row["charge_rate"]
            if rate.currency != price_list.currency or rate.is_negative():
                raise _invalid(
                    "items",
                    _("Use non-negative prices in %(c)s.") % {"c": price_list.currency},
                )
            if row["service"].pk in services_seen:
                raise _invalid("items", _("A service is listed twice."))
            services_seen.add(row["service"].pk)
        price_list.items.exclude(service__in=services_seen).delete()
        for row in items:
            PriceListItem.objects.update_or_create(
                price_list=price_list,
                service=row["service"],
                defaults={
                    "currency": price_list.currency,
                    "charge_rate_amount": row["charge_rate"].amount,
                },
            )
        audit.record(price_list, "update", {"items": [None, len(items)]})
    if clients is not None:
        ids = {c.pk for c in clients}
        price_list.clients.exclude(client_id__in=ids).delete()
        for client in clients:
            PriceListClient.objects.get_or_create(price_list=price_list, client=client)
        audit.record(price_list, "update", {"clients": [None, [str(i) for i in ids]]})
    publish(events.PricingChanged(subject_id=price_list.pk, kind="price_list"))
    return price_list
