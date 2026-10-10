"""The report engine: definitions, parameters, scoping, grouping, totals and currency.

A report is a ``ReportDef`` whose ``run(user, params)`` returns a ``Result`` (columns,
rows, totals, chart hint). Reports read the fact tables (or other apps' records,
read-only) through ``scoped()`` so the permission's data scope (all / branch / own)
always applies. Money cells are decimal strings in the row's ``currency``; with a
reporting currency they are converted at the day's FX rate and the original currency is
kept in ``original_currency`` (FR-26-6).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db.models import Q, QuerySet
from django.db.models.functions import (
    TruncDay,
    TruncMonth,
    TruncQuarter,
    TruncWeek,
    TruncYear,
)
from django.utils.translation import gettext_lazy as _

from tutortrack.core.context import current_branch_ids
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import minor_units, validate_currency
from tutortrack.core.permissions import permission_scope, scope_queryset

from .. import dims, periods
from ..fx import Converter

CATEGORIES = {
    "finance": _("Finance"),
    "payroll": _("Payroll"),
    "operations": _("Operations"),
    "sales": _("Sales and growth"),
    "people": _("People and compliance"),
}
FILTERS = ("branch", "tutor", "client", "service", "subject", "tag", "custom_field")
NUMERIC = ("money", "number", "count", "hours")
TIME_GROUPS: dict[str, Any] = {
    "day": TruncDay,
    "week": TruncWeek,
    "month": TruncMonth,
    "quarter": TruncQuarter,
    "year": TruncYear,
}
GROUP_LABELS = {
    "day": _("Day"),
    "week": _("Week"),
    "month": _("Month"),
    "quarter": _("Quarter"),
    "year": _("Year"),
    "tutor": _("Tutor"),
    "client": _("Client"),
    "student": _("Student"),
    "service": _("Service"),
    "subject": _("Subject"),
    "branch": _("Branch"),
    "job": _("Job"),
    "location": _("Location"),
    "kind": _("Type"),
    "status": _("Status"),
    "method": _("Method"),
    "provider": _("Provider"),
    "pay_run": _("Pay run"),
    "category": _("Category"),
    "outcome": _("Outcome"),
    "who": _("Cancelled by"),
    "notice": _("Notice given"),
    "source": _("Source"),
    "owner": _("Owner"),
    "level": _("Level"),
    "stage": _("Stage"),
}


def invalid(field_name: str, message: Any) -> BusinessRuleViolation:
    return BusinessRuleViolation(str(message), extra={"errors": {field_name: [str(message)]}})


# --- definitions --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    key: str
    label: Any
    type: str = "text"  # text | number | count | money | hours | percent | date

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "label": str(self.label), "type": self.type}


@dataclass
class Result:
    columns: list[Column]
    rows: list[dict[str, Any]]
    chart: dict[str, Any] | None = None
    totals: list[dict[str, Any]] | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReportDef:
    key: str
    title: Any
    category: str
    codename: str
    description: Any
    run: Callable[[Any, Params], Result]
    filters: tuple[str, ...] = ()
    group_by: tuple[str, ...] = ()  # the first one is the default
    ordering: str = ""
    period: bool = True  # whether the date range applies
    default_period: str = "this_month"

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": str(self.title),
            "category": self.category,
            "category_label": str(CATEGORIES[self.category]),
            "description": str(self.description),
            "filters": list(self.filters),
            "group_by": [{"value": g, "label": str(GROUP_LABELS.get(g, g))} for g in self.group_by],
            "period": self.period,
            "default_period": self.default_period,
        }


_registry: dict[str, ReportDef] = {}


def register(report: ReportDef) -> ReportDef:
    if report.category not in CATEGORIES:
        raise ValueError(f"unknown report category {report.category!r}")
    _registry[report.key] = report
    return report


def get(key: str) -> ReportDef | None:
    return _registry.get(key)


def all_reports() -> list[ReportDef]:
    return list(_registry.values())


# --- parameters ---------------------------------------------------------------------------------


@dataclass
class Params:
    period: periods.Period
    preset: str = "this_month"
    compare: str = "none"
    group_by: str = ""
    ordering: str = ""
    currency: str = ""
    branch: list[str] = field(default_factory=list)
    tutor: list[str] = field(default_factory=list)
    client: list[str] = field(default_factory=list)
    service: list[str] = field(default_factory=list)
    subject: list[str] = field(default_factory=list)
    tag: str = ""
    custom_field: str = ""

    def as_query(self) -> dict[str, Any]:
        """The parameters as saved with a view (relative presets stay relative)."""
        out: dict[str, Any] = {"period": self.preset}
        if self.preset == "custom":
            out.update(self.period.as_dict())
        for name in ("compare", "group_by", "ordering", "currency", "tag", "custom_field"):
            value = getattr(self, name)
            if value and not (name == "compare" and value == "none"):
                out[name] = value
        for name in ("branch", "tutor", "client", "service", "subject"):
            if getattr(self, name):
                out[name] = ",".join(getattr(self, name))
        return out


def id_list(data: Mapping[str, Any], name: str) -> list[str]:
    getlist = getattr(data, "getlist", None)
    raw = getlist(name) if callable(getlist) else data.get(name)
    if raw is None:
        return []
    values = raw if isinstance(raw, list | tuple) else [raw]
    out: list[str] = []
    for value in values:
        out += [v.strip() for v in str(value).split(",") if v.strip()]
    import uuid

    for value in out:
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise invalid(name, _("Not a valid id.")) from exc
    return out


def parse_params(report: ReportDef, data: Mapping[str, Any]) -> Params:
    def one(name: str, default: str = "") -> str:
        value = data.get(name, default)
        if isinstance(value, list | tuple):
            value = value[0] if value else default
        return str(value or default).strip()

    preset = one("period", report.default_period)
    start = end = None
    try:
        if one("from"):
            start = date.fromisoformat(one("from"))
        if one("to"):
            end = date.fromisoformat(one("to"))
    except ValueError as exc:
        raise invalid("from", _("Use dates like 2026-01-31.")) from exc
    if start and end and preset != "custom" and "period" not in data:
        preset = "custom"
    if preset not in periods.PRESETS:
        raise invalid("period", _("Unknown period."))
    try:
        period = periods.resolve(preset, start=start, end=end)
    except ValueError as exc:
        raise invalid(
            "from", _("Choose a start and an end date, the end after the start.")
        ) from exc
    if period.days > 3 * 366 + 1:
        raise invalid("to", _("Choose a period of up to three years."))
    compare = one("compare", "none")
    if compare not in periods.COMPARISONS:
        raise invalid("compare", _("Unknown comparison."))
    group_by = one("group_by", report.group_by[0] if report.group_by else "")
    if report.group_by and group_by not in report.group_by:
        raise invalid("group_by", _("This report can't be grouped that way."))
    currency = one("currency").upper()
    if not currency and "currency" not in data:
        from tutortrack.tenancy.settings_service import get_setting

        currency = str(get_setting("reporting.currency") or "").upper()
    if currency:
        try:
            validate_currency(currency)
        except ValueError as exc:
            raise invalid("currency", _("Unknown currency.")) from exc
    params = Params(
        period=period,
        preset=preset,
        compare=compare,
        group_by=group_by,
        ordering=one("ordering", report.ordering),
        currency=currency,
        tag=one("tag"),
        custom_field=one("custom_field"),
    )
    for name in ("branch", "tutor", "client", "service", "subject"):
        setattr(params, name, id_list(data, name))
    if params.tag:
        id_list({"tag": params.tag}, "tag")
    if params.custom_field and "=" not in params.custom_field:
        raise invalid("custom_field", _("Use field=value."))
    return params


# --- scoping ------------------------------------------------------------------------------------


def scoped(user: Any, qs: QuerySet[Any], codename: str) -> QuerySet[Any]:
    """Records the user may see under ``codename`` (models with ``branch`` / ``own_scope_q``)."""
    return scope_queryset(user, qs, codename)


def scoped_by(
    user: Any,
    qs: QuerySet[Any],
    codename: str,
    *,
    branch: str | None = None,
    own: Q | None = None,
) -> QuerySet[Any]:
    """Scope models without a ``branch`` field: ``branch`` is the lookup to the branch
    (e.g. ``"lesson__branch_id"``) and ``own`` the filter for the ``own`` scope."""
    scope = permission_scope(user, codename)
    if scope is None:
        return qs.none()
    if scope == "all":
        return qs
    if scope == "branch":
        ids = current_branch_ids()
        if ids is None:
            return qs
        return qs.filter(**{f"{branch}__in": ids}) if branch else qs.none()
    return qs.filter(own) if own is not None else qs.none()


def my_tutor_ids(user: Any) -> list[Any]:
    from tutortrack.people.models import TutorProfile

    return list(TutorProfile.objects.filter(membership__user=user).values_list("pk", flat=True))


def filter_facts(
    qs: QuerySet[Any], params: Params, fields: Mapping[str, str | None]
) -> QuerySet[Any]:
    """Apply the shared filters a report supports (``fields`` maps filter → lookup)."""
    for name in ("branch", "tutor", "client", "service", "subject"):
        lookup = fields.get(name)
        values = getattr(params, name)
        if lookup and values:
            qs = qs.filter(**{f"{lookup}__in": values})
    client_lookup = fields.get("client")
    if params.tag:
        from tutortrack.crm.models import TaggedItem

        q = Q(pk__in=[])
        for name, label in (
            ("client", "people.client"),
            ("tutor", "people.tutorprofile"),
            ("student", "people.student"),
        ):
            lookup = fields.get(name)
            if lookup:
                ids = TaggedItem.objects.filter(tag_id=params.tag, target_type=label).values(
                    "target_id"
                )
                q |= Q(**{f"{lookup}__in": [str(i["target_id"]) for i in ids]})
        qs = qs.filter(q)
    if params.custom_field and client_lookup:
        from tutortrack.people.models import Client

        key, _sep, value = params.custom_field.partition("=")
        ids = Client.objects.filter(**{f"custom_fields__{key.strip()}": value.strip()}).values("pk")
        qs = qs.filter(**{f"{client_lookup}__in": ids})
    return qs


def in_period(qs: QuerySet[Any], params: Params, lookup: str = "date") -> QuerySet[Any]:
    return qs.filter(**{f"{lookup}__gte": params.period.start, f"{lookup}__lte": params.period.end})


# --- grouping -----------------------------------------------------------------------------------


def money(value: Any, currency: str = "") -> str:
    places = minor_units(currency) if currency else 2
    amount = value if isinstance(value, Decimal) else Decimal(value or 0)
    return str(amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def hours(minutes: Any) -> str:
    return str((Decimal(minutes or 0) / 60).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def percent(part: Any, whole: Any) -> str:
    if not whole:
        return "0.0"
    value = Decimal(part or 0) * 100 / Decimal(whole)
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def group_key(group: str, fields: Mapping[str, str]) -> tuple[str, Any]:
    """(values() key, annotation or None) for a group-by option."""
    if group in TIME_GROUPS:
        return "_g", TIME_GROUPS[group]("date")
    return fields.get(group, group), None


def grouped(
    qs: QuerySet[Any],
    group: str,
    measures: Mapping[str, Any],
    *,
    fields: Mapping[str, str] | None = None,
    by_currency: bool = True,
    choices: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate ``qs`` by ``group`` (and currency): rows with ``group``/``group_id``
    and one key per measure (raw aggregate values; format them afterwards)."""
    key, annotation = group_key(group, fields or {})
    if annotation is not None:
        qs = qs.annotate(_g=annotation)
    values = [key] + (["currency"] if by_currency else [])
    rows = list(qs.values(*values).annotate(**measures).order_by(*values))
    names = dims.labels(group, (r[key] for r in rows)) if group not in TIME_GROUPS else {}
    out = []
    for r in rows:
        raw = r[key]
        if group in TIME_GROUPS:
            day = raw.date() if hasattr(raw, "date") else raw
            label = day.isoformat() if day else ""
            fx_day = day
        elif choices is not None:
            label = str(choices.get(raw, choices.get(str(raw), raw))) if raw else str(_("(none)"))
            fx_day = None
        else:
            label = names.get(str(raw), str(raw) if raw else str(_("(none)")))
            fx_day = None
        row: dict[str, Any] = {"group": label, "group_id": str(raw) if raw else ""}
        if by_currency:
            row["currency"] = r["currency"]
        if fx_day is not None:
            row["_fx_day"] = fx_day
        for m in measures:
            row[m] = r[m]
        out.append(row)
    return out


