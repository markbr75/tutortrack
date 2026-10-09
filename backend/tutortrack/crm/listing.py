"""Shared list behaviour for people records (FR-05-11): tag and custom-field filters, the
"missing required data" filter, and permissioned, audited CSV export."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable
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


def csv_export(
    request: Any,
    rows: Iterable[Any],
    columns: list[tuple[str, Callable[[Any], Any]]],
    *,
    filename: str,
    entity_type: str,
) -> HttpResponse:
    """Write a CSV (≤ 50,000 rows); the export itself is audited (FR-05-11, FR-29-2)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([name for name, _ in columns])
    count = 0
    for row in rows:
        if count >= EXPORT_LIMIT:
            break
        writer.writerow([_safe(getter(row)) for _, getter in columns])
        count += 1
    with transaction.atomic():
        from tutortrack.core.security_alerts import check_mass_export

        audit.record(
            request.organisation,
            "export",
            {"entity": [None, entity_type], "rows": [None, count]},
            object_repr=f"{entity_type} export",
        )
        check_mass_export(request.user, request.organisation.pk)
    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
