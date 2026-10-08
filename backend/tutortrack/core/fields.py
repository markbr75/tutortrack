"""Model fields for money, rates and currencies.

``MoneyField`` stores the amount in a ``<name>_amount`` NUMERIC column and reads the
currency from a sibling ``CurrencyField`` named by ``currency_field``. Many records share a
single currency (an invoice and all its totals), so the currency column is declared
explicitly on the model rather than generated:

    class Invoice(TenantModel):
        currency = CurrencyField()
        subtotal = MoneyField(currency_field="currency")
        total = MoneyField(currency_field="currency")

``invoice.total`` returns a ``Money``; ``invoice.total_amount`` is the raw Decimal, which
Django internals use, so querysets, ``values()`` and migrations all behave normally.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from .money import CurrencyMismatch, Money, validate_currency


def _validate_currency(value: str) -> None:
    try:
        validate_currency(value)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


class CurrencyField(models.CharField):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 3)
        super().__init__(*args, **kwargs)
        self.validators.append(_validate_currency)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return value.upper() if isinstance(value, str) else value


class MoneyDescriptor:
    """Exposes ``Money`` at the field name, backed by the ``<name>_amount`` attribute."""

    def __init__(self, field: MoneyField):
        self.field = field

    def __get__(self, instance: models.Model | None, owner: type | None = None) -> Any:
        if instance is None:
            return self
        amount = getattr(instance, self.field.attname)
        if amount is None:
            return None
        currency = getattr(instance, self.field.currency_field)
        if not currency:
            raise ValueError(
                f"{type(instance).__name__}.{self.field.currency_field} must be set before "
                f"reading {self.field.name}"
            )
        return Money(amount, currency)

    def __set__(self, instance: models.Model, value: Any) -> None:
        if value is None:
            setattr(instance, self.field.attname, None)
            return
        if not isinstance(value, Money):
            raise TypeError(
                f"Assign a Money to {self.field.name}, or a Decimal to {self.field.attname}"
            )
        current = instance.__dict__.get(self.field.currency_field)
        if current and current != value.currency:
            raise CurrencyMismatch(
                f"{self.field.name} is {current} but a {value.currency} amount was assigned"
            )
        setattr(instance, self.field.currency_field, value.currency)
        setattr(instance, self.field.attname, value.amount)


class MoneyField(models.DecimalField):
    """Decimal amount column whose Python value is exposed as ``Money``."""

    def __init__(
        self,
        *args: Any,
        currency_field: str = "currency",
        max_digits: int = 14,
        decimal_places: int = 2,
        **kwargs: Any,
    ) -> None:
        self.currency_field = currency_field
        kwargs["max_digits"] = max_digits
        kwargs["decimal_places"] = decimal_places
        super().__init__(*args, **kwargs)

    def get_attname(self) -> str:
        return f"{self.name}_amount"

    def contribute_to_class(
        self, cls: type[models.Model], name: str, private_only: bool = False
    ) -> None:
        super().contribute_to_class(cls, name, private_only=private_only)
        setattr(cls, name, MoneyDescriptor(self))

    def deconstruct(self) -> Any:
        name, path, args, kwargs = super().deconstruct()
        kwargs["currency_field"] = self.currency_field
        if kwargs.get("max_digits") == 14:
            kwargs.pop("max_digits")
        if kwargs.get("decimal_places") == 2 and type(self) is MoneyField:
            kwargs.pop("decimal_places")
        return name, path, args, kwargs

    def get_prep_value(self, value: Any) -> Any:
        if isinstance(value, Money):
            value = value.amount
        return super().get_prep_value(value)

    def to_python(self, value: Any) -> Any:
        if isinstance(value, Money):
            value = value.amount
        return super().to_python(value)

    def pre_save(self, model_instance: models.Model, add: bool) -> Any:
        value = getattr(model_instance, self.attname)
        if value is not None and isinstance(value, Decimal):
            exponent = value.as_tuple().exponent
            if isinstance(exponent, int) and -exponent > self.decimal_places:
                # Never let the database silently round money: services must round first.
                raise ValueError(
                    f"{type(model_instance).__name__}.{self.name}={value} has more than "
                    f"{self.decimal_places} decimal places; round it before saving"
                )
        return value


class RateField(MoneyField):
    """A price or pay rate: like MoneyField but with 4 decimal places (e.g. £33.3333/h)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("decimal_places", 4)
        super().__init__(*args, **kwargs)

    def deconstruct(self) -> Any:
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get("decimal_places") == 4:
            kwargs.pop("decimal_places")
        return name, path, args, kwargs
