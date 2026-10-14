"""Shared list behaviour for people records (FR-05-11): tag and custom-field filters, the
"missing required data" filter, and permissioned, audited CSV export."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpResponse

from tutortrack.core import audit

from .custom_fields import missing_required
from .models import TaggedItem

EXPORT_LIMIT = 50_000


def apply_crm_filters(qs: QuerySet[Any], params: Any, entity_type: str) -> QuerySet[Any]:
    """``?tag=<id>`` (repeatable), ``?cf_<key>=value``, ``?missing_required=true``,
    ``?include_archived=true`` (archived records are hidden by default, FR-05-14)."""
    if params.get("include_archived") not in {"1", "true"} and hasattr(qs.model, "archived_at"):
        qs = qs.filter(archived_at__isnull=True)
    for tag_id in params.getlist("tag") if hasattr(params, "getlist") else []:
        tagged = TaggedItem.objects.filter(tag_id=tag_id, target_type=entity_type).values(
            "target_id"
        )
        qs = qs.filter(pk__in=[row["target_id"] for row in tagged])
    for key, value in params.items():
        if key.startswith("cf_") and value != "":
            field = key[3:]
            if value in {"true", "false"}:
                qs = qs.filter(**{f"custom_fields__{field}": value == "true"})
            else:
                qs = qs.filter(**{f"custom_fields__{field}__iexact": value})
    if params.get("missing_required") in {"1", "true"}:
        condition = Q()
        for key in missing_required(entity_type):
            condition |= ~Q(custom_fields__has_key=key)
        qs = qs.filter(condition) if condition else qs.none()
    return qs


def _safe(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in {"=", "+", "-", "@", "\t"} else text


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORT_FORMATS = ("csv", "xlsx")


def _numeric(value: Any) -> bool:
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def selected_ids(params: Any) -> list[str]:
    """``?ids=a,b,c``: export only the selected rows (bulk "export", FR-05-12)."""
    raw = params.get("ids", "") if hasattr(params, "get") else ""
    return [i.strip() for i in str(raw).split(",") if i.strip()][:EXPORT_LIMIT]


def table_export(
    request: Any,
    rows: Iterable[Any],
    columns: list[tuple[str, Callable[[Any], Any]]],
    *,
    filename: str,
    entity_type: str,
    file_format: str = "csv",
) -> HttpResponse:
    """Write a CSV or an Excel workbook (≤ 50,000 rows), formula-injection safe; the export
    itself is audited and counts towards mass-export alerts (FR-05-11, FR-29-2)."""
    file_format = file_format if file_format in EXPORT_FORMATS else "csv"
    header = [name for name, _ in columns]
    table: list[list[Any]] = []
    for row in rows:
        if len(table) >= EXPORT_LIMIT:
            break
        values = [getter(row) for _, getter in columns]
        table.append([v if _numeric(v) else _safe(v) for v in values])
    with transaction.atomic():
        from tutortrack.core.security_alerts import check_mass_export

        audit.record(
            request.organisation,
            "export",
            {
                "entity": [None, entity_type],
                "rows": [None, len(table)],
                "format": [None, file_format],
            },
            object_repr=f"{entity_type} export",
        )
        check_mass_export(request.user, request.organisation.pk)
    stem = filename.rsplit(".", 1)[0]
    if file_format == "xlsx":
        from tutortrack.reporting.exports import xlsx_bytes

        numeric = [any(_numeric(r[i]) for r in table) for i in range(len(header))]
        content: Any = xlsx_bytes(header, table, numeric, stem)
        response = HttpResponse(content, content_type=XLSX)
    else:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(header)
        writer.writerows(table)
        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{stem}.{file_format}"'
    return response


def csv_export(
    request: Any,
    rows: Iterable[Any],
    columns: list[tuple[str, Callable[[Any], Any]]],
    *,
    filename: str,
    entity_type: str,
) -> HttpResponse:
    """Write a CSV (≤ 50,000 rows); the export itself is audited (FR-05-11, FR-29-2)."""
    return table_export(request, rows, columns, filename=filename, entity_type=entity_type)
