"""The importer contract (FR-28-1).

An ``Importer`` describes one entity's fields and how a mapped row is checked, applied and
undone. Every write goes through the owning app's services, so validation, audit, events
and tenancy all apply exactly as for a record created by hand.

    check(values, ctx) -> Plan     # validation + dry run: errors, warnings, what will happen
    apply(values, ctx) -> Outcome  # create or update through services
    undo(row, ctx) -> bool         # rollback: True when reverted, False when kept
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

TRUE = {"1", "true", "yes", "y", "t", "x", "✓", "on", "active"}
FALSE = {"0", "false", "no", "n", "f", "", "off", "inactive"}
DATE_FORMATS = {
    "DMY": ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d %b %Y", "%d %B %Y"),
    "MDY": ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%b %d %Y", "%B %d %Y", "%b %d, %Y"),
    "YMD": ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"),
}
TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H.%M")
WEEKDAYS = {
    **{
        d: i
        for i, d in enumerate(
            ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        )
    },
    **{d: i for i, d in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])},
    **{d: i for i, d in enumerate(["mo", "tu", "we", "th", "fr", "sa", "su"])},
    "tues": 1,
    "weds": 2,
    "thur": 3,
    "thurs": 3,
}


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: Any  # lazy string
    type: str = "text"  # text email date datetime time decimal int bool choice list weekday
    required: bool = False
    choices: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    help: Any = ""
    max_length: int = 0

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": str(self.label),
            "field_type": self.type,
            "required": self.required,
            "choices": list(self.choices),
            "help": str(self.help),
        }


@dataclass
class Issue:
    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


@dataclass
class Plan:
    """What applying the row will do (the dry run)."""

    action: str = "create"  # create | update | skip
    effects: list[tuple[str, str]] = field(default_factory=list)  # (target type, verb)
    target_type: str = ""
    target_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)  # stored with the row's values


@dataclass
class Outcome:
    action: str  # create | update | skip
    target_type: str = ""
    target_id: str = ""
    created: list[dict[str, Any]] = field(default_factory=list)  # [{type, id, ...}]
    previous: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class RowError(Exception):
    """A row that can't be applied; the message is shown in the error report."""

    def __init__(self, message: str, field: str = "") -> None:
        super().__init__(message)
        self.field = field


@dataclass
class Context:
    """Per-batch state shared by the rows of one validation or import pass."""

    batch: Any
    system: str
    upsert_key: str
    date_format: str
    cutover: date
    currency: str
    timezone: str
    options: dict[str, Any]
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    # Keys claimed by earlier rows of this pass (validation can't see uncreated records).
    pending: dict[tuple[str, str], int] = field(default_factory=dict)
    cache: dict[Any, Any] = field(default_factory=dict)
    row_number: int = 0

    def error(self, field_key: str, message: str) -> None:
        self.errors.append(Issue(field_key, message))

    def warn(self, field_key: str, message: str) -> None:
        self.warnings.append(Issue(field_key, message))

    def reset_row(self, row_number: int) -> None:
        self.errors, self.warnings, self.row_number = [], [], row_number

    def claim(self, kind: str, key: str) -> int | None:
        """Remember that this row introduces ``key``; returns the row that already did."""
        if not key:
            return None
        found = self.pending.get((kind, key.lower()))
        if found is None:
            self.pending[(kind, key.lower())] = self.row_number
        return found

    def claimed(self, kind: str, key: str) -> int | None:
        return self.pending.get((kind, key.lower())) if key else None


class Importer:
    key: ClassVar[str]
    label: ClassVar[Any]
    permissions: ClassVar[tuple[str, ...]] = ()
    fields: ClassVar[list[FieldSpec]] = []
    upsert_keys: ClassVar[tuple[str, ...]] = ("external_id",)
    default_upsert: ClassVar[str] = "external_id"
    target_type: ClassVar[str] = ""
    description: ClassVar[Any] = ""
    example: ClassVar[dict[str, str]] = {}

    def field(self, key: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.key == key), None)

    def prepare(self, rows: list[Any], ctx: Context) -> None:
        """Optional pass over all rows before checking (series detection)."""

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        raise NotImplementedError

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        raise NotImplementedError

    def undo(self, row: Any, ctx: Context) -> bool:
        """Revert what the row did. The default deletes created records (newest first)
        through the registered discarders and reverts updates."""
        from .undo import undo_row

        return undo_row(self, row, ctx)

    def revert_update(self, row: Any, ctx: Context) -> bool:
        return False

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": str(self.label),
            "description": str(self.description),
            "field_specs": [f.describe() for f in self.fields],
            "upsert_keys": list(self.upsert_keys),
            "default_upsert": self.default_upsert,
            "permissions": list(self.permissions),
        }


_registry: dict[str, Importer] = {}


def register(cls: type[Importer]) -> type[Importer]:
    _registry[cls.key] = cls()
    return cls


def get(key: str) -> Importer | None:
    _load()
    return _registry.get(key)


def all_importers() -> list[Importer]:
    _load()
    return list(_registry.values())


def _load() -> None:
    from . import catalogue, crm, finance, jobs, lessons, people  # noqa: F401


# --- value coercion -----------------------------------------------------------------------------


