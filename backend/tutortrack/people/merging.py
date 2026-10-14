"""Merging duplicate clients, contacts and students (FR-05-13, ADR 0035).

Every app keeps ownership of its own records: it registers a ``MergeProvider`` in its own
``<app>/merge.py`` (autodiscovered by the people app), and the provider re-points that
app's references from the duplicate (``source``) to the record that survives (``target``).
The people app only chooses the surviving values, runs the providers in one transaction,
checks nothing still points at the duplicate, and leaves the duplicate as an archived
tombstone (``merged_into``).

Rules every provider follows:

* re-point, never edit amounts: financial records keep their history. Records that may
  never change (ledger entries, commission items) stay on the tombstone and are declared
  in ``history``; the owning app posts balancing entries instead;
* a unique constraint that would clash (both records tagged with the same tag, both on
  the same homework...) keeps the survivor's row; a clash that would lose financial or
  attendance data is a ``check`` problem that blocks the merge instead;
* generic references (``target_type``/``target_id`` style) are declared in ``generic`` so
  the engine can prove none is left behind.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from django.apps import apps
from django.db import models

SUBJECT_TYPES = ("people.client", "people.contact", "people.student")
KINDS = {"people.client": "client", "people.contact": "contact", "people.student": "student"}


@dataclass
class MergeContext:
    """One merge in progress: ``source`` is merged into ``target``."""

    subject_type: str
    source: Any
    target: Any
    user: Any = None
    notes: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return KINDS[self.subject_type]

    @property
    def source_id(self) -> str:
        return str(self.source.pk)

    @property
    def target_id(self) -> str:
        return str(self.target.pk)

    def note(self, message: str) -> None:
        if message not in self.notes:
            self.notes.append(message)


@dataclass(frozen=True)
class Move:
    """``count`` records of one kind that move (preview) or moved (merge)."""

    key: str
    label: str
    count: int


@dataclass(frozen=True)
class GenericRef:
    """A non-FK reference: ``model`` rows whose ``type_field`` is one of ``types[subject]``
    and whose ``id_field`` holds the record id."""

    model: str  # app_label.ModelName
    type_field: str
    id_field: str
    types: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class MergeProvider:
    key: str
    label: str
    subject_types: frozenset[str]
    count: Callable[[MergeContext], list[Move]]
    merge: Callable[[MergeContext], list[Move]]
    check: Callable[[MergeContext], list[str]] | None = None
    notes: Callable[[MergeContext], list[str]] | None = None
    # FK references deliberately left on the tombstone, "app_label.Model.field".
    history: tuple[str, ...] = ()
    generic: tuple[GenericRef, ...] = ()
    order: int = 100  # people (moving contacts and students) runs first


_providers: dict[str, MergeProvider] = {}


def register(provider: MergeProvider) -> MergeProvider:
    _providers[provider.key] = provider
    return provider


def providers(subject_type: str | None = None) -> list[MergeProvider]:
    out = sorted(_providers.values(), key=lambda p: (p.order, p.key))
    return [p for p in out if subject_type is None or subject_type in p.subject_types]


# --- helpers for providers ----------------------------------------------------------------------


def repoint(
    model: type[models.Model], field_name: str, ctx: MergeContext, *, exclude: Any = None
) -> int:
    """``UPDATE model SET field = target WHERE field = source`` (minus ``exclude`` rows)."""
    qs = model._base_manager.filter(**{f"{field_name}_id": ctx.source.pk})
    if exclude is not None:
        qs = qs.exclude(exclude)
    return qs.update(**{f"{field_name}_id": ctx.target.pk})


def repoint_unique(
    model: type[models.Model], field_name: str, ctx: MergeContext, together: Iterable[str]
) -> tuple[int, int]:
    """Re-point rows, keeping the survivor's row where ``(field, *together)`` would clash
    (the duplicate's clashing row is deleted). Returns (moved, dropped)."""
    together = list(together)
    taken = set(
        model._base_manager.filter(**{f"{field_name}_id": ctx.target.pk}).values_list(*together)
    )
    dropped = 0
    for row in model._base_manager.filter(**{f"{field_name}_id": ctx.source.pk}):
        if tuple(getattr(row, f) for f in together) in taken:
            row.delete()
            dropped += 1
    return repoint(model, field_name, ctx), dropped


def clashes(
    model: type[models.Model], field_name: str, ctx: MergeContext, together: Iterable[str]
) -> int:
    """How many of the duplicate's rows would clash with the survivor's on ``together``."""
    together = list(together)
    taken = set(
        model._base_manager.filter(**{f"{field_name}_id": ctx.target.pk}).values_list(*together)
    )
    rows = model._base_manager.filter(**{f"{field_name}_id": ctx.source.pk}).values_list(*together)
    return sum(1 for row in rows if tuple(row) in taken)


def count(model: type[models.Model], field_name: str, ctx: MergeContext) -> int:
    return model._base_manager.filter(**{f"{field_name}_id": ctx.source.pk}).count()


def generic_rows(ref: GenericRef, subject_type: str, record_id: str) -> Any:
    model = apps.get_model(ref.model)
    types = ref.types.get(subject_type, ())
    if not types:
        return model._base_manager.none()
    return model._base_manager.filter(
        **{f"{ref.type_field}__in": types, ref.id_field: str(record_id)}
    )


def repoint_generic(ref: GenericRef, ctx: MergeContext) -> int:
    return generic_rows(ref, ctx.subject_type, ctx.source_id).update(
        **{ref.id_field: ctx.target_id}
    )


def moves(*items: tuple[str, Any, int]) -> list[Move]:
    """``Move`` rows for the non-zero counts."""
    return [Move(key, str(label), n) for key, label, n in items if n]


# --- the safety net -----------------------------------------------------------------------------


def foreign_keys(model: type[models.Model]) -> list[tuple[type[models.Model], Any]]:
    """Every concrete FK, one-to-one and many-to-many field pointing at ``model``."""
    out: list[tuple[type[models.Model], Any]] = []
    for m in apps.get_models():
        for f in m._meta.get_fields():
            if (
                getattr(f, "concrete", False)
                and (f.many_to_one or f.one_to_one or f.many_to_many)
                and f.related_model is model
            ):
                out.append((m, f))
    return out


def references(subject_type: str, record_id: Any) -> dict[str, int]:
    """Rows anywhere that still refer to the record: FKs found through model meta, plus
    the generic references providers declare. History references are left out."""
    model = apps.get_model(subject_type)
    history = {h for p in providers(subject_type) for h in p.history}
    out: dict[str, int] = {}
    for m, f in foreign_keys(model):
        label = f"{m._meta.label}.{f.name}"
        if label in history:
            continue
        qs = m._base_manager.filter(**{f.name: record_id})
        if m is model:
            qs = qs.exclude(pk=record_id)
        n = qs.count()
        if n:
            out[label] = n
    for p in providers(subject_type):
        for ref in p.generic:
            n = generic_rows(ref, subject_type, str(record_id)).count()
            if n:
                key = f"{ref.model}.{ref.type_field}/{ref.id_field}"
                out[key] = out.get(key, 0) + n
    return out


# --- surviving values ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """A field the user chooses a surviving value for. ``kind``: ``value``, ``fk`` (a
    relation; the id is copied), ``address`` (copied into the survivor's own address) or
    ``custom`` (custom fields, combined key by key)."""

    name: str
    label: Any
    kind: str = "value"
    permission: str = ""  # needed to see (and choose) the values


def field_specs(subject_type: str) -> list[FieldSpec]:
    from django.utils.translation import gettext_lazy as _

    specs = {
        "people.client": [
            FieldSpec("display_name", _("Name")),
            FieldSpec("type", _("Type")),
            FieldSpec("status", _("Status")),
            FieldSpec("branch", _("Branch"), "fk"),
            FieldSpec("billing_address", _("Billing address"), "address"),
            FieldSpec("payment_terms_days", _("Payment terms (days)")),
            FieldSpec("invoice_delivery", _("Invoice delivery")),
            FieldSpec("invoice_grouping", _("Invoice grouping")),
            FieldSpec("preferred_payment_method", _("Preferred payment method")),
            FieldSpec("auto_pay", _("Auto-pay")),
            FieldSpec("credit_limit_amount", _("Credit limit")),
            FieldSpec("prevent_negative_balance", _("Prevent a negative balance")),
            FieldSpec("tax_exempt", _("Tax exempt")),
            FieldSpec("tax_id", _("Tax ID"), permission="billing.client.view_tax"),
            FieldSpec("po_number", _("PO number")),
            FieldSpec("referral_source", _("Referral source")),
            FieldSpec("account_manager", _("Account manager"), "fk"),
            FieldSpec("custom_fields", _("Custom fields"), "custom"),
        ],
        "people.contact": [
            FieldSpec("first_name", _("First name")),
            FieldSpec("last_name", _("Last name")),
            FieldSpec("relationship", _("Relationship")),
            FieldSpec("email", _("Email"), permission="people.contact.view_details"),
            FieldSpec("phone", _("Phone"), permission="people.contact.view_phone"),
            FieldSpec("mobile", _("Mobile"), permission="people.contact.view_phone"),
            FieldSpec("preferred_contact_method", _("Preferred contact method")),
            FieldSpec("address", _("Address"), "address", "people.contact.view_details"),
            FieldSpec("receives_reminders", _("Receives lesson reminders")),
            FieldSpec("receives_invoices", _("Receives invoices")),
            FieldSpec("receives_reports", _("Receives reports")),
            FieldSpec("receives_marketing", _("Receives marketing")),
            FieldSpec("is_emergency_contact", _("Emergency contact")),
            FieldSpec("language", _("Language")),
            FieldSpec("custom_fields", _("Custom fields"), "custom"),
        ],
        "people.student": [
            FieldSpec("first_name", _("First name")),
            FieldSpec("last_name", _("Last name")),
            FieldSpec("preferred_name", _("Preferred name")),
            FieldSpec("status", _("Status")),
            FieldSpec(
                "date_of_birth", _("Date of birth"), permission="people.student.view_sensitive"
            ),
            FieldSpec("year_group", _("Year group")),
            FieldSpec("school", _("School")),
            FieldSpec("branch", _("Branch"), "fk"),
            FieldSpec("subjects", _("Subjects")),
            FieldSpec("goals", _("Goals")),
            FieldSpec(
                "learning_needs", _("Learning needs"), permission="people.student.view_sensitive"
            ),
            FieldSpec("exam_boards", _("Exam boards")),
            FieldSpec("target_grades", _("Target grades")),
            FieldSpec("availability", _("Availability")),
            FieldSpec("lesson_address", _("Lesson address"), "address"),
            FieldSpec("custom_fields", _("Custom fields"), "custom"),
        ],
    }
    return specs[subject_type]


def _raw(record: Any, spec: FieldSpec) -> Any:
    if spec.kind == "fk":
        return getattr(record, f"{spec.name}_id")
    if spec.kind == "address":
        address = getattr(record, spec.name)
        return address.one_line() if address is not None else ""
    return getattr(record, spec.name)


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _display(record: Any, spec: FieldSpec) -> str:
    import json

    if spec.kind == "fk":
        related = getattr(record, spec.name)
        return str(related) if related is not None else ""
    value = _raw(record, spec)
    if _empty(value):
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if spec.name == "subjects" and isinstance(value, list):
        return ", ".join(
            " ".join(p for p in (str(s.get("subject", "")), str(s.get("level", ""))) if p)
            for s in value
            if isinstance(s, dict)
        )
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def default_choice(source: Any, target: Any, spec: FieldSpec) -> str:
    """Keep the survivor's value unless it is empty and the duplicate has one."""
    if spec.kind == "custom":
        return "target"
    if _empty(_raw(target, spec)) and not _empty(_raw(source, spec)):
        return "source"
    return "target"


def field_rows(user: Any, subject_type: str, source: Any, target: Any) -> list[dict[str, Any]]:
    """Side by side values for the merge screen; values the user may not see are hidden."""
    from tutortrack.core.permissions import has_perm

    rows = []
    for spec in field_specs(subject_type):
        hidden = bool(spec.permission) and not has_perm(user, spec.permission)
        rows.append(
            {
                "name": spec.name,
                "label": str(spec.label),
                "source": "" if hidden else _display(source, spec),
                "target": "" if hidden else _display(target, spec),
                "hidden": hidden,
                "same": _raw(source, spec) == _raw(target, spec),
                "default": default_choice(source, target, spec),
            }
        )
    return rows


def _address_dict(address: Any) -> dict[str, str]:
    from .services import ADDRESS_FIELDS

    if address is None:
        return {}
    return {k: getattr(address, k) for k in ADDRESS_FIELDS}


def surviving_changes(
    user: Any, subject_type: str, source: Any, target: Any, choices: dict[str, str]
) -> tuple[dict[str, Any], dict[str, str]]:
    """The changes to make on the survivor, and the resolved choice for every field."""
    from django.utils.translation import gettext as _

    from tutortrack.core.exceptions import BusinessRuleViolation
    from tutortrack.core.permissions import has_perm

    specs = {s.name: s for s in field_specs(subject_type)}
    wrong = {k for k, v in choices.items() if k not in specs or v not in {"source", "target"}}
    if wrong:
        message = _("Choose which value to keep for each field.")
        raise BusinessRuleViolation(message, extra={"errors": {"choices": sorted(wrong)}})
    changes: dict[str, Any] = {}
    resolved: dict[str, str] = {}
    for name, spec in specs.items():
        choice = choices.get(name) or default_choice(source, target, spec)
        if spec.permission and not has_perm(user, spec.permission):
            choice = default_choice(source, target, spec)  # nobody chooses what they can't see
        resolved[name] = choice
        if spec.kind == "custom":
            first, second = (target, source) if choice == "source" else (source, target)
            combined = {**(first.custom_fields or {}), **(second.custom_fields or {})}
            if combined != (target.custom_fields or {}):
                changes["custom_fields"] = combined
            continue
        if choice != "source" or _raw(source, spec) == _raw(target, spec):
            continue
        if spec.kind == "fk":
            changes[f"{name}_id"] = getattr(source, f"{name}_id")
        elif spec.kind == "address":
            changes[name] = _address_dict(getattr(source, name))
        elif name == "status" and source.status == "archived":
            continue  # the survivor stays live
        else:
            changes[name] = getattr(source, name)
    return changes, resolved


# --- preview and merge --------------------------------------------------------------------------


def _related_subjects(ctx: MergeContext) -> list[tuple[str, str]]:
    """Records a legal hold on which blocks the merge: both records, and for clients the
    people in both households."""
    from .models import Contact, Student

    refs = [(ctx.subject_type, ctx.source_id), (ctx.subject_type, ctx.target_id)]
    if ctx.subject_type == "people.client":
        clients = [ctx.source, ctx.target]
        for model, kind in ((Contact, "people.contact"), (Student, "people.student")):
            ids = model.objects.filter(client__in=clients).values_list("pk", flat=True)
            refs += [(kind, str(pk)) for pk in ids]
    return refs


def problems(ctx: MergeContext) -> list[str]:
    """Why the merge can't go ahead (empty: it can)."""
    from django.db.models import Q
    from django.utils.translation import gettext as _

    out: list[str] = []
    source, target = ctx.source, ctx.target
    if source.pk == target.pk:
        return [_("Choose two different records.")]
    if source.merged_into_id or target.merged_into_id:
        out.append(_("One of these records was already merged into another."))
    if target.archived_at is not None:
        out.append(_("The record that stays is archived. Restore it first."))
    if ctx.subject_type in {"people.contact", "people.student"} and (
        source.client_id != target.client_id
    ):
        out.append(_("They belong to different families. Merge the families first."))
    from tutortrack.privacy.selectors import active_holds

    held = Q()
    for subject_type, subject_id in _related_subjects(ctx):
        held |= Q(subject_type=subject_type, subject_id=subject_id)
    if active_holds().filter(held).exists():
        out.append(_("A legal hold applies to one of these records, so they can't be merged."))
    for p in providers(ctx.subject_type):
        if p.check is not None:
            out += p.check(ctx)
    return out


def warnings(ctx: MergeContext) -> list[str]:
    from django.utils.translation import gettext as _

    out: list[str] = []
    if ctx.subject_type == "people.client" and ctx.source.currency != ctx.target.currency:
        out.append(
            _(
                "The families bill in different currencies (%(a)s and %(b)s). "
                "Both balances are kept."
            )
            % {"a": ctx.source.currency, "b": ctx.target.currency}
        )
    for p in providers(ctx.subject_type):
        if p.notes is not None:
            out += p.notes(ctx)
    return out


def load(subject_type: str, record_id: Any, *, lock: bool = False) -> Any:
    from django.core.exceptions import ValidationError

    from tutortrack.core.exceptions import NotFound

    model = apps.get_model(subject_type)
    qs = model._default_manager.all()
    if lock:
        qs = qs.select_for_update()
    try:
        record = qs.filter(pk=record_id).first()
    except (ValidationError, ValueError):
        record = None
    if record is None:
        raise NotFound()
    return record


def preview(user: Any, subject_type: str, source: Any, target: Any) -> dict[str, Any]:
    """What a merge would do: values side by side, what moves, and what stops it."""
    ctx = MergeContext(subject_type, source, target, user)
    blocked = problems(ctx)
    moved: list[Move] = []
    if source.pk != target.pk:
        for p in providers(subject_type):
            moved += p.count(ctx)
    return {
        "subject_type": subject_type,
        "source": {"id": ctx.source_id, "name": str(source)},
        "target": {"id": ctx.target_id, "name": str(target)},
        "values": field_rows(user, subject_type, source, target) if source.pk != target.pk else [],
        "moves": [{"key": m.key, "label": m.label, "count": m.count} for m in moved],
        "problems": blocked,
        "warnings": warnings(ctx) if source.pk != target.pk else [],
        "can_merge": not blocked,
    }
