"""Serializer building blocks shared by every app.

* ``MoneySerializerField``: ``{"amount": "12.50", "currency": "GBP"}``.
* ``BaseModelSerializer``: hides fields per ``Meta.field_permissions``, maps
  ``MoneyField``/``RateField`` automatically, supports sparse
  fieldsets (``?fields=id,name``) and expansion (``?expand=client``) via
  ``Meta.expandable_fields = {"client": ("dotted.path.ClientSerializer", {...kwargs})}``.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils.module_loading import import_string
from rest_framework import serializers

from ..fields import MoneyField, RateField
from ..money import Money, validate_currency


class MoneySerializerField(serializers.Field):
    default_error_messages = {
        "invalid": 'Enter money as {{"amount": "12.50", "currency": "GBP"}}.',
        "invalid_currency": "Unknown currency {currency}.",
        "max_decimal_places": "Ensure that there are no more than {places} decimal places.",
    }

    def __init__(self, *, decimal_places: int = 2, **kwargs: Any):
        self.decimal_places = decimal_places
        super().__init__(**kwargs)

    def to_representation(self, value: Money) -> dict[str, str]:
        quantum = Decimal(1).scaleb(-self.decimal_places)
        return {"amount": str(value.amount.quantize(quantum)), "currency": value.currency}

    def to_internal_value(self, data: Any) -> Money:
        if not isinstance(data, dict) or "amount" not in data or "currency" not in data:
            self.fail("invalid")
        if isinstance(data["amount"], float):
            self.fail("invalid")  # floats lose precision; send a string
        try:
            amount = Decimal(str(data["amount"]))
        except InvalidOperation:
            self.fail("invalid")
        exponent = amount.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > self.decimal_places:
            self.fail("max_decimal_places", places=self.decimal_places)
        try:
            currency = validate_currency(str(data["currency"]))
        except ValueError:
            self.fail("invalid_currency", currency=data["currency"])
        return Money(amount, currency)


class MoneyOut(serializers.Serializer):
    """Read-only money in computed responses (quotes, summaries)."""

    amount = serializers.CharField()
    currency = serializers.CharField()


class TenantRelatedField(serializers.PrimaryKeyRelatedField):
    """A primary key of a tenant model, looked up in the organisation in context when the
    request is validated (not when the serializer class is defined).

        student = TenantRelatedField(Student)
        service = TenantRelatedField(Service, filter={"active": True})
    """

    def __init__(self, model: Any, *, filter: dict[str, Any] | None = None, **kwargs: Any):
        self.model = model
        self.filter = filter or {}
        kwargs.setdefault("queryset", model.all_tenants.none())  # only for introspection
        super().__init__(**kwargs)

    def get_queryset(self) -> Any:
        return self.model.objects.filter(**self.filter)


class DynamicFieldsMixin:
    """``?fields=a,b`` limits output fields on the top-level serializer (``id`` always kept)."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        if not self._is_root():
            return
        request = self.context.get("request")  # type: ignore[attr-defined]
        raw = request.query_params.get("fields") if request is not None else None
        if not raw:
            return
        wanted = {f.strip() for f in raw.split(",") if f.strip()} | {"id"}
        for name in list(self.fields):  # type: ignore[attr-defined]
            if name not in wanted:
                self.fields.pop(name)  # type: ignore[attr-defined]

    def _is_root(self) -> bool:
        parent = getattr(self, "parent", None)
        # A ListSerializer wrapping us on a list endpoint still counts as the root.
        return parent is None or (
            isinstance(parent, serializers.ListSerializer) and parent.parent is None
        )


class ExpandableFieldsMixin:
    """``?expand=client,students`` swaps id fields for nested serializers listed in
    ``Meta.expandable_fields``."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        expandable: dict[str, tuple[str | type, dict[str, Any]]] = getattr(
            getattr(self, "Meta", None), "expandable_fields", {}
        )
        request = self.context.get("request")  # type: ignore[attr-defined]
        if not expandable or request is None:
            return
        requested = {
            e.strip() for e in request.query_params.get("expand", "").split(",") if e.strip()
        }
        for name in requested & set(expandable):
            serializer_ref, options = expandable[name]
            serializer_class = (
                import_string(serializer_ref) if isinstance(serializer_ref, str) else serializer_ref
            )
            context = self.context  # type: ignore[attr-defined]
            self.fields[name] = serializer_class(  # type: ignore[attr-defined]
                read_only=True, context=context, **options
            )


class FieldPermissionMixin:
    """Drops fields the viewer may not see (FR-03-5 field-level permissions).

        class Meta:
            field_permissions = {"pay_rate": "billing.rates.view_pay",
                                 "charge_rate": "billing.rates.view_charge"}

    Fields are removed from output *and* input, so they can't be written either. The check
    runs when the fields are built, so nested serializers see the request of their root.
    Serializers without a request in context (internal use) keep every field.
    """

    def get_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = super().get_fields()  # type: ignore[misc]
        rules: dict[str, str] = getattr(getattr(self, "Meta", None), "field_permissions", {})
        request = self.context.get("request")  # type: ignore[attr-defined]
        if not rules or request is None:
            return fields
        if getattr(self.context.get("view"), "swagger_fake_view", False):  # type: ignore[attr-defined]
            return fields  # the OpenAPI schema documents every field; access is per viewer
        from ..permissions import has_perm

        for field, codename in rules.items():
            if field in fields and not has_perm(request.user, codename):
                fields.pop(field)
        return fields


class BaseModelSerializer(
    FieldPermissionMixin, DynamicFieldsMixin, ExpandableFieldsMixin, serializers.ModelSerializer
):
    serializer_field_mapping = {
        **serializers.ModelSerializer.serializer_field_mapping,
        MoneyField: MoneySerializerField,
        RateField: MoneySerializerField,
    }

    def build_standard_field(self, field_name: str, model_field: Any) -> Any:
        if isinstance(model_field, MoneyField):
            kwargs: dict[str, Any] = {"decimal_places": model_field.decimal_places}
            if model_field.null:
                kwargs["allow_null"] = True
                kwargs["required"] = False
            if not model_field.editable:
                kwargs["read_only"] = True
            return MoneySerializerField, kwargs
        return super().build_standard_field(field_name, model_field)
