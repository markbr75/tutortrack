"""Import pipeline writes (FR-28-1): upload → mapping → validation preview and dry run →
import in checkpointed chunks → error report → rollback within the window.

The API calls the request-side functions (create, map, submit, confirm, cancel, rollback);
``ImportWorkflow`` (``processes.py``) calls the activity-side functions (validate, import a
chunk, finish, roll back a chunk, finalise). Rows are applied one at a time, each in its own
savepoint, through the owning apps' services (``importers/``)."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import structlog
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError as DRFValidationError

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict, PermissionDenied
from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now
from tutortrack.core.workflows import signal
from tutortrack.tenancy.settings_service import get_setting

from . import events, files, mapping, parsing
from .importers import base as importers
from .importers.base import Context, Importer, RowError, normalise
from .importers.common import custom_field_specs, json_safe
from .models import ExportJob, ImportBatch, ImportRow, MigrationProject, SavedImportMapping, Source

logger = structlog.get_logger(__name__)
B = ImportBatch.Status
R = ImportRow.Status
CONNECTOR_SOURCES = {Source.TUTORCRUNCHER, Source.TEACHWORKS}
CUSTOM_FIELD_ENTITIES = {
    "clients": "people.client",
    "students": "people.student",
    "tutors": "people.tutor",
    "jobs": "jobs.job",
}
SAMPLE_ROWS = 5
WRITE_CHUNK = 500


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def importer_for(entity: str) -> Importer:
    found = importers.get(entity)
    if found is None:
        raise _invalid("entity", _("Unknown kind of record."))
    return found


def extra_fields(entity: str) -> list[Any]:
    entity_type = CUSTOM_FIELD_ENTITIES.get(entity)
    return custom_field_specs(entity_type) if entity_type else []


def allowed_fields(entity: str) -> set[str]:
    importer = importer_for(entity)
    return {f.key for f in importer.fields} | {f.key for f in extra_fields(entity)}


def check_permissions(user: Any, entity: str) -> None:
    importer = importer_for(entity)
    if not has_perm(user, "migration.import.manage"):
        raise PermissionDenied(_("You can't run imports."))
    missing = [p for p in importer.permissions if not has_perm(user, p)]
    if missing:
        raise PermissionDenied(
            _("Importing %(what)s needs permission to create them.") % {"what": importer.label}
        )


# --- context ------------------------------------------------------------------------------------


def org_defaults() -> tuple[str, str, str]:
    """(timezone, currency, date order) of the organisation in context."""
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Branch, Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    branch = Branch.objects.filter(is_default=True).first()
    currency = str(getattr(branch, "currency", "") or getattr(org, "currency", "") or "GBP")
    locale = str(getattr(org, "locale", "") or "en-GB")
    return str(org.timezone), currency, "MDY" if locale.endswith("US") else "DMY"


def context_for(batch: ImportBatch, importer: Importer) -> Context:
    from zoneinfo import ZoneInfo

    tz, currency, order = org_defaults()
    options = dict(batch.options or {})
    options.setdefault("series_min", get_setting("migration.series_min_lessons"))
    # External ids from spreadsheets share one namespace (whatever preset); API pulls
    # keep the source's own.
    system = options.get("system") or (
        batch.source if batch.source in CONNECTOR_SOURCES else "file"
    )
    cutover = options.get("cutover_date")
    if not cutover and batch.project_id:
        cutover = batch.project.cutover_date.isoformat()  # type: ignore[union-attr]
    upsert = options.get("upsert_key") or importer.default_upsert
    if upsert not in importer.upsert_keys:
        upsert = importer.default_upsert
    return Context(
        batch=batch,
        system=str(system),
        upsert_key=str(upsert),
        date_format=str(options.get("date_format") or order),
        cutover=date.fromisoformat(cutover) if cutover else now().astimezone(ZoneInfo(tz)).date(),
        currency=str(options.get("currency") or currency).upper(),
        timezone=str(options.get("timezone") or tz),
        options=options,
    )


# --- creating batches ---------------------------------------------------------------------------


def _source_for(filename: str, content_type: str) -> str:
    name = filename.lower()
    return (
        Source.XLSX
        if name.endswith((".xlsx", ".xlsm")) or "spreadsheetml" in content_type
        else Source.CSV
    )


def _clean_options(importer: Importer, options: dict[str, Any] | None) -> dict[str, Any]:
    options = dict(options or {})
    out: dict[str, Any] = {}
    if options.get("upsert_key") in importer.upsert_keys:
        out["upsert_key"] = options["upsert_key"]
    if options.get("date_format") in ("DMY", "MDY", "YMD", "auto"):
        out["date_format"] = options["date_format"]
    if options.get("cutover_date"):
        try:
            out["cutover_date"] = date.fromisoformat(str(options["cutover_date"])).isoformat()
        except ValueError as exc:
            raise _invalid("cutover_date", _("Enter a date (YYYY-MM-DD).")) from exc
    if options.get("currency"):
        from tutortrack.core.money import validate_currency

        try:
            out["currency"] = validate_currency(str(options["currency"]).upper())
        except ValueError as exc:
            raise _invalid("currency", _("Unknown currency.")) from exc
    if options.get("timezone"):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(str(options["timezone"]))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise _invalid("timezone", _("Unknown time zone.")) from exc
        out["timezone"] = str(options["timezone"])
    if options.get("system"):
        out["system"] = str(options["system"])[:20]
    return out


@transaction.atomic
def create_batch(
    *,
    user: Any,
    entity: str,
    headers: list[str],
    rows: list[dict[str, str]],
    source: str,
    filename: str = "",
    file: Any = None,
    preset: str = "",
    sheet: str = "",
    options: dict[str, Any] | None = None,
    saved_mapping: SavedImportMapping | None = None,
    project: Any = None,
    project_step: str = "",
) -> ImportBatch:
    importer = importer_for(entity)
    if preset and preset not in mapping.PRESETS:
        raise _invalid("preset", _("Unknown preset."))
    batch = ImportBatch(
        entity=entity,
        source=source,
        preset=preset,
        file=file,
        filename=filename[:255],
        sheet=sheet[:100],
        headers=headers,
        options=_clean_options(importer, options),
        requested_by=user if getattr(user, "is_authenticated", False) else None,
        project=project,
        project_step=project_step,
    )
    if saved_mapping is not None:
        if saved_mapping.entity != entity:
            raise _invalid("saved_mapping", _("That mapping is for another kind of record."))
        auto = mapping.automap(headers, importer, preset=preset, extra=extra_fields(entity))
        batch.mapping = {h: saved_mapping.mapping.get(h, auto[h]) for h in headers}
        batch.value_map = dict(saved_mapping.value_map)
        batch.options = {**_clean_options(importer, saved_mapping.options), **batch.options}
    else:
        batch.mapping = mapping.automap(
            headers, importer, preset=preset, extra=extra_fields(entity)
        )
        batch.value_map = mapping.default_values(preset, entity)
    batch.mapping = mapping.clean_mapping(batch.mapping, headers, allowed_fields(entity))
    batch.stats = {"rows": len(rows)}
    batch.save()
    ImportRow.objects.bulk_create(
        [
            ImportRow(organisation_id=batch.organisation_id, batch=batch, row_number=i, raw=raw)
            for i, raw in enumerate(rows, start=1)
        ],
        batch_size=WRITE_CHUNK,
    )
    audit.record_create(batch)
    return batch


def create_from_file(
    *,
    user: Any,
    file: Any,
    entity: str,
    preset: str = "",
    sheet: str = "",
    options: dict[str, Any] | None = None,
    saved_mapping: SavedImportMapping | None = None,
    project: Any = None,
    project_step: str = "",
) -> ImportBatch:
    """An uploaded CSV/XLSX (it must have passed the malware scan)."""
    check_permissions(user, entity)
    if file.status != file.Status.UPLOADED:
        raise Conflict(_("The file hasn't finished uploading."))
    if file.scan_status in (file.ScanStatus.PENDING,):
        raise Conflict(
            _("The file is still being checked for viruses; try again in a moment."),
            extra={"code": "scan_pending"},
        )
    if not file.is_downloadable:
        raise _invalid("file", _("This file can't be used."))
    try:
        data = files.read(file)
    except ValueError as exc:
        raise _invalid("file", _("The file is too large to import.")) from exc
    try:
        table = parsing.parse(
            data, filename=file.filename, content_type=file.content_type, sheet=sheet
        )
    except parsing.SpreadsheetError as exc:
        raise _invalid("file", str(exc)) from exc
    batch = create_batch(
        user=user,
        entity=entity,
        headers=table.headers,
        rows=table.rows,
        source=_source_for(file.filename, file.content_type),
        filename=file.filename,
        file=file,
        preset=preset,
        sheet=sheet,
        options=options,
        saved_mapping=saved_mapping,
        project=project,
        project_step=project_step,
    )
    if table.sheets or table.truncated:
        batch.stats = {**batch.stats, "sheets": table.sheets, "truncated": table.truncated}
        batch.save(update_fields=["stats", "updated_at"])
    return batch


def create_from_google_sheet(
    *,
    user: Any,
    url: str,
    entity: str,
    sheet: str = "",
    options: dict[str, Any] | None = None,
    saved_mapping: SavedImportMapping | None = None,
) -> ImportBatch:
    """A Google Sheet read with the user's read-only Google connection (FR-28-6)."""
    from .connectors import sheets

    check_permissions(user, entity)
    rows_raw, title = sheets.read_sheet(user, url, sheet)
    try:
        table = parsing.to_table(rows_raw)
    except parsing.SpreadsheetError as exc:
        raise _invalid("url", str(exc)) from exc
    return create_batch(
        user=user,
        entity=entity,
        headers=table.headers,
        rows=table.rows,
        source=Source.GOOGLE_SHEETS,
        filename=title,
        sheet=sheet,
        options=options,
        saved_mapping=saved_mapping,
    )


