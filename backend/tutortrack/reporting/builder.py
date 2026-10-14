"""The custom report builder (FR-26-3, E26-T08) on a semantic layer.

A *dataset* is a whitelisted description of one queryable table: its dimensions (columns
to group by, show or filter on, each an ORM lookup we wrote), its measures (count, sum,
average, minimum or maximum of a field we chose) and the date that the period applies to.
A user's report is a JSON definition that only *names* dimensions and measures; ``run``
validates it against the dataset and builds the ORM query, so no SQL or field path ever
comes from the user. Data is permission-scoped twice: the dataset belongs to a report
family (``reporting.<family>.view``, with its all/branch/own scope, like the standard
reports) and the builder itself needs ``reporting.builder.use``.

Money is summed per currency (never across currencies) and formatted half-up to the
currency's minor unit; averages are rounded half-up to two places. Totals are a separate
aggregate over the same filtered rows, so an average's total is the overall average, not
a sum of averages. Queries run with a statement timeout and a row cap.

Definition::

    {"dataset": "charges", "group_by": ["service", "date:month"],
     "measures": ["count", "gross"], "filters": [{"field": "kind", "op": "in",
     "value": ["lesson"]}], "period": "this_year", "from": "", "to": "",
     "ordering": "-gross", "limit": 100, "chart": "bar", "currency": ""}

Without measures the report lists rows (the chosen dimensions as columns).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.db import OperationalError, connection, transaction
from django.db.models import Avg, Count, F, Max, Min, Q, QuerySet, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncQuarter, TruncWeek, TruncYear
from django.utils.translation import gettext_lazy as _

from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.money import minor_units, validate_currency
from tutortrack.core.permissions import has_perm, scope_queryset

from . import dims, periods
from .reports.base import (
    CATEGORIES,
    Column,
    Result,
    convert_currency,
    invalid,
    scoped_by,
)

BUILDER = "reporting.builder.use"
GRAINS: dict[str, Any] = {
    "day": TruncDay,
    "week": TruncWeek,
    "month": TruncMonth,
    "quarter": TruncQuarter,
    "year": TruncYear,
}
GRAIN_LABELS = {
    "day": _("Day"),
    "week": _("Week"),
    "month": _("Month"),
    "quarter": _("Quarter"),
    "year": _("Year"),
}
AGGREGATES: dict[str, Any] = {"count": Count, "sum": Sum, "avg": Avg, "min": Min, "max": Max}
OPS = ("eq", "neq", "in", "gte", "lte", "contains", "empty", "not_empty")
OPS_BY_TYPE = {
    "id": ("eq", "neq", "in", "empty", "not_empty"),
    "choice": ("eq", "neq", "in"),
    "text": ("eq", "neq", "in", "contains", "empty", "not_empty"),
    "date": ("eq", "gte", "lte", "empty", "not_empty"),
    "bool": ("eq",),
    "number": ("eq", "neq", "gte", "lte"),
}
CHARTS = ("table", "bar", "line", "pie")
MAX_GROUPS = 3
MAX_MEASURES = 6
MAX_FILTERS = 10
MAX_ROWS = 1000
TIMEOUT_MS = 15000
ALL = "all"  # period preset: no date filter


# --- the semantic layer -------------------------------------------------------------------------


@dataclass(frozen=True)
class Dim:
    key: str
    label: Any
    lookup: str
    type: str = "text"  # id | choice | text | date | bool | number
    names: str = ""  # ``dims.labels`` kind that names ids
    choices: tuple[tuple[str, Any], ...] = ()
    timestamp: bool = False  # a timestamp (dates are taken in the organisation's timezone)

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": str(self.label),
            "type": self.type,
            "grains": list(GRAINS) if self.type == "date" else [],
            "choices": [{"value": v, "label": str(lbl)} for v, lbl in self.choices],
            "operators": list(OPS_BY_TYPE[self.type]),
        }


@dataclass(frozen=True)
class Measure:
    key: str
    label: Any
    agg: str  # count | sum | avg | min | max
    field: str = "pk"
    type: str = "count"  # count | number | money | hours (a sum of minutes) | percent
    distinct: bool = False
    where: Q | None = None

    def expression(self) -> Any:
        fn = AGGREGATES[self.agg]
        if self.agg == "count":
            return fn(self.field, distinct=self.distinct, filter=self.where)
        return fn(self.field, filter=self.where)

    @property
    def column_type(self) -> str:
        if self.type == "hours":
            return "hours"
        if self.type == "money":
            return "money"
        return "count" if self.agg == "count" else "number"

    def describe(self) -> dict[str, Any]:
        return {"key": self.key, "label": str(self.label), "type": self.column_type}


Scope = Callable[[Any, QuerySet[Any], str], QuerySet[Any]]


@dataclass(frozen=True)
class Dataset:
    key: str
    label: Any
    category: str  # the report family: finance | payroll | operations | sales | people
    queryset: Callable[[], QuerySet[Any]]
    date: str  # the dimension key the period filters on
    dims: tuple[Dim, ...]
    measures: tuple[Measure, ...]
    currency: str = ""  # lookup of the currency column when there are money measures
    custom_fields: tuple[tuple[str, str], ...] = ()  # (entity type, lookup path)
    scope: Scope = scope_queryset
    description: Any = ""

    @property
    def codename(self) -> str:
        return f"reporting.{self.category}.view"

    def all_dims(self) -> dict[str, Dim]:
        found = {d.key: d for d in self.dims}
        found.update(custom_field_dims(self))
        return found

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": str(self.label),
            "description": str(self.description),
            "category": self.category,
            "category_label": str(CATEGORIES[self.category]),
            "date_field": self.date,
            "dimensions": [d.describe() for d in self.all_dims().values()],
            "measures": [m.describe() for m in self.measures],
        }


def custom_field_dims(ds: Dataset) -> dict[str, Dim]:
    """Active client/student custom fields as text dimensions (``cf.<entity>.<key>``)."""
    if not ds.custom_fields:
        return {}
    from tutortrack.crm.models import CustomFieldDefinition

    out: dict[str, Dim] = {}
    entities = dict(ds.custom_fields)
    rows = CustomFieldDefinition.objects.filter(
        entity_type__in=list(entities), active=True
    ).order_by("entity_type", "order", "key")
    for row in rows:
        entity = row.entity_type.split(".")[-1]
        key = f"cf.{entity}.{row.key}"
        out[key] = Dim(key, f"{row.label} ({entity})", f"{entities[row.entity_type]}{row.key}")
    return out


def _tutor_scope(user: Any, qs: QuerySet[Any], codename: str) -> QuerySet[Any]:
    from tutortrack.people.models import TutorProfile

    return scoped_by(
        user, qs, codename, branch="branches", own=TutorProfile.own_scope_q(user)
    ).distinct()


def _attendee_scope(user: Any, qs: QuerySet[Any], codename: str) -> QuerySet[Any]:
    return scoped_by(
        user,
        qs,
        codename,
        branch="lesson__branch_id",
        own=Q(lesson__tutors__tutor__membership__user=user),
    )


def _issued_invoices() -> QuerySet[Any]:
    from tutortrack.billing.models import Invoice

    return Invoice.objects.exclude(status=Invoice.Status.DRAFT)


def _choices(model_choices: Any) -> tuple[tuple[str, Any], ...]:
    return tuple((str(v), lbl) for v, lbl in model_choices)


def _datasets() -> dict[str, Dataset]:
    from tutortrack.delivery.models import LessonFeedback
    from tutortrack.leads.models import Enquiry
    from tutortrack.people.models import Client, Student, TutorProfile
    from tutortrack.scheduling.models import LessonAttendee

    from .models import FactCharge, FactLesson, FactPayItem, FactPayment

    branch = Dim("branch", _("Branch"), "branch_id", "id", names="branch")
    tutor = Dim("tutor", _("Tutor"), "tutor_id", "id", names="tutor")
    client = Dim("client", _("Client"), "client_id", "id", names="client")
    student = Dim("student", _("Student"), "student_id", "id", names="student")
    service = Dim("service", _("Service"), "service_id", "id", names="service")
    subject = Dim("subject", _("Subject"), "subject_id", "id", names="subject")
    job = Dim("job", _("Job"), "job_id", "id", names="job")
    day = Dim("date", _("Date"), "date", "date")
    count = Measure("count", _("Rows"), "count")
    sets = [
        Dataset(
            "lessons",
            _("Lessons"),
            "operations",
            lambda: FactLesson.objects.all(),
            "date",
            (
                day,
                tutor,
                service,
                subject,
                job,
                Dim("location", _("Location"), "location_id", "id", names="location"),
                branch,
                Dim(
                    "status",
                    _("Status"),
                    "status",
                    "choice",
                    choices=(
                        ("planned", _("Planned")),
                        ("completed", _("Completed")),
                        ("cancelled", _("Cancelled")),
                        ("missed", _("Missed")),
                    ),
                ),
                Dim("cancelled_by", _("Cancelled by"), "cancelled_by"),
                Dim("unconfirmed", _("Unconfirmed"), "unconfirmed", "bool"),
            ),
            (
                Measure("lessons", _("Lessons"), "count", "lesson_id", distinct=True),
                Measure("scheduled_hours", _("Scheduled hours"), "sum", "minutes", "hours"),
                Measure(
                    "delivered_hours", _("Delivered hours"), "sum", "delivered_minutes", "hours"
                ),
                Measure("attendees", _("Attendees"), "sum", "attendees", "number"),
                Measure("present", _("Present"), "sum", "present", "number"),
                Measure("absent", _("Absent"), "sum", "absent", "number"),
                Measure("revenue", _("Revenue"), "sum", "revenue_amount", "money"),
                Measure("pay", _("Tutor pay"), "sum", "pay_amount", "money"),
            ),
            currency="currency",
            description=_("One row per lesson and tutor (revenue on the first row only)."),
        ),
        Dataset(
            "attendees",
            _("Attendees"),
            "operations",
            lambda: LessonAttendee.objects.select_related(None),
            "lesson_date",
            (
                Dim("lesson_date", _("Lesson date"), "lesson__start", "date", timestamp=True),
                student,
                client,
                Dim("tutor", _("Tutor"), "lesson__tutors__tutor_id", "id", names="tutor"),
                Dim("service", _("Service"), "lesson__service_id", "id", names="service"),
                Dim("branch", _("Branch"), "lesson__branch_id", "id", names="branch"),
                Dim(
                    "outcome",
                    _("Outcome"),
                    "outcome",
                    "choice",
                    choices=_choices(LessonAttendee.Outcome.choices),
                ),
                Dim(
                    "lesson_status",
                    _("Lesson status"),
                    "lesson__status",
                    "choice",
                    choices=(
                        ("planned", _("Planned")),
                        ("completed", _("Completed")),
                        ("cancelled", _("Cancelled")),
                        ("missed", _("Missed")),
                    ),
                ),
                Dim("chargeable", _("Chargeable"), "chargeable", "bool"),
            ),
            (
                Measure("attendances", _("Attendances"), "count"),
                Measure("students", _("Students"), "count", "student_id", distinct=True),
                Measure(
                    "late_minutes", _("Minutes late (average)"), "avg", "late_minutes", "number"
                ),
            ),
            custom_fields=(("people.client", "client__custom_fields__"),),
            scope=_attendee_scope,
        ),
        Dataset(
            "charges",
            _("Charges"),
            "finance",
            lambda: FactCharge.objects.all(),
            "date",
            (
                day,
                client,
                student,
                tutor,
                service,
                subject,
                job,
                branch,
                Dim("kind", _("Type"), "kind"),
                Dim("status", _("Status"), "status"),
            ),
            (
                count,
                Measure("net", _("Net"), "sum", "net_amount", "money"),
                Measure("tax", _("Tax"), "sum", "tax_amount", "money"),
                Measure("gross", _("Gross"), "sum", "gross_amount", "money"),
                Measure("average_gross", _("Average charge"), "avg", "gross_amount", "money"),
            ),
            currency="currency",
            custom_fields=(("people.client", "client__custom_fields__"),),
        ),
        Dataset(
            "payments",
            _("Payments"),
            "finance",
            lambda: FactPayment.objects.all(),
            "date",
            (
                day,
                client,
                branch,
                Dim("method", _("Method"), "method"),
                Dim("provider", _("Provider"), "provider"),
                Dim("status", _("Status"), "status"),
            ),
            (
                count,
                Measure("amount", _("Received"), "sum", "amount_amount", "money"),
                Measure("refunded", _("Refunded"), "sum", "refunded_amount", "money"),
                Measure("fee", _("Fees"), "sum", "fee_amount", "money"),
            ),
            currency="currency",
            custom_fields=(("people.client", "client__custom_fields__"),),
        ),
        Dataset(
            "pay_items",
            _("Pay items"),
            "payroll",
            lambda: FactPayItem.objects.all(),
            "date",
            (
                day,
                tutor,
                service,
                job,
                branch,
                Dim("pay_run", _("Pay run"), "pay_run_id", "id", names="pay_run"),
                Dim("kind", _("Type"), "kind"),
                Dim("status", _("Status"), "status"),
            ),
            (
                count,
                Measure("amount", _("Amount"), "sum", "amount_amount", "money"),
                Measure("quantity", _("Quantity"), "sum", "quantity", "number"),
            ),
            currency="currency",
        ),
        Dataset(
            "invoices",
            _("Invoices"),
            "finance",
            _issued_invoices,
            "issue_date",
            (
                Dim("issue_date", _("Issue date"), "issue_date", "date"),
                Dim("due_date", _("Due date"), "due_date", "date"),
                client,
                branch,
                Dim(
                    "status",
                    _("Status"),
                    "status",
                    "choice",
                    choices=(
                        ("issued", _("Issued")),
                        ("partially_paid", _("Partially paid")),
                        ("paid", _("Paid")),
                        ("void", _("Void")),
                        ("written_off", _("Written off")),
                    ),
                ),
            ),
            (
                count,
                Measure("total", _("Total"), "sum", "total_amount", "money"),
                Measure("tax", _("Tax"), "sum", "tax_total_amount", "money"),
                Measure("balance_due", _("Still owed"), "sum", "balance_due_amount", "money"),
            ),
            currency="currency",
            custom_fields=(("people.client", "client__custom_fields__"),),
        ),
        Dataset(
            "students",
            _("Students"),
            "people",
            lambda: Student.objects.filter(archived_at__isnull=True),
            "created",
            (
                Dim("created", _("Added"), "created_at", "date", timestamp=True),
                client,
                branch,
                Dim(
                    "status",
                    _("Status"),
                    "status",
                    "choice",
                    choices=_choices(Student.Status.choices),
                ),
                Dim("year_group", _("Year group"), "year_group"),
                Dim("school", _("School"), "school"),
            ),
            (Measure("students", _("Students"), "count"),),
            custom_fields=(
                ("people.student", "custom_fields__"),
                ("people.client", "client__custom_fields__"),
            ),
        ),
        Dataset(
            "clients",
            _("Clients"),
            "people",
            lambda: Client.objects.filter(archived_at__isnull=True),
            "created",
            (
                Dim("created", _("Added"), "created_at", "date", timestamp=True),
                branch,
                Dim(
                    "status",
                    _("Status"),
                    "status",
                    "choice",
                    choices=_choices(Client.Status.choices),
                ),
                Dim("type", _("Type"), "type", "choice", choices=_choices(Client.Type.choices)),
                Dim("referral_source", _("Referral source"), "referral_source"),
            ),
            (Measure("clients", _("Clients"), "count"),),
            custom_fields=(("people.client", "custom_fields__"),),
        ),
        Dataset(
            "tutors",
            _("Tutors"),
            "people",
            lambda: TutorProfile.objects.filter(archived_at__isnull=True),
            "created",
            (
                Dim("created", _("Added"), "created_at", "date", timestamp=True),
                Dim(
                    "status",
                    _("Status"),
                    "status",
                    "choice",
                    choices=_choices(TutorProfile.Status.choices),
                ),
                Dim(
                    "employment_type",
                    _("Employment"),
                    "employment_type",
                    "choice",
                    choices=_choices(TutorProfile.Employment.choices),
                ),
                Dim("delivers_online", _("Teaches online"), "delivers_online", "bool"),
                Dim("delivers_in_person", _("Teaches in person"), "delivers_in_person", "bool"),
            ),
            (
                Measure("tutors", _("Tutors"), "count", "pk", distinct=True),
                Measure(
                    "experience",
                    _("Years of experience (average)"),
                    "avg",
                    "years_experience",
                    "number",
                ),
            ),
            custom_fields=(("people.tutor", "custom_fields__"),),
            scope=_tutor_scope,
        ),
        Dataset(
            "enquiries",
            _("Enquiries"),
            "sales",
            lambda: Enquiry.objects.all(),
            "created",
            (
                Dim("created", _("Received"), "created_at", "date", timestamp=True),
                branch,
                Dim(
                    "status",
                    _("Outcome"),
                    "status",
                    "choice",
                    choices=_choices(Enquiry.Status.choices),
                ),
                Dim(
                    "source",
                    _("Source"),
                    "source",
                    "choice",
                    choices=_choices(Enquiry.Source.choices),
                ),
                Dim("stage", _("Stage"), "stage__name"),
                Dim("pipeline", _("Pipeline"), "pipeline__name"),
                Dim(
                    "priority",
                    _("Priority"),
                    "priority",
                    "choice",
                    choices=_choices(Enquiry.Priority.choices),
                ),
                Dim("lost_reason", _("Lost reason"), "lost_reason"),
                Dim("owner", _("Owner"), "owner__email"),
            ),
            (
                Measure("enquiries", _("Enquiries"), "count"),
                Measure("won", _("Won"), "count", where=Q(status="won")),
                Measure("value", _("Estimated value"), "sum", "value_estimate_amount", "money"),
            ),
            currency="currency",
            custom_fields=(("people.client", "client__custom_fields__"),),
        ),
        Dataset(
            "lesson_feedback",
            _("Lesson feedback"),
            "operations",
            lambda: LessonFeedback.objects.all(),
            "lesson_date",
            (
                Dim("lesson_date", _("Lesson date"), "lesson_date", "date"),
                tutor,
                student,
                client,
                branch,
                Dim(
                    "status",
                    _("Status"),
                    "status",
                    "choice",
                    choices=_choices(LessonFeedback.Status.choices),
                ),
                Dim("rating", _("Stars"), "rating", "number"),
            ),
            (
                Measure("requests", _("Requests"), "count"),
                Measure("answered", _("Answered"), "count", where=Q(status="answered")),
                Measure("average_rating", _("Average stars"), "avg", "rating", "number"),
                Measure("lowest_rating", _("Lowest stars"), "min", "rating", "number"),
            ),
        ),
    ]
    return {ds.key: ds for ds in sets}


_cache: dict[str, Dataset] = {}


def datasets() -> dict[str, Dataset]:
    if not _cache:
        _cache.update(_datasets())
    return _cache


def available(user: Any) -> list[Dataset]:
    if not has_perm(user, BUILDER):
        return []
    return [ds for ds in datasets().values() if has_perm(user, ds.codename)]


def dataset_for(key: str, user: Any) -> Dataset:
    ds = datasets().get(str(key))
    if ds is None:
        raise invalid("dataset", _("Unknown dataset."))
    if not has_perm(user, BUILDER) or not has_perm(user, ds.codename):
        raise PermissionDenied(str(_("You can't build reports on this data.")))
    return ds


# --- definitions --------------------------------------------------------------------------------


@dataclass
class Spec:
    dataset: Dataset
    group_by: list[tuple[Dim, str]]  # (dimension, grain or "")
    measures: list[Measure]
    filters: list[tuple[Dim, str, Any]]
    period: periods.Period | None
    preset: str
    ordering: str
    limit: int
    chart: str
    currency: str
    clean: dict[str, Any] = field(default_factory=dict)  # the normalised definition


def _str_list(value: Any, name: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise invalid(name, _("Give a list of names."))
    return value


def _filter_value(dim: Dim, op: str, value: Any) -> Any:
    if op in ("empty", "not_empty"):
        return None
    values = value if op == "in" else [value]
    if op == "in" and (not isinstance(value, list) or not value or len(value) > 50):
        raise invalid("filters", _("Give between 1 and 50 values."))
    out: list[Any] = []
    for raw in values:
        if dim.type == "id":
            try:
                out.append(str(uuid.UUID(str(raw))))
            except ValueError as exc:
                raise invalid("filters", _("Not a valid id.")) from exc
        elif dim.type == "choice":
            if str(raw) not in {v for v, _lbl in dim.choices}:
                raise invalid("filters", _("Not one of the choices."))
            out.append(str(raw))
        elif dim.type == "date":
            try:
                out.append(date.fromisoformat(str(raw)))
            except ValueError as exc:
                raise invalid("filters", _("Use dates like 2026-01-31.")) from exc
        elif dim.type == "bool":
            if not isinstance(raw, bool):
                raise invalid("filters", _("Use true or false."))
            out.append(raw)
        elif dim.type == "number":
            try:
                out.append(Decimal(str(raw)))
            except ArithmeticError as exc:
                raise invalid("filters", _("Enter a number.")) from exc
        else:
            text = str(raw)
            if len(text) > 200:
                raise invalid("filters", _("Use at most 200 characters."))
            out.append(text)
    return out if op == "in" else out[0]


def parse(user: Any, definition: Mapping[str, Any]) -> Spec:
    """Validate a definition against its dataset (names only, never field paths)."""
    if not isinstance(definition, Mapping):
        raise invalid("definition", _("Give the report definition."))
    ds = dataset_for(str(definition.get("dataset", "")), user)
    known = ds.all_dims()
    group_by: list[tuple[Dim, str]] = []
    for name in _str_list(definition.get("group_by"), "group_by")[: MAX_GROUPS + 1]:
        key, _sep, grain = name.partition(":")
        dim = known.get(key)
        if dim is None:
            raise invalid("group_by", _("Unknown column: %(name)s") % {"name": key})
        if dim.type == "date":
            grain = grain or "day"
            if grain not in GRAINS:
                raise invalid("group_by", _("Group dates by day, week, month, quarter or year."))
        elif grain:
            raise invalid("group_by", _("Only dates can be grouped by period."))
        group_by.append((dim, grain))
    if len(group_by) > MAX_GROUPS:
        raise invalid("group_by", _("Group by at most %(n)s columns.") % {"n": MAX_GROUPS})
    by_key = {m.key: m for m in ds.measures}
    measures = []
    for name in _str_list(definition.get("measures"), "measures"):
        if name not in by_key:
            raise invalid("measures", _("Unknown measure: %(name)s") % {"name": name})
        if by_key[name] not in measures:
            measures.append(by_key[name])
    if len(measures) > MAX_MEASURES:
        raise invalid("measures", _("Choose at most %(n)s measures.") % {"n": MAX_MEASURES})
    if not group_by and not measures:
        raise invalid("measures", _("Choose columns or measures."))
    raw_filters = definition.get("filters") or []
    if not isinstance(raw_filters, list) or len(raw_filters) > MAX_FILTERS:
        raise invalid("filters", _("Use at most %(n)s filters.") % {"n": MAX_FILTERS})
    filters: list[tuple[Dim, str, Any]] = []
    clean_filters = []
    for row in raw_filters:
        if not isinstance(row, Mapping):
            raise invalid("filters", _("Each filter needs a field, an operator and a value."))
        dim = known.get(str(row.get("field", "")))
        op = str(row.get("op", "eq"))
        if dim is None:
            raise invalid("filters", _("Unknown column: %(name)s") % {"name": row.get("field")})
        if op not in OPS_BY_TYPE[dim.type]:
            raise invalid("filters", _("That comparison doesn't apply to this column."))
        value = _filter_value(dim, op, row.get("value"))
        filters.append((dim, op, value))
        clean_filters.append({"field": dim.key, "op": op, "value": row.get("value")})
    preset = str(definition.get("period") or "this_month")
    period = None
    if preset != ALL:
        try:
            start = date.fromisoformat(str(definition["from"])) if definition.get("from") else None
            end = date.fromisoformat(str(definition["to"])) if definition.get("to") else None
            if preset not in periods.PRESETS:
                raise ValueError(preset)
            period = periods.resolve(preset, start=start, end=end)
        except ValueError as exc:
            raise invalid("period", _("Choose a period, or a start and end date.")) from exc
        if period.days > 5 * 366:
            raise invalid("period", _("Choose a period of up to five years."))
    ordering = str(definition.get("ordering") or "")
    columns = {(f"{d.key}:{g}" if g else d.key) for d, g in group_by} | {m.key for m in measures}
    if ordering and ordering.lstrip("-") not in columns:
        raise invalid("ordering", _("Sort by one of the report's columns."))
    try:
        limit = int(definition.get("limit") or MAX_ROWS)
    except (TypeError, ValueError):
        limit = MAX_ROWS
    limit = max(1, min(limit, MAX_ROWS))
    chart = str(definition.get("chart") or "table")
    if chart not in CHARTS:
        raise invalid("chart", _("Choose a table, bar, line or pie chart."))
    currency = str(definition.get("currency") or "").upper()
    if currency:
        try:
            validate_currency(currency)
        except ValueError as exc:
            raise invalid("currency", _("Unknown currency.")) from exc
    clean = {
        "dataset": ds.key,
        "group_by": [f"{d.key}:{g}" if g else d.key for d, g in group_by],
        "measures": [m.key for m in measures],
        "filters": clean_filters,
        "period": preset,
        "from": period.start.isoformat() if period and preset == "custom" else "",
        "to": period.end.isoformat() if period and preset == "custom" else "",
        "ordering": ordering,
        "limit": limit,
        "chart": chart,
        "currency": currency,
    }
    return Spec(
        ds, group_by, measures, filters, period, preset, ordering, limit, chart, currency, clean
    )


# --- running ------------------------------------------------------------------------------------


def _column_key(dim: Dim, grain: str) -> str:
    return f"{dim.key}:{grain}" if grain else dim.key


def _alias(index: int) -> str:
    return f"g{index}"


def _apply_filters(qs: QuerySet[Any], spec: Spec, tz: str) -> QuerySet[Any]:
    ds = spec.dataset
    if spec.period is not None:
        date_dim = ds.all_dims()[ds.date]
        if date_dim.timestamp:
            start, end = spec.period.utc_bounds(tz)
            qs = qs.filter(**{f"{date_dim.lookup}__gte": start, f"{date_dim.lookup}__lt": end})
        else:
            qs = qs.filter(
                **{
                    f"{date_dim.lookup}__gte": spec.period.start,
                    f"{date_dim.lookup}__lte": spec.period.end,
                }
            )
    for dim, op, value in spec.filters:
        lookup = dim.lookup
        if dim.type == "date" and dim.timestamp:
            lookup = f"{lookup}__date"
        if op == "eq":
            qs = qs.filter(**{lookup: value})
        elif op == "neq":
            qs = qs.exclude(**{lookup: value})
        elif op == "in":
            qs = qs.filter(**{f"{lookup}__in": value})
        elif op == "gte":
            qs = qs.filter(**{f"{lookup}__gte": value})
        elif op == "lte":
            qs = qs.filter(**{f"{lookup}__lte": value})
        elif op == "contains":
            qs = qs.filter(**{f"{lookup}__icontains": value})
        elif op == "empty":
            qs = qs.filter(Q(**{f"{lookup}__isnull": True}) | Q(**{lookup: ""}))
        elif op == "not_empty":
            qs = qs.exclude(Q(**{f"{lookup}__isnull": True}) | Q(**{lookup: ""}))
    return qs


def _group_expression(dim: Dim, grain: str, tz: str) -> Any:
    if dim.type == "date":
        fn = GRAINS[grain]
        return fn(dim.lookup, tzinfo=ZoneInfo(tz)) if dim.timestamp else fn(dim.lookup)
    return F(dim.lookup)


def _quantise(value: Any, places: int) -> str:
    amount = value if isinstance(value, Decimal) else Decimal(str(value or 0))
    return str(amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def format_measure(measure: Measure, value: Any, currency: str) -> Any:
    """Raw aggregate → display value: counts as ints, money half-up to the currency's minor
    unit, hours with one decimal, other numbers half-up to two places."""
    if value is None:
        return "" if measure.agg != "count" else 0
    if measure.agg == "count":
        return int(value)
    if measure.type == "money":
        return _quantise(value, minor_units(currency) if currency else 2)
    if measure.type == "hours":
        return _quantise(Decimal(str(value)) / 60, 1)
    return _quantise(value, 2)


def _label(dim: Dim, grain: str, raw: Any, names: Mapping[str, str]) -> str:
    if raw is None or raw == "":
        return str(_("(none)"))
    if dim.type == "date":
        day = raw.date() if isinstance(raw, datetime) else raw
        return day.isoformat() if isinstance(day, date) else str(day)
    if dim.type == "choice":
        return str(dict(dim.choices).get(str(raw), raw))
    if dim.type == "bool":
        return str(_("Yes") if raw else _("No"))
    if dim.names:
        return names.get(str(raw), str(raw))
    if isinstance(raw, list):
        return ", ".join(str(v) for v in raw)
    return str(raw)


@dataclass
class Output:
    spec: Spec
    result: Result
    truncated: bool


def _timeout() -> None:
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = %s", [TIMEOUT_MS])


def run(user: Any, definition: Mapping[str, Any]) -> Output:
    """Validate, scope, query (with a timeout) and format a custom report."""
    spec = parse(user, definition)
    tz = periods.org_timezone()
    try:
        with transaction.atomic():
            _timeout()
            return _run(user, spec, tz)
    except OperationalError as exc:
        raise BusinessRuleViolation(
            str(_("This report took too long. Narrow the period or add filters."))
        ) from exc


def _run(user: Any, spec: Spec, tz: str) -> Output:
    ds = spec.dataset
    qs = ds.scope(user, ds.queryset(), ds.codename)
    qs = _apply_filters(qs, spec, tz)
    money = bool(ds.currency) and any(m.type == "money" for m in spec.measures)
    columns: list[Column] = []
    for dim, grain in spec.group_by:
        label = dim.label if not grain else f"{dim.label} ({GRAIN_LABELS[grain]})"
        columns.append(Column(_column_key(dim, grain), label, "date" if grain else "text"))
    if money:
        columns.append(Column("currency", _("Currency")))
    columns += [Column(m.key, m.label, m.column_type) for m in spec.measures]
    if not spec.measures:
        return _list_rows(spec, qs, columns, tz)
    aliases = {_alias(i): _group_expression(d, g, tz) for i, (d, g) in enumerate(spec.group_by)}
    keys = list(aliases) + (["_currency"] if money else [])
    if money:
        aliases["_currency"] = F(ds.currency)
    aggregates = {m.key: m.expression() for m in spec.measures}
    grouped = qs.annotate(**aliases).values(*keys).annotate(**aggregates)
    ordering = spec.ordering.lstrip("-")
    if ordering in aggregates:
        prefix = "-" if spec.ordering.startswith("-") else ""
        grouped = grouped.order_by(f"{prefix}{ordering}", *keys)
    else:
        grouped = grouped.order_by(*keys)
    raw_rows = list(grouped[: spec.limit + 1])
    truncated = len(raw_rows) > spec.limit
    raw_rows = raw_rows[: spec.limit]
    names: dict[int, dict[str, str]] = {}
    for i, (dim, _grain) in enumerate(spec.group_by):
        if dim.names:
            names[i] = dims.labels(dim.names, (r[_alias(i)] for r in raw_rows))
    rows = []
    for raw in raw_rows:
        currency = str(raw.get("_currency") or "") if money else ""
        row: dict[str, Any] = {}
        for i, (dim, grain) in enumerate(spec.group_by):
            row[_column_key(dim, grain)] = _label(dim, grain, raw[_alias(i)], names.get(i, {}))
            if dim.type == "date" and raw[_alias(i)] is not None:
                value = raw[_alias(i)]
                row["_fx_day"] = value.date() if isinstance(value, datetime) else value
        if money:
            row["currency"] = currency
        for m in spec.measures:
            row[m.key] = format_measure(m, raw[m.key], currency)
        rows.append(row)
    result = Result(columns=columns, rows=rows, chart=_chart(spec, columns))
    if ordering and ordering not in aggregates:
        reverse = spec.ordering.startswith("-")
        result.rows.sort(key=lambda r: str(r.get(ordering, "")).lower(), reverse=reverse)
    result.totals = _totals(spec, qs, money)
    if truncated:
        result.notes.append(
            str(_("Showing the first %(n)s rows. Add filters to see the rest.")) % {"n": spec.limit}
        )
    if spec.currency and money:
        default_day = spec.period.end if spec.period else periods.org_today()
        convert_currency(result, spec.currency, default_day)
        result.totals = _converted_totals(spec, result)
    for row in result.rows:
        row.pop("_fx_day", None)
    return Output(spec, result, truncated)


def _totals(spec: Spec, qs: QuerySet[Any], money: bool) -> list[dict[str, Any]]:
    """Aggregates over every filtered row (per currency for money), not sums of rows."""
    aggregates = {m.key: m.expression() for m in spec.measures}
    if money:
        rows = list(
            qs.annotate(_currency=F(spec.dataset.currency))
            .values("_currency")
            .annotate(**aggregates)
            .order_by("_currency")
        )
    else:
        rows = [qs.aggregate(**aggregates)]
    out = []
    for raw in rows:
        currency = str(raw.get("_currency") or "") if money else ""
        total: dict[str, Any] = {"currency": currency} if money else {}
        for m in spec.measures:
            total[m.key] = format_measure(m, raw[m.key], currency)
        out.append(total)
    return out


def _converted_totals(spec: Spec, result: Result) -> list[dict[str, Any]]:
    """After converting to a reporting currency: counts and sums add up per currency;
    averages, minimums and maximums can't be rebuilt from rows and are left blank."""
    by: dict[str, dict[str, Decimal]] = {}
    for row in result.rows:
        bucket = by.setdefault(str(row.get("currency") or ""), {})
        for m in spec.measures:
            if m.agg in ("count", "sum") and row.get(m.key) not in (None, ""):
                bucket[m.key] = bucket.get(m.key, Decimal(0)) + Decimal(str(row[m.key]))
    out = []
    for currency, sums in sorted(by.items()):
        total: dict[str, Any] = {"currency": currency}
        for m in spec.measures:
            if m.agg == "count":
                total[m.key] = int(sums.get(m.key, 0))
            elif m.agg == "sum":
                total[m.key] = format_measure(m, sums.get(m.key, Decimal(0)), currency)
            else:
                total[m.key] = ""
        out.append(total)
    return out