def _number_text(text: str) -> str:
    cleaned = re.sub(r"[^\d,.\-()]", "", text)
    negative = (cleaned.startswith("(") and cleaned.endswith(")")) or text.strip().startswith("-")
    cleaned = cleaned.strip("()").lstrip("-")
    if cleaned.count(",") and cleaned.count("."):
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")  # 1.234,56
        else:
            cleaned = cleaned.replace(",", "")  # 1,234.56
    elif cleaned.count(",") == 1 and len(cleaned.split(",")[1]) in (1, 2):
        cleaned = cleaned.replace(",", ".")  # 12,50
    else:
        cleaned = cleaned.replace(",", "")
    return ("-" if negative else "") + cleaned


def parse_decimal(text: str) -> Decimal:
    try:
        value = Decimal(_number_text(text))
    except InvalidOperation as exc:
        raise ValueError(_("Not a number.")) from exc
    if not value.is_finite():
        raise ValueError(_("Not a number."))
    return value


def parse_date(text: str, order: str = "auto") -> date:
    text = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T].*)?", text):
        return date.fromisoformat(text[:10])
    orders = [order] if order in DATE_FORMATS else ["YMD", "DMY", "MDY"]
    for key in orders:
        for fmt in DATE_FORMATS[key]:
            try:
                return datetime.strptime(text, fmt).date()  # noqa: DTZ007 - a calendar date
            except ValueError:
                continue
    raise ValueError(_("Not a date we recognise (%(value)s).") % {"value": text[:20]})


def parse_time(text: str) -> time:
    text = text.strip().upper().replace(".", ":") if ":" not in text else text.strip().upper()
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).time()  # noqa: DTZ007 - a wall-clock time
        except ValueError:
            continue
    raise ValueError(_("Not a time we recognise (%(value)s).") % {"value": text[:10]})


def parse_datetime(text: str, order: str = "auto") -> tuple[date, time | None]:
    text = text.strip()
    match = re.match(r"^(.*?)[ T](\d{1,2}[:.]\d{2}(?::\d{2})?\s*(?:[AaPp][Mm])?)", text)
    if match:
        return parse_date(match.group(1), order), parse_time(match.group(2))
    return parse_date(text, order), None


def split_list(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;|\n]|,(?![^()]*\))", text) if p.strip()]


def coerce(spec: FieldSpec, text: str, ctx: Context, value_map: dict[str, str]) -> Any:
    """Turn a cell into a typed value (raises ValueError with a readable message)."""
    text = (text or "").strip()
    if value_map and text in value_map:
        text = value_map[text]
    elif value_map and text.lower() in {k.lower(): v for k, v in value_map.items()}:
        text = {k.lower(): v for k, v in value_map.items()}[text.lower()]
    if text == "":
        return None
    kind = spec.type
    if kind == "text":
        return text[: spec.max_length] if spec.max_length else text
    if kind == "email":
        email = text.lower()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise ValueError(_("Not a valid email address.")) from exc
        return email
    if kind == "date":
        return parse_date(text, ctx.date_format)
    if kind == "datetime":
        return parse_datetime(text, ctx.date_format)
    if kind == "time":
        return parse_time(text)
    if kind == "decimal":
        return parse_decimal(text)
    if kind == "int":
        number = parse_decimal(text)
        if number != number.to_integral_value():
            raise ValueError(_("Enter a whole number."))
        return int(number)
    if kind == "bool":
        lowered = text.lower()
        if lowered in TRUE:
            return True
        if lowered in FALSE:
            return False
        raise ValueError(_("Use yes or no."))
    if kind == "choice":
        normal = re.sub(r"[\s-]+", "_", text.lower())
        if normal in spec.choices:
            return normal
        raise ValueError(
            _("Use one of: %(choices)s (or map the value).") % {"choices": ", ".join(spec.choices)}
        )
    if kind == "list":
        return split_list(text)
    if kind == "weekday":
        lowered = text.lower().rstrip(".")
        if lowered in WEEKDAYS:
            return WEEKDAYS[lowered]
        if lowered.isdigit() and 0 <= int(lowered) <= 7:
            return int(lowered) % 7 if int(lowered) != 0 else 6  # 1=Monday ... 7/0=Sunday
        raise ValueError(_("Use a day name such as Monday."))
    return text


def normalise(
    importer: Importer,
    raw: dict[str, str],
    mapping: dict[str, str],
    value_map: dict[str, dict[str, str]],
    ctx: Context,
    extra: list[FieldSpec] | None = None,
) -> dict[str, Any]:
    """Mapped, typed values; coercion problems become row errors. ``extra``: the
    organisation's custom fields (``cf.<key>``)."""
    specs = {f.key: f for f in [*importer.fields, *(extra or [])]}
    values: dict[str, Any] = {}
    texts: dict[str, list[str]] = {}
    for column, key in mapping.items():
        if key and column in raw:
            texts.setdefault(key, []).append(raw[column])
    for key, cells in texts.items():
        spec = specs.get(key)
        if spec is None:
            continue
        joined = cells[0] if len(cells) == 1 else " ".join(c for c in cells if c)
        if spec.type == "list" and len(cells) > 1:
            joined = ";".join(c for c in cells if c)
        try:
            values[key] = coerce(spec, joined, ctx, value_map.get(key) or {})
        except ValueError as exc:
            ctx.error(key, f"{spec.label}: {exc}")
    for spec in importer.fields:
        missing = spec.required and values.get(spec.key) in (None, "", [])
        if missing and not any(i.field == spec.key for i in ctx.errors):
            ctx.error(spec.key, _("%(field)s is required.") % {"field": spec.label})
    return values


def label(text: str) -> Any:
    return gettext_lazy(text)


def first(values: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if values.get(key) not in (None, "", []):
            return values[key]
    return None


Discarder = Callable[[Any], None]


def chunks(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