def _editable(batch: ImportBatch) -> None:
    if batch.status not in (B.MAPPING, B.VALIDATED):
        raise Conflict(_("This import can't be changed any more."))


@transaction.atomic
def update_mapping(
    batch: ImportBatch,
    *,
    column_map: dict[str, Any] | None = None,
    value_map: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> ImportBatch:
    batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    _editable(batch)
    importer = importer_for(batch.entity)
    with audit.track(batch, action="map"):
        if column_map is not None:
            unknown = {v for v in column_map.values() if v} - allowed_fields(batch.entity)
            if unknown:
                raise _invalid("mapping", _("Unknown field: %(f)s") % {"f": sorted(unknown)[0]})
            batch.mapping = mapping.clean_mapping(
                column_map, batch.headers, allowed_fields(batch.entity)
            )
        if value_map is not None:
            batch.value_map = {
                str(k): {str(a): str(b) for a, b in (v or {}).items()}
                for k, v in value_map.items()
                if isinstance(v, dict)
            }
        if options is not None:
            batch.options = {**batch.options, **_clean_options(importer, options)}
        revalidate = batch.status == B.VALIDATED
        if revalidate:
            batch.status = B.VALIDATING
        batch.save()
    if revalidate:
        signal(batch.workflow_id, "revalidate")
    return batch


@transaction.atomic
def save_mapping(batch: ImportBatch, *, name: str, user: Any) -> SavedImportMapping:
    name = name.strip()[:120]
    if not name:
        raise _invalid("name", _("Name the mapping."))
    saved, created = SavedImportMapping.objects.update_or_create(
        entity=batch.entity,
        name=name,
        defaults={
            "source": batch.source,
            "mapping": {k: v for k, v in batch.mapping.items() if v},
            "value_map": batch.value_map,
            "options": {k: v for k, v in batch.options.items() if k != "cutover_date"},
            "created_by": user,
        },
    )
    if created:
        audit.record_create(saved)
    else:
        audit.record(saved, "update", {"mapping": [None, len(saved.mapping)]})
    return saved


@transaction.atomic
def delete_saved_mapping(saved: SavedImportMapping) -> None:
    audit.record(saved, "delete", {"name": [saved.name, None]})
    saved.delete()


def missing_required(batch: ImportBatch) -> list[str]:
    importer = importer_for(batch.entity)
    mapped = set(batch.mapping.values())
    return [str(f.label) for f in importer.fields if f.required and f.key not in mapped]


@transaction.atomic
def submit(batch: ImportBatch, *, user: Any = None) -> ImportBatch:
    """Mapping done: validate and dry-run in the background (``ImportWorkflow``)."""
    from .processes import import_workflow_id

    batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status != B.MAPPING:
        raise Conflict(_("This import was already submitted."))
    missing = missing_required(batch)
    if missing:
        raise _invalid(
            "mapping", _("Map a column to: %(fields)s.") % {"fields": ", ".join(missing)}
        )
    with audit.track(batch, action="submit"):
        batch.status = B.VALIDATING
        batch.workflow_id = import_workflow_id(batch.organisation_id, batch.pk)
        batch.save(update_fields=["status", "workflow_id", "updated_at"])
    publish(events.ImportSubmitted(subject_id=batch.pk, entity=batch.entity, source=batch.source))
    return batch


@transaction.atomic
def confirm(batch: ImportBatch, *, user: Any = None) -> ImportBatch:
    batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status != B.VALIDATED:
        raise Conflict(_("Check the file first; it isn't ready to import."))
    if not batch.stats.get("valid"):
        raise BusinessRuleViolation(_("No rows can be imported. Fix the file and try again."))
    with audit.track(batch, action="confirm"):
        batch.confirmed_at = now()
        batch.status = B.IMPORTING
        batch.save(update_fields=["confirmed_at", "status", "updated_at"])
    signal(batch.workflow_id, "confirm")
    return batch


@transaction.atomic
def cancel(batch: ImportBatch, *, user: Any = None) -> ImportBatch:
    batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status not in (B.MAPPING, B.VALIDATING, B.VALIDATED, B.IMPORTING):
        raise Conflict(_("This import has finished; roll it back instead."))
    with audit.track(batch, action="cancel"):
        if batch.status in (B.MAPPING,) or not batch.workflow_id:
            batch.status = B.CANCELLED
            batch.save(update_fields=["status", "updated_at"])
        else:
            batch.options = {**batch.options, "cancel_requested": True}
            batch.save(update_fields=["options", "updated_at"])
    if batch.workflow_id and batch.status != B.CANCELLED:
        signal(batch.workflow_id, "cancel")
    return batch


@transaction.atomic
def request_rollback(batch: ImportBatch, *, user: Any = None) -> ImportBatch:
    batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    if not batch.can_rollback:
        raise Conflict(_("This import can no longer be rolled back."))
    with audit.track(batch, action="rollback"):
        batch.status = B.ROLLING_BACK
        batch.save(update_fields=["status", "updated_at"])
    signal(batch.workflow_id, "rollback")
    return batch


# --- preview ------------------------------------------------------------------------------------


def distinct_values(batch: ImportBatch, column: str, limit: int = 50) -> list[str]:
    from django.db.models.fields.json import KeyTextTransform

    if column not in batch.headers:
        return []
    values = (
        ImportRow.objects.filter(batch=batch)
        .annotate(v=KeyTextTransform(column, "raw"))
        .values_list("v", flat=True)
        .distinct()
        .order_by("v")[: limit + 1]
    )
    return [v for v in values if v not in (None, "")][:limit]


def preview(batch: ImportBatch) -> dict[str, Any]:
    importer = importer_for(batch.entity)
    specs = [*importer.fields, *extra_fields(batch.entity)]
    choice_fields = {s.key for s in specs if s.type in ("choice", "bool", "weekday")}
    values = {
        column: distinct_values(batch, column)
        for column, key in batch.mapping.items()
        if key in choice_fields
    }
    sample = list(batch.rows.order_by("row_number")[:SAMPLE_ROWS].values_list("raw", flat=True))
    return {
        "headers": batch.headers,
        "column_map": batch.mapping,
        "value_map": batch.value_map,
        "options": batch.options,
        "sample": sample,
        "distinct": values,
        "field_specs": [s.describe() for s in specs],
        "upsert_keys": list(importer.upsert_keys),
        "missing_required": missing_required(batch),
    }


# --- activity side: validation and dry run -----------------------------------------------------


def _values(importer: Importer, batch: ImportBatch, row: ImportRow, ctx: Context) -> dict[str, Any]:
    values = normalise(
        importer, row.raw, batch.mapping, batch.value_map, ctx, ctx.cache.get("extra_fields")
    )
    for key, value in (row.values or {}).items():
        if key.startswith("_"):
            values[key] = value
    return values


def validate(batch_id: Any, heartbeat: Any = None) -> dict[str, Any]:
    """Check every row and work out what importing it will do (the dry run)."""
    batch = ImportBatch.objects.select_related("project").get(pk=batch_id)
    if batch.status not in (B.VALIDATING, B.VALIDATED):
        return dict(batch.stats)
    importer = importer_for(batch.entity)
    ctx = context_for(batch, importer)
    rows = list(batch.rows.order_by("row_number"))
    custom = extra_fields(batch.entity)
    normalised: list[tuple[ImportRow, dict[str, Any], list[Any]]] = []
    for row in rows:
        ctx.reset_row(row.row_number)
        values = normalise(importer, row.raw, batch.mapping, batch.value_map, ctx, custom)
        normalised.append((row, values, list(ctx.errors)))
    importer.prepare([(r.row_number, v) for r, v, errs in normalised if not errs], ctx)
    plans: Counter[tuple[str, str]] = Counter()
    actions: Counter[str] = Counter()
    for index, (row, values, errors) in enumerate(normalised):
        ctx.reset_row(row.row_number)
        ctx.errors = list(errors)
        extra: dict[str, Any] = {}
        plan = None
        if not errors:
            try:
                plan = importer.check(values, ctx)
                extra = plan.extra
            except RowError as exc:
                ctx.error(exc.field, str(exc))
            except Exception:
                logger.exception(
                    "import.validate_row_failed", batch=str(batch.pk), row=row.row_number
                )
                ctx.error("", _("This row couldn't be checked."))
        row.values = json_safe({**values, **extra})
        row.errors = [i.as_dict() for i in ctx.errors]
        row.warnings = [i.as_dict() for i in ctx.warnings]
        if ctx.errors or plan is None:
            row.status, row.action = R.INVALID, ""
        else:
            row.status, row.action = R.VALID, plan.action
            row.target_type, row.target_id = plan.target_type, plan.target_id
            actions[plan.action] += 1
            for effect in plan.effects:
                plans[effect] += 1
        if heartbeat and index % 200 == 0:
            heartbeat(index)
    ImportRow.objects.bulk_update(
        rows,
        ["values", "errors", "warnings", "status", "action", "target_type", "target_id"],
        batch_size=WRITE_CHUNK,
    )
    invalid = sum(1 for r in rows if r.status == R.INVALID)
    will: dict[str, dict[str, int]] = defaultdict(dict)
    for (target, verb), count in plans.items():
        will[target][verb] = count
    stats = {
        **{k: v for k, v in batch.stats.items() if k in ("sheets", "truncated")},
        "rows": len(rows),
        "valid": len(rows) - invalid,
        "invalid": invalid,
        "warnings": sum(1 for r in rows if r.warnings),
        "actions": dict(actions),
        "will": dict(will),
    }
    with transaction.atomic():
        locked = ImportBatch.objects.select_for_update().get(pk=batch.pk)
        if locked.status == B.VALIDATING:
            locked.status = B.VALIDATED
        locked.stats = stats
        locked.validated_at = now()
        locked.save(update_fields=["stats", "status", "validated_at", "updated_at"])
        publish(
            events.ImportValidated(
                subject_id=batch.pk, entity=batch.entity, source=batch.source, stats=stats
            )
        )
    return stats


# --- activity side: import ----------------------------------------------------------------------

ROW_FAILURES = (
    BusinessRuleViolation,
    RowError,
    DjangoValidationError,
    DRFValidationError,
    IntegrityError,
    ValueError,
    KeyError,
    LookupError,
)


def _message(exc: Exception) -> str:
    if isinstance(exc, DRFValidationError):
        detail = exc.detail
        if isinstance(detail, dict):
            parts = []
            for key, value in detail.items():
                if isinstance(value, dict):
                    shown = "; ".join(f"{k}: {v}" for k, v in value.items())
                elif isinstance(value, list):
                    shown = "; ".join(str(v) for v in value)
                else:
                    shown = str(value)
                parts.append(f"{key}: {shown}")
            return "; ".join(parts)[:500]
        return str(detail)[:500]
    if isinstance(exc, DjangoValidationError):
        return "; ".join(exc.messages)[:500]
    if isinstance(exc, IntegrityError):
        return _("It clashes with an existing record.")
    return str(getattr(exc, "detail", None) or exc)[:500] or exc.__class__.__name__


def start_import(batch_id: Any) -> str:
    with transaction.atomic():
        batch = ImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status in (B.VALIDATED, B.IMPORTING):
            batch.status = B.IMPORTING
            batch.confirmed_at = batch.confirmed_at or now()
            batch.save(update_fields=["status", "confirmed_at", "updated_at"])
        return str(batch.status)


def import_chunk(batch_id: Any, after_row: int, size: int, heartbeat: Any = None) -> dict[str, Any]:
    """Apply the next ``size`` valid rows after ``after_row`` (idempotent per row: applied
    rows change status in the same savepoint as their records)."""
    batch = ImportBatch.objects.select_related("project").get(pk=batch_id)
    importer = importer_for(batch.entity)
    ctx = context_for(batch, importer)
    ctx.cache["extra_fields"] = extra_fields(batch.entity)
    rows = list(batch.rows.filter(row_number__gt=after_row).order_by("row_number")[:size])
    counts: Counter[str] = Counter()
    for index, row in enumerate(rows):
        if row.status != R.VALID:
            continue
        if row.action == "skip":  # the dry run found nothing to do (duplicate, already there)
            row.status, row.applied_at = R.SKIPPED, now()
            row.save(update_fields=["status", "applied_at", "updated_at"])
            counts[str(row.status)] += 1
            continue
        ctx.reset_row(row.row_number)
        values = _values(importer, batch, row, ctx)
        try:
            with transaction.atomic():
                if ctx.errors:
                    raise RowError("; ".join(i.message for i in ctx.errors))
                outcome = importer.apply(values, ctx)
                row.status = {
                    "create": R.CREATED,
                    "update": R.UPDATED,
                    "skip": R.SKIPPED,
                }[outcome.action]
                row.target_type = outcome.target_type or row.target_type
                row.target_id = outcome.target_id or row.target_id
                row.created_refs = outcome.created
                row.previous = json_safe(outcome.previous)
                row.warnings = [
                    *row.warnings,
                    *({"field": "", "message": w} for w in outcome.warnings),
                ]
                row.applied_at = now()
                row.save(
                    update_fields=[
                        "status",
                        "target_type",
                        "target_id",
                        "created_refs",
                        "previous",
                        "warnings",
                        "applied_at",
                        "updated_at",
                    ]
                )
        except ROW_FAILURES as exc:
            row.status = R.FAILED
            row.errors = [
                *row.errors,
                {"field": getattr(exc, "field", ""), "message": _message(exc)},
            ]
            row.applied_at = now()
            row.save(update_fields=["status", "errors", "applied_at", "updated_at"])
        counts[str(row.status)] += 1
        if heartbeat and index % 25 == 0:
            heartbeat(row.row_number)
    last = rows[-1].row_number if rows else after_row
    done = not rows or not batch.rows.filter(row_number__gt=last).exists()
    return {"last_row": last, "done": done, "counts": dict(counts)}


def _error_report(batch: ImportBatch) -> Any:
    rows = batch.rows.filter(status__in=[R.INVALID, R.FAILED]).order_by("row_number")
    if not rows.exists():
        return None
    headers = [_("Row"), *batch.headers, _("Status"), _("Problems")]
    lines = []
    for row in rows.iterator(chunk_size=WRITE_CHUNK):
        problems = "; ".join(e.get("message", "") for e in row.errors)
        lines.append(
            [
                row.row_number,
                *[row.raw.get(h, "") for h in batch.headers],
                row.get_status_display(),
                problems,
            ]
        )
    data = parsing.to_csv([str(h) for h in headers], lines)
    stem = (batch.filename.rsplit(".", 1)[0] or batch.entity)[:80]
    return files.save(batch, f"{stem}-errors.csv", "text/csv", data, kind="imports")


def finish_import(batch_id: Any) -> str:
    """Counts, the error report and the rollback window."""
    batch = ImportBatch.objects.get(pk=batch_id)
    counts = Counter(batch.rows.values_list("status", flat=True))
    days = int(get_setting("migration.rollback_days") or 7)
    error_file = _error_report(batch)
    with transaction.atomic():
        batch = ImportBatch.objects.select_for_update().get(pk=batch_id)
        batch.stats = {
            **batch.stats,
            "created": counts.get(R.CREATED, 0),
            "updated": counts.get(R.UPDATED, 0),
            "skipped": counts.get(R.SKIPPED, 0),
            "failed": counts.get(R.FAILED, 0),
            "invalid": counts.get(R.INVALID, 0),
            "imported": counts.get(R.CREATED, 0) + counts.get(R.UPDATED, 0),
        }
        batch.error_file = error_file or batch.error_file
        batch.status = B.COMPLETED
        batch.completed_at = now()
        batch.rollback_until = batch.completed_at + timedelta(days=days)
        batch.save()
        audit.record(batch, "complete", {"imported": [None, batch.stats["imported"]]})
        publish(
            events.ImportCompleted(
                subject_id=batch.pk,
                entity=batch.entity,
                source=batch.source,
                stats=batch.stats,
                rollback_until=batch.rollback_until.isoformat(),
            )
        )
    return batch.rollback_until.isoformat()


def finish_validation_only(batch_id: Any, status: str, error: str = "") -> None:
    """The import stops before rows are applied: cancelled, expired or failed."""
    with transaction.atomic():
        batch = ImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status in (B.COMPLETED, B.ROLLED_BACK, B.FINALISED):
            return
        batch.status = status
        batch.error = error[:2000]
        batch.save(update_fields=["status", "error", "updated_at"])
        if status == B.FAILED:
            publish(
                events.ImportFailed(
                    subject_id=batch.pk, entity=batch.entity, source=batch.source, error=error[:500]
                )
            )


def cancel_import(batch_id: Any) -> None:
    """Stopped while importing: what was imported stays and can be rolled back."""
    batch = ImportBatch.objects.get(pk=batch_id)
    if batch.rows.filter(status__in=[R.CREATED, R.UPDATED, R.SKIPPED, R.FAILED]).exists():
        batch.rows.filter(status=R.VALID).update(status=R.SKIPPED, action="skip")
        finish_import(batch_id)
        return
    finish_validation_only(batch_id, B.CANCELLED)


# --- activity side: rollback --------------------------------------------------------------------


def rollback_chunk(batch_id: Any, before_row: int, size: int) -> dict[str, Any]:
    """Undo up to ``size`` applied rows below ``before_row``, newest first."""
    batch = ImportBatch.objects.select_related("project").get(pk=batch_id)
    importer = importer_for(batch.entity)
    ctx = context_for(batch, importer)
    rows = list(
        batch.rows.filter(row_number__lt=before_row, status__in=[R.CREATED, R.UPDATED]).order_by(
            "-row_number"
        )[:size]
    )
    for row in rows:
        ctx.reset_row(row.row_number)
        complete = importer.undo(row, ctx)
        row.status = R.ROLLED_BACK if complete else R.KEPT
        row.save(update_fields=["status", "updated_at"])
    last = rows[-1].row_number if rows else 0
    return {"before_row": last, "done": len(rows) < size}


def finish_rollback(batch_id: Any) -> dict[str, int]:
    with transaction.atomic():
        batch = ImportBatch.objects.select_for_update().get(pk=batch_id)
        counts = Counter(batch.rows.values_list("status", flat=True))
        result = {"reverted": counts.get(R.ROLLED_BACK, 0), "kept": counts.get(R.KEPT, 0)}
        batch.stats = {**batch.stats, **result}
        batch.status = B.ROLLED_BACK
        batch.rolled_back_at = now()
        batch.save(update_fields=["stats", "status", "rolled_back_at", "updated_at"])
        audit.record(batch, "rolled_back", {"reverted": [None, result["reverted"]]})
        publish(
            events.ImportRolledBack(
                subject_id=batch.pk, entity=batch.entity, source=batch.source, **result
            )
        )
    return result


def finalise(batch_id: Any) -> bool:
    with transaction.atomic():
        batch = ImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status != B.COMPLETED:
            return False
        batch.status = B.FINALISED
        batch.finalised_at = now()
        batch.save(update_fields=["status", "finalised_at", "updated_at"])
        publish(
            events.ImportFinalised(subject_id=batch.pk, entity=batch.entity, source=batch.source)
        )
    return True


# --- templates ----------------------------------------------------------------------------------


def template_csv(entity: str) -> bytes:
    importer = importer_for(entity)
    specs = [*importer.fields, *extra_fields(entity)]
    example = importer.example
    return parsing.to_csv([str(s.label) for s in specs], [[example.get(s.key, "") for s in specs]])


# === migration projects: the cutover assistant (FR-28-2) =========================================

STEPS: list[tuple[str, tuple[str, ...]]] = [
    ("people", ("clients", "students", "tutors")),
    ("services", ("services",)),
    ("jobs", ("jobs", "lessons", "availability")),
    ("balances", ("opening_balances", "invoices", "payments", "packages")),
    ("payment_methods", ()),
    ("invite_users", ()),
    ("reminders", ()),
]
STEP_KEYS = [key for key, _entities in STEPS]
API_SOURCES = {Source.TUTORCRUNCHER, Source.TEACHWORKS}
PROJECT_SOURCES = {Source.TUTORCRUNCHER, Source.TEACHWORKS, Source.TUTORBIRD, Source.CSV}
OPEN_BATCH = (B.MAPPING, B.VALIDATING, B.VALIDATED, B.IMPORTING, B.ROLLING_BACK)


def step_entities(step: str) -> tuple[str, ...]:
    return dict(STEPS).get(step, ())


@transaction.atomic
def create_project(
    *,
    user: Any,
    name: str,
    source: str,
    cutover_date: date,
    api_key: str = "",
) -> MigrationProject:
    """Start the cutover assistant. API sources connect with the key first (stored
    encrypted on the integration framework's connection)."""
    from .processes import project_workflow_id

    if source not in PROJECT_SOURCES:
        raise _invalid("source", _("Choose where you are moving from."))
    connection = None
    if source in API_SOURCES:
        from tutortrack.integrations import services as integrations

        if not api_key.strip():
            raise _invalid("api_key", _("Enter the API key from your current system."))
        connection = integrations.connect_with_credentials(
            user, provider=source, level="organisation", api_key=api_key.strip()
        )
    project = MigrationProject.objects.create(
        name=name.strip()[:120] or str(dict(Source.choices)[source]),
        source=source,
        connection=connection,
        cutover_date=cutover_date,
        steps={key: {"status": "pending"} for key in STEP_KEYS},
        current_step=STEP_KEYS[0],
        created_by=user,
    )
    project.workflow_id = project_workflow_id(project.organisation_id, project.pk)
    project.save(update_fields=["workflow_id"])
    audit.record_create(project)
    publish(
        events.MigrationProjectStarted(
            subject_id=project.pk, source=source, cutover_date=cutover_date.isoformat()
        )
    )
    return project


def start_step(project_id: Any, step: str) -> list[str]:
    """Activity: mark the step started and, for API sources, pull its records into import
    batches (validated in the background; the user reviews and confirms each)."""
    from .connectors import base as connectors

    project = MigrationProject.objects.get(pk=project_id)
    state = dict(project.steps.get(step) or {})
    if state.get("status") in ("in_progress", "done", "skipped"):
        return list(state.get("batches") or [])
    batch_ids: list[str] = []
    if project.source in API_SOURCES and project.connection is not None:
        source = connectors.source_for(project.source)
        creds = connectors.credentials(project.connection)
        for entity in step_entities(step):
            if not source.supports(entity):
                continue
            rows = list(source.fetch(creds, entity, cutover=project.cutover_date))
            if not rows:
                continue
            headers = sorted({k for row in rows for k in row})
            text_rows = [
                {k: "" if row.get(k) is None else str(row[k]) for k in headers} for row in rows
            ]
            with transaction.atomic():
                batch = create_batch(
                    user=project.created_by,
                    entity=entity,
                    headers=headers,
                    rows=text_rows,
                    source=project.source,
                    filename=f"{project.get_source_display()}: {entity}",
                    options={"system": project.source, "date_format": "YMD"},
                    project=project,
                    project_step=step,
                )
                submit(batch)
            batch_ids.append(str(batch.pk))
    with transaction.atomic():
        locked = MigrationProject.objects.select_for_update().get(pk=project_id)
        locked.steps = {
            **locked.steps,
            step: {
                **state,
                "status": "in_progress",
                "started_at": now().isoformat(),
                "batches": batch_ids,
            },
        }
        locked.current_step = step
        locked.save(update_fields=["steps", "current_step", "updated_at"])
    return batch_ids


@transaction.atomic
def complete_step(
    project: MigrationProject, step: str, *, skip: bool = False, note: str = ""
) -> MigrationProject:
    """The user confirms a step (or skips it); the workflow moves on."""
    project = MigrationProject.objects.select_for_update().get(pk=project.pk)
    if project.status != MigrationProject.Status.ACTIVE:
        raise Conflict(_("This migration has finished."))
    if step != project.current_step:
        raise Conflict(_("Finish the current step first."))
    if not skip and project.batches.filter(project_step=step, status__in=OPEN_BATCH).exists():
        raise BusinessRuleViolation(_("Finish or cancel this step's imports first."))
    with audit.track(project, action="step_done"):
        project.steps = {
            **project.steps,
            step: {
                **(project.steps.get(step) or {}),
                "status": "skipped" if skip else "done",
                "completed_at": now().isoformat(),
                "note": note[:500],
            },
        }
        index = STEP_KEYS.index(step)
        project.current_step = STEP_KEYS[index + 1] if index + 1 < len(STEP_KEYS) else ""
        project.save(update_fields=["steps", "current_step", "updated_at"])
    publish(events.MigrationStepCompleted(subject_id=project.pk, step=step, skipped=skip))
    signal(project.workflow_id, "step_done", step)
    return project


@transaction.atomic
def cancel_project(project: MigrationProject) -> MigrationProject:
    project = MigrationProject.objects.select_for_update().get(pk=project.pk)
    if project.status != MigrationProject.Status.ACTIVE:
        raise Conflict(_("This migration has finished."))
    with audit.track(project, action="cancel"):
        project.status = MigrationProject.Status.CANCELLED
        project.save(update_fields=["status", "updated_at"])
    signal(project.workflow_id, "cancel")
    return project


def invite_imported_tutors(project: MigrationProject) -> int:
    """Step "invite users": tutors this migration created get their invitation."""
    from tutortrack.identity.models import Invitation, Membership
    from tutortrack.identity.services import invite
    from tutortrack.people.models import TutorProfile

    ids = ImportRow.objects.filter(
        batch__project=project, batch__entity="tutors", status=R.CREATED
    ).values_list("target_id", flat=True)
    sent = 0
    for tutor in TutorProfile.objects.filter(pk__in=list(ids), membership__isnull=True):
        if Invitation.objects.filter(email=tutor.email, status=Invitation.Status.PENDING).exists():
            continue
        with transaction.atomic():
            invite(
                tutor.email,
                role=Membership.Role.TUTOR,
                target_type="people.tutor",
                target_id=str(tutor.pk),
            )
        sent += 1
    with transaction.atomic():
        audit.record(project, "invite_tutors", {"sent": [None, sent]})
    return sent


def _imported_totals(project: MigrationProject) -> dict[str, Any]:
    from tutortrack.scheduling.models import Lesson

    rows = ImportRow.objects.filter(batch__project=project)
    done = rows.filter(status__in=[R.CREATED, R.UPDATED, R.SKIPPED])
    counts = Counter(done.values_list("batch__entity", flat=True))
    balance = Decimal(0)
    for refs_list in rows.filter(batch__entity="opening_balances", status=R.UPDATED).values_list(
        "created_refs", flat=True
    ):
        for item in refs_list or []:
            if item.get("type") == "billing.ledgeradjustment":
                balance += Decimal(str(item.get("amount") or 0))
    lesson_rows = list(
        rows.filter(batch__entity="lessons", status=R.CREATED).values_list(
            "target_type", "target_id"
        )
    )
    lesson_ids = [i for t, i in lesson_rows if t == "scheduling.lesson"]
    series_ids = [i for t, i in lesson_rows if t == "scheduling.lessonseries"]
    cutover = datetime.combine(project.cutover_date, time.min, tzinfo=UTC)
    future = (
        Lesson.objects.filter(start__gte=cutover)
        .filter(Q(pk__in=lesson_ids) | Q(series_id__in=series_ids))
        .count()
    )
    return {
        "clients": counts.get("clients", 0),
        "students": counts.get("students", 0),
        "tutors": counts.get("tutors", 0),
        "jobs": counts.get("jobs", 0),
        "invoices": counts.get("invoices", 0),
        "balances_sum": str(balance),
        "future_lessons": future,
    }


def _source_totals_from_files(project: MigrationProject) -> dict[str, Any]:
    rows = ImportRow.objects.filter(batch__project=project).exclude(batch__status=B.CANCELLED)
    counts = Counter(rows.values_list("batch__entity", flat=True))
    balance = Decimal(0)
    for values in rows.filter(batch__entity="opening_balances").values_list("values", flat=True):
        values = values or {}
        try:
            amount = Decimal(str(values.get("balance") or 0))
        except ArithmeticError:
            continue
        if values.get("direction") == "credit":
            amount = -abs(amount)
        elif values.get("direction") == "owes":
            amount = abs(amount)
        balance += amount
    future = 0
    for values in rows.filter(batch__entity="lessons").values_list("values", flat=True):
        values = values or {}
        day = str(values.get("date") or "")
        if day >= project.cutover_date.isoformat() and values.get("status") in (
            None,
            "",
            "planned",
        ):
            future += 1
    return {
        "clients": counts.get("clients", 0),
        "students": counts.get("students", 0),
        "tutors": counts.get("tutors", 0),
        "jobs": counts.get("jobs", 0),
        "invoices": counts.get("invoices", 0),
        "balances_sum": str(balance),
        "future_lessons": future,
    }


RECONCILED = ("clients", "students", "tutors", "jobs", "invoices", "balances_sum", "future_lessons")


def reconcile(project_id: Any) -> dict[str, Any]:
    """Activity: compare the source's totals with what was imported (FR-28-2)."""
    from .connectors import base as connectors

    project = MigrationProject.objects.get(pk=project_id)
    if project.source in API_SOURCES and project.connection is not None:
        source = connectors.source_for(project.source)
        totals = source.totals(
            connectors.credentials(project.connection), cutover=project.cutover_date
        )
    else:
        totals = _source_totals_from_files(project)
    imported = _imported_totals(project)
    lines = []
    for metric in RECONCILED:
        src, got = totals.get(metric), imported.get(metric)
        if src is None or got is None:
            continue
        diff = Decimal(str(got)) - Decimal(str(src))
        lines.append(
            {
                "metric": metric,
                "source": str(src),
                "imported": str(got),
                "difference": str(diff),
                "ok": diff == 0,
            }
        )
    report = {
        "generated_at": now().isoformat(),
        "lines": lines,
        "ok": all(line["ok"] for line in lines),
    }
    with transaction.atomic():
        locked = MigrationProject.objects.select_for_update().get(pk=project_id)
        locked.source_totals = json_safe(totals)
        locked.reconciliation = report
        if locked.status == MigrationProject.Status.ACTIVE:
            locked.status = MigrationProject.Status.COMPLETED
            locked.completed_at = now()
            publish(events.MigrationProjectCompleted(subject_id=locked.pk, source=locked.source))
        locked.save()
        audit.record(locked, "reconciled", {"ok": [None, report["ok"]]})
    return report


def expire_project(project_id: Any) -> None:
    with transaction.atomic():
        project = MigrationProject.objects.select_for_update().get(pk=project_id)
        if project.status == MigrationProject.Status.ACTIVE:
            project.status = MigrationProject.Status.CANCELLED
            project.save(update_fields=["status", "updated_at"])


# === full tenant export (FR-28-7) ================================================================


@transaction.atomic
def request_export(*, user: Any = None, reason: str = "") -> ExportJob:
    """The owner asks for everything (or account closure / the platform did)."""
    from .processes import export_workflow_id

    if user is not None and not has_perm(user, "migration.export.full"):
        raise PermissionDenied(_("Only the owner can export all data."))
    running = ExportJob.objects.filter(
        status__in=[ExportJob.Status.REQUESTED, ExportJob.Status.RUNNING]
    ).first()
    if running is not None:
        return running
    job = ExportJob.objects.create(
        requested_by=user if getattr(user, "is_authenticated", False) else None,
        reason=reason[:200],
    )
    job.workflow_id = export_workflow_id(job.organisation_id, job.pk)
    job.save(update_fields=["workflow_id"])
    audit.record_create(job)
    publish(events.ExportRequested(subject_id=job.pk, kind=job.kind, reason=job.reason))
    return job


def export_plan(export_id: Any) -> list[str]:
    from . import exporter

    with transaction.atomic():
        job = ExportJob.objects.select_for_update().get(pk=export_id)
        if job.status == ExportJob.Status.REQUESTED:
            job.status = ExportJob.Status.RUNNING
            job.save(update_fields=["status", "updated_at"])
    done = set((job.progress or {}).keys())
    return [name for name in exporter.entities() if name not in done]


def export_entity(export_id: Any, name: str) -> int:
    from . import exporter

    job = ExportJob.objects.get(pk=export_id)
    if name in (job.progress or {}):
        return int(job.progress[name])
    count, keys = exporter.export_entity(job, name)
    with transaction.atomic():
        job = ExportJob.objects.select_for_update().get(pk=export_id)
        job.progress = {**job.progress, name: count}
        job.parts = [*job.parts, *[k for k in keys if k not in job.parts]]
        job.save(update_fields=["progress", "parts", "updated_at"])
    return count


def export_archive(export_id: Any, heartbeat: Any = None) -> str:
    """Zip the parts into the archive and offer it for download (emailed link)."""
    from tutortrack.comms.services import notify

    from . import exporter
    from .notifications import EXPORT_READY

    job = ExportJob.objects.get(pk=export_id)
    if job.status == ExportJob.Status.READY and job.expires_at is not None:
        return job.expires_at.isoformat()
    handle, size = exporter.build_archive(job, heartbeat)
    try:
        stored = files.save_stream(
            job, f"tutortrack-export-{now():%Y-%m-%d}.zip", "application/zip", handle, size
        )
    finally:
        handle.close()
    for key in job.parts:
        try:
            files.delete_key(key)
        except Exception:
            logger.warning("export.part_cleanup_failed", export=str(job.pk))
    days = int(get_setting("migration.export_link_days") or 7)
    with transaction.atomic():
        job = ExportJob.objects.select_for_update().get(pk=export_id)
        job.file = stored
        job.size_bytes = size
        job.status = ExportJob.Status.READY
        job.ready_at = now()
        job.expires_at = job.ready_at + timedelta(days=days)
        job.parts = []
        job.save()
        audit.record(job, "ready", {"size": [None, size]})
        publish(
            events.ExportReady(
                subject_id=job.pk, size_bytes=size, expires_at=job.expires_at.isoformat()
            )
        )
    notify(EXPORT_READY, job, key=f"export:{job.pk}")
    return job.expires_at.isoformat()


def expire_export(export_id: Any, *, status: str = "expired", error: str = "") -> None:
    """The link expired (or the export was cancelled or failed): delete the archive."""
    with transaction.atomic():
        job = ExportJob.objects.select_for_update().get(pk=export_id)
        if job.status in (
            ExportJob.Status.EXPIRED,
            ExportJob.Status.CANCELLED,
            ExportJob.Status.FAILED,
        ):
            return
        stored = job.file
        keys = list(job.parts)
        job.status = status
        job.error = error[:2000]
        job.parts = []
        job.save(update_fields=["status", "error", "parts", "updated_at"])
        if stored is not None:
            stored.status = stored.Status.REJECTED  # gone: never downloadable again
            stored.save(update_fields=["status", "updated_at"])
            keys.append(stored.storage_key)
        audit.record(job, status, {"status": [None, status]})
        if status == ExportJob.Status.EXPIRED:
            publish(events.ExportExpired(subject_id=job.pk))
    for key in keys:
        try:
            files.delete_key(key)
        except Exception:
            logger.warning("export.cleanup_failed", export=str(export_id))


@transaction.atomic
def cancel_export(job: ExportJob) -> ExportJob:
    job = ExportJob.objects.select_for_update().get(pk=job.pk)
    if job.status not in (
        ExportJob.Status.REQUESTED,
        ExportJob.Status.RUNNING,
        ExportJob.Status.READY,
    ):
        raise Conflict(_("This export has already ended."))
    audit.record(job, "cancel_requested", {"status": [None, job.status]})
    signal(job.workflow_id, "cancel")
    return job


def download_export(job: ExportJob, *, user: Any, password: str) -> str:
    """A short-lived link to the archive, after the owner confirms their password."""
    from tutortrack.tenancy.lifecycle import ReauthenticationFailed

    if not has_perm(user, "migration.export.full"):
        raise PermissionDenied(_("Only the owner can download the export."))
    if not password or not user.check_password(password):
        raise ReauthenticationFailed()
    if (
        job.status != ExportJob.Status.READY
        or job.file is None
        or (job.expires_at is not None and job.expires_at <= now())
    ):
        raise Conflict(_("This export is no longer available."))
    with transaction.atomic():
        locked = ExportJob.objects.select_for_update().get(pk=job.pk)
        locked.download_count += 1
        locked.downloaded_at = now()
        locked.save(update_fields=["download_count", "downloaded_at", "updated_at"])
        audit.record_read(locked, "download")
        publish(events.ExportDownloaded(subject_id=locked.pk, count=locked.download_count))
    return files.presigned_get(job.file)