def group_column(params: Params) -> Column:
    return Column("group", GROUP_LABELS.get(params.group_by, _("Group")))


# --- ordering, currency, totals -----------------------------------------------------------------


def _sort_key(value: Any) -> tuple[int, Decimal, str]:
    if value is None or value == "":
        return (2, Decimal(0), "")
    try:
        return (0, Decimal(str(value)), "")
    except ArithmeticError:
        return (1, Decimal(0), str(value).lower())


def order_rows(result: Result, ordering: str) -> None:
    if not ordering:
        return
    key = ordering.lstrip("-")
    if key not in {c.key for c in result.columns}:
        raise invalid("ordering", _("Unknown column."))
    result.rows.sort(key=lambda row: _sort_key(row.get(key)), reverse=ordering.startswith("-"))


def convert_currency(result: Result, target: str, default_day: date) -> None:
    """Convert money cells into ``target`` at each row's day (or ``default_day``)."""
    money_cols = [c.key for c in result.columns if c.type == "money"]
    if not money_cols or not any("currency" in r for r in result.rows):
        return
    converter = Converter()
    missing: set[str] = set()
    for row in result.rows:
        source = row.get("currency") or target
        day = row.get("_fx_day") or default_day
        row["original_currency"] = source
        for key in money_cols:
            if row.get(key) in (None, ""):
                continue
            value = converter.convert(Decimal(str(row[key])), source, target, day)
            if value is None:
                missing.add(source)
                continue
            row[key] = str(value)
        if source not in missing:
            row["currency"] = target
    if missing:
        result.notes.append(
            str(_("No exchange rate for %(c)s; those rows stay in their own currency."))
            % {"c": ", ".join(sorted(missing))}
        )
    if not any(c.key == "original_currency" for c in result.columns):
        index = next((i for i, c in enumerate(result.columns) if c.key == "currency"), None)
        column = Column("original_currency", _("Original currency"))
        if index is None:
            result.columns.append(column)
        else:
            result.columns.insert(index + 1, column)


