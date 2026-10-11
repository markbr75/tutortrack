"""Helpers shared by importers: addresses, tags, custom fields, updates with undo data and
finding records created by earlier rows of the same batch."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _

from .base import Context, FieldSpec
from .base import label as _l

ADDRESS_KEYS = ("line1", "line2", "city", "region", "postcode", "country")


def address_fields(prefix: str = "address_", what: str = "") -> list[FieldSpec]:
    names = {
        "line1": (_l("Address line 1"), ("address", "street", "address 1", "address line 1")),
        "line2": (_l("Address line 2"), ("address 2", "address line 2")),
        "city": (_l("Town or city"), ("city", "town", "suburb")),
        "region": (_l("County, state or region"), ("county", "state", "region", "province")),
        "postcode": (
            _l("Postcode"),
            ("postcode", "post code", "zip", "zip code", "postal code"),
        ),
        "country": (_l("Country code"), ("country",)),
    }
    return [
        FieldSpec(f"{prefix}{key}", text, synonyms=tuple(f"{what}{s}" for s in syn))
        for key, (text, syn) in names.items()
    ]


def address_from(values: dict[str, Any], prefix: str = "address_") -> dict[str, str] | None:
    data = {k: str(values.get(f"{prefix}{k}") or "") for k in ADDRESS_KEYS}
    if data["country"] and len(data["country"]) != 2:
        data["country"] = COUNTRY_NAMES.get(data["country"].lower(), "")
    return data if any(data.values()) else None


COUNTRY_NAMES = {
    "united kingdom": "GB",
    "uk": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "great britain": "GB",
    "united states": "US",
    "usa": "US",
    "australia": "AU",
    "canada": "CA",
    "ireland": "IE",
    "new zealand": "NZ",
    "south africa": "ZA",
}


def custom_field_specs(entity_type: str) -> list[FieldSpec]:
    from tutortrack.crm.custom_fields import definitions

    kinds = {
        "number": "int",
        "decimal": "decimal",
        "currency": "decimal",
        "date": "date",
        "boolean": "bool",
        "multi_select": "list",
        "email": "email",
    }
    return [
        FieldSpec(
            f"cf.{d.key}", d.label, kinds.get(d.type, "text"), synonyms=(d.key, d.label.lower())
        )
        for d in definitions(entity_type)
        if d.type not in ("file", "user", "address", "datetime")
    ]


def custom_values(values: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in values.items():
        if key.startswith("cf.") and value not in (None, "", []):
            out[key[3:]] = json_safe(value)
    return out


def json_safe(value: Any) -> Any:
    from django.db import models

    from tutortrack.core.money import Money

    if isinstance(value, Money):
        return {"amount": str(value.amount), "currency": value.currency}
    if isinstance(value, models.Model):
        return str(value.pk)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    return value


def apply_tags(target_type: str, target: Any, names: list[str] | None) -> list[dict[str, Any]]:
    from tutortrack.crm import services as crm

    out = []
    for name in names or []:
        tag = crm.get_or_create_tag(name)
        if crm.apply_tag(tag, target_type, [str(target.pk)]):
            out.append(
                {
                    "type": "crm.tag",
                    "id": str(tag.pk),
                    "target_type": target_type,
                    "target_id": str(target.pk),
                }
            )
    return out


def ref(obj: Any) -> dict[str, Any]:
    return {"type": f"{obj._meta.app_label}.{obj._meta.model_name}", "id": str(obj.pk)}


def changes_for(obj: Any, wanted: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The fields that differ (new values) and their current values (for rollback)."""
    new, old = {}, {}
    for key, value in wanted.items():
        if value is None:
            continue
        current = getattr(obj, key, None)
        if current != value:
            new[key] = value
            old[key] = json_safe(current)
    return new, old


def update_tracked(
    obj: Any, wanted: dict[str, Any], update: Callable[..., Any], previous: dict[str, Any]
) -> bool:
    """Apply ``wanted`` through the owning service, remembering the old values."""
    new, old = changes_for(obj, wanted)
    if not new:
        return False
    update(obj, **new)
    key = f"{obj._meta.app_label}.{obj._meta.model_name}:{obj.pk}"
    previous.setdefault(key, {}).update(
        {k: v for k, v in old.items() if k not in previous.get(key, {})}
    )
    return True


def batch_target(ctx: Context, key: str, *, before: int) -> Any:
    """The client a previous row of this batch created or matched for household ``key``."""
    from tutortrack.people.models import Client, Student

    from ..models import ImportRow

    if not key:
        return None
    cached = ctx.cache.get(("household", key.lower()))
    if cached is not None:
        return Client.objects.filter(pk=cached).first()
    row = (
        ImportRow.objects.filter(batch=ctx.batch, row_number__lt=before)
        .filter(values___household=key.lower())
        .exclude(target_id="")
        .order_by("row_number")
        .first()
    )
    if row is None:
        return None
    if row.target_type == "people.client":
        return Client.objects.filter(pk=row.target_id).first()
    if row.target_type == "people.student":
        student = Student.objects.filter(pk=row.target_id).select_related("client").first()
        return student.client if student else None
    return None


def remember_household(ctx: Context, key: str, client: Any) -> None:
    if key:
        ctx.cache[("household", key.lower())] = client.pk


def money_or_none(amount: Decimal | None, currency: str) -> Any:
    from tutortrack.core.money import Money

    return None if amount is None else Money(amount, currency).round_to_minor()


def not_found(what: str) -> str:
    return _("%(what)s not found.") % {"what": what}
