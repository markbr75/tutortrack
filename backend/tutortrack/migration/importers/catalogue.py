"""Services and rates (E28-T02)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _

from . import refs
from .base import Context, FieldSpec, Importer, Outcome, Plan, register
from .base import label as _l
from .common import money_or_none, ref, update_tracked


@register
class ServiceImporter(Importer):
    key = "services"
    label = _l("Services and rates")
    description = _l("What you teach, with default durations, charge rates and pay rates.")
    permissions = ("catalogue.manage",)
    target_type = "catalogue.service"
    upsert_keys = ("name", "external_id", "none")
    default_upsert = "name"
    fields = [
        FieldSpec("external_id", _l("Service ID"), synonyms=("service id", "id")),
        FieldSpec(
            "name",
            _l("Name"),
            required=True,
            synonyms=("name", "service", "service name", "lesson type"),
        ),
        FieldSpec(
            "format",
            _l("Format"),
            "choice",
            choices=("one_to_one", "group", "class"),
            synonyms=("format", "type"),
        ),
        FieldSpec(
            "delivery_mode",
            _l("Delivery"),
            "choice",
            choices=("in_person", "online", "hybrid"),
            synonyms=("delivery", "location type"),
        ),
        FieldSpec(
            "default_duration_minutes",
            _l("Default duration (minutes)"),
            "int",
            synonyms=("duration", "length", "minutes", "default duration"),
        ),
        FieldSpec(
            "charge_rate",
            _l("Charge rate"),
            "decimal",
            synonyms=("charge rate", "price", "rate", "client rate", "default charge rate"),
        ),
        FieldSpec(
            "pay_rate",
            _l("Pay rate"),
            "decimal",
            synonyms=("pay rate", "tutor rate", "wage", "default pay rate"),
        ),
        FieldSpec("currency", _l("Currency"), synonyms=("currency",), max_length=3),
        FieldSpec("subject", _l("Subject"), synonyms=("subject",)),
        FieldSpec("level", _l("Level"), synonyms=("level", "grade")),
        FieldSpec(
            "max_students", _l("Maximum students"), "int", synonyms=("capacity", "max students")
        ),
        FieldSpec("description", _l("Description"), synonyms=("description", "notes")),
    ]
    example = {
        "name": "GCSE Maths 1:1",
        "format": "one_to_one",
        "default_duration_minutes": "60",
        "charge_rate": "45.00",
        "pay_rate": "25.00",
        "subject": "Maths",
        "level": "GCSE",
    }

    def _existing(self, values: dict[str, Any], ctx: Context) -> Any:
        if ctx.upsert_key == "none":
            return None
        if values.get("external_id"):
            found = refs.find_service(ctx, {"service_external_id": values["external_id"]})
            if found is not None or ctx.upsert_key == "external_id":
                return found
        if ctx.upsert_key == "name":
            return refs.find_service(ctx, {"service": values.get("name")})
        return None

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        if ctx.claim("service", str(values.get("name") or "")):
            ctx.error("name", _("This service appears earlier in the file."))
        currency = (values.get("currency") or ctx.currency).upper()
        values["currency"] = currency
        for key in ("charge_rate", "pay_rate"):
            if values.get(key) is not None and values[key] < 0:
                ctx.error(key, _("Rates can't be negative."))
        if values.get("subject"):
            from tutortrack.catalogue.selectors import match_subject

            subject, level = match_subject(values["subject"], values.get("level") or "")
            if subject is None:
                ctx.warn("subject", _("Subject not in your catalogue; the service has none."))
            elif values.get("level") and level is None:
                ctx.warn("level", _("Level not found for this subject; left empty."))
        existing = self._existing(values, ctx)
        if existing is not None:
            return Plan(
                action="update",
                effects=[("catalogue.service", "update")],
                target_type="catalogue.service",
                target_id=str(existing.pk),
            )
        return Plan(effects=[("catalogue.service", "create")])

    def _data(self, values: dict[str, Any], ctx: Context) -> dict[str, Any]:
        from tutortrack.catalogue.selectors import match_subject

        currency = (values.get("currency") or ctx.currency).upper()
        data: dict[str, Any] = {
            k: values[k]
            for k in (
                "format",
                "delivery_mode",
                "default_duration_minutes",
                "description",
                "max_students",
            )
            if values.get(k) not in (None, "")
        }
        if data.get("format") in ("group", "class") and "max_students" not in data:
            data["max_students"] = 8
        if values.get("subject"):
            subject, level = match_subject(values["subject"], values.get("level") or "")
            if subject is not None:
                data["subject"], data["level"] = subject, level
        if values.get("charge_rate") is not None:
            data["charge_rate"] = money_or_none(values["charge_rate"], currency)
        if values.get("pay_rate") is not None:
            data["pay_rate"] = money_or_none(values["pay_rate"], currency)
        return data

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from tutortrack.catalogue import services as catalogue

        data = self._data(values, ctx)
        existing = self._existing(values, ctx)
        if existing is not None:
            out = Outcome(
                action="update", target_type="catalogue.service", target_id=str(existing.pk)
            )
            update_tracked(
                existing, {"name": values["name"], **data}, catalogue.update_service, out.previous
            )
            return out
        currency = (values.get("currency") or ctx.currency).upper()
        data.setdefault("charge_rate", money_or_none(Decimal(0), currency))
        service = catalogue.create_service(name=values["name"], **data)
        out = Outcome(action="create", target_type="catalogue.service", target_id=str(service.pk))
        out.created.append(ref(service))
        if values.get("external_id"):
            out.created.append(
                refs.remember(ctx, "catalogue.service", values["external_id"], service)
            )
        return out