def compute_totals(result: Result) -> list[dict[str, Any]]:
    """One totals row per currency (or one row), summing numeric and money columns."""
    numeric = [c for c in result.columns if c.type in NUMERIC]
    if not numeric or not result.rows:
        return []
    by: dict[str, dict[str, Decimal]] = {}
    for row in result.rows:
        currency = str(row.get("currency") or "")
        bucket = by.setdefault(currency, {})
        for c in numeric:
            value = row.get(c.key)
            if value in (None, ""):
                continue
            bucket[c.key] = bucket.get(c.key, Decimal(0)) + Decimal(str(value))
    out = []
    for currency, sums in sorted(by.items()):
        total: dict[str, Any] = {"currency": currency} if currency else {}
        for c in numeric:
            value = sums.get(c.key, Decimal(0))
            if c.type == "money":
                total[c.key] = money(value, currency)
            elif c.type == "count":
                total[c.key] = int(value)
            else:
                total[c.key] = str(value)
        out.append(total)
    return out


def finalise(report: ReportDef, params: Params, result: Result) -> Result:
    if params.currency and any(c.type == "money" for c in result.columns):
        convert_currency(result, params.currency, params.period.end)
        result.totals = None  # recomputed in the reporting currency
    order_rows(result, params.ordering)
    if result.totals is None:
        result.totals = compute_totals(result)
    for row in result.rows:
        row.pop("_fx_day", None)
    return result


def money_columns(rows: Iterable[dict[str, Any]], keys: Iterable[str]) -> None:
    """Format raw aggregate money values in place (2dp, per currency minor unit)."""
    keys = list(keys)
    for row in rows:
        currency = str(row.get("currency") or "")
        for key in keys:
            row[key] = money(row.get(key), currency)
