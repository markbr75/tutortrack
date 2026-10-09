"""Catalogue writes (E06). Every mutation is audited."""

from __future__ import annotations

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
    Level,
    Location,
    PackageTemplate,
    Product,
    Service,
    ServicePrice,
    Subject,
    TaxRate,
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