def _list_rows(spec: Spec, qs: QuerySet[Any], columns: list[Column], tz: str) -> Output:
    aliases = {
        _alias(i): _group_expression(d, g or "day", tz) for i, (d, g) in enumerate(spec.group_by)
    }
    values = qs.annotate(**aliases).values(*aliases).order_by(*aliases)
    raw_rows = list(values[: spec.limit + 1])
    truncated = len(raw_rows) > spec.limit
    raw_rows = raw_rows[: spec.limit]
    names = {
        i: dims.labels(d.names, (r[_alias(i)] for r in raw_rows))
        for i, (d, _g) in enumerate(spec.group_by)
        if d.names
    }
    rows = [
        {
            _column_key(d, g): _label(d, g, raw[_alias(i)], names.get(i, {}))
            for i, (d, g) in enumerate(spec.group_by)
        }
        for raw in raw_rows
    ]
    result = Result(columns=columns, rows=rows, chart=None, totals=[])
    ordering = spec.ordering.lstrip("-")
    if ordering:
        result.rows.sort(
            key=lambda r: str(r.get(ordering, "")).lower(), reverse=spec.ordering.startswith("-")
        )
    if truncated:
        result.notes.append(
            str(_("Showing the first %(n)s rows. Add filters to see the rest.")) % {"n": spec.limit}
        )
    return Output(spec, result, truncated)


def _chart(spec: Spec, columns: list[Column]) -> dict[str, Any] | None:
    if spec.chart == "table" or not spec.group_by or not spec.measures:
        return None
    first = spec.group_by[0]
    return {
        "kind": spec.chart,
        "x": _column_key(*first),
        "y": [m.key for m in spec.measures][:4],
        "stacked": False,
    }
