"""Concrete models used only by the core test suite (installed in test settings only)."""

from typing import ClassVar

from django.db import models

from tutortrack.core.fields import CurrencyField, MoneyField, RateField
from tutortrack.core.models import ArchivableModel, TenantModel


class Gadget(TenantModel):
    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Widget(ArchivableModel):
    name = models.CharField(max_length=100)
    secret_note = models.CharField(max_length=100, blank=True, default="")
    currency = CurrencyField(default="GBP")
    price = MoneyField(currency_field="currency", null=True, blank=True)
    hourly_rate = RateField(currency_field="currency", null=True, blank=True)
    gadget = models.ForeignKey(Gadget, null=True, blank=True, on_delete=models.SET_NULL)

    audit_sensitive_fields: ClassVar[frozenset[str]] = frozenset({"secret_note"})

    def __str__(self) -> str:
        return self.name
