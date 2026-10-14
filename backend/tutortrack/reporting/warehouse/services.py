"""Warehouse export services (E26-T09): destinations, schedules and the export itself.

An export run (``WarehouseExportWorkflow``) begins by fixing ``until`` (now) and each
dataset's watermark (the ``until`` of the last successful run, or nothing for a full
refresh), exports every dataset's rows with ``since < updated_at <= until`` as one
gzipped CSV batch, and finishes by recording the manifest. Each dataset step is
idempotent: rows are keyed by ``id`` and ``updated_at``, and a retried step writes the
same file name, so a retry never duplicates data in the warehouse.

Enterprise only: ``warehouse_export`` plan feature (E04).
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit, entitlements
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now

from . import destinations
from .datasets import DATASETS, schema
from .models import WarehouseDestination, WarehouseExport

FEATURE = "warehouse_export"
SCHEDULE_PROCESS = "warehouse-export"
SECRET_FIELDS = {
    "s3": ("access_key_id", "secret_access_key"),
    "bigquery": ("client_email", "private_key"),
    "snowflake": ("private_key",),
    "platform": (),
}


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def _clean_datasets(keys: list[str]) -> list[str]:
    unknown = [k for k in keys if k not in DATASETS]
    if unknown:
        raise _invalid("datasets", _("Unknown datasets: %(keys)s") % {"keys": ", ".join(unknown)})
    return list(dict.fromkeys(keys))


@transaction.atomic
def save_destination(
    destination: WarehouseDestination | None,
    *,
    name: str,
    kind: str,
    config: dict[str, Any],
    credentials: dict[str, Any] | None = None,
    datasets: list[str] | None = None,
    enabled: bool = True,
    hour: int = 2,
    full_refresh_weekday: int = 6,
) -> WarehouseDestination:
    entitlements.require(FEATURE)
    if kind not in WarehouseDestination.Kind.values:
        raise _invalid("kind", _("Choose where to export to."))
    if not 0 <= hour <= 23:
        raise _invalid("hour", _("Choose an hour between 0 and 23."))
    if not -1 <= full_refresh_weekday <= 6:
        raise _invalid("full_refresh_weekday", _("Choose a weekday or never."))
    creating = destination is None
    destination = destination or WarehouseDestination(kind=kind)
    if not creating and destination.kind != kind:
        raise _invalid("kind", _("Create a new destination to change where it exports to."))
    with audit.track(destination, action="create" if creating else "update"):
        destination.name = name.strip()[:100] or str(WarehouseDestination.Kind(kind).label)
        destination.kind = kind
        destination.config = {k: str(v)[:300] for k, v in (config or {}).items()}
        if credentials:
            missing = [f for f in SECRET_FIELDS[kind] if not credentials.get(f)]
            if missing:
                raise _invalid("credentials", _("Missing: %(f)s") % {"f": ", ".join(missing)})
            destination.credentials = json.dumps(
                {k: str(credentials[k]) for k in SECRET_FIELDS[kind]}
            )
        elif creating and SECRET_FIELDS[kind]:
            raise _invalid("credentials", _("Enter the credentials."))
        destination.datasets = _clean_datasets(datasets or [])
        destination.enabled = enabled
        destination.hour = hour
        destination.full_refresh_weekday = full_refresh_weekday
        try:
            destinations.for_destination(destination)  # validates the configuration
        except destinations.DestinationError as exc:
            raise _invalid("config", str(exc)) from exc
        destination.save()
    if creating:
        audit.record_create(destination)
    from .events import WarehouseDestinationSaved

    publish(WarehouseDestinationSaved(subject_id=destination.pk, kind=destination.kind))
    return destination


@transaction.atomic
def delete_destination(destination: WarehouseDestination) -> None:
    from .events import WarehouseDestinationDeleted

    destination_id = destination.pk
    audit.record(destination, "delete")
    destination.delete()
    publish(WarehouseDestinationDeleted(subject_id=destination_id))


def check(destination: WarehouseDestination) -> None:
    try:
        destinations.for_destination(destination).check()
    except destinations.DestinationError as exc:
        raise _invalid("config", str(exc)) from exc


def sync_schedule(destination_id: Any) -> str | None:
    """Create, update or remove the destination's nightly Temporal Schedule."""
    from tutortrack.core.workflows.schedules import delete_schedule, ensure_schedule, schedule_id
    from tutortrack.reporting.periods import org_timezone

    from .processes import WarehouseExportInput, WarehouseExportWorkflow

    org_id = require_organisation_id()
    sid = schedule_id(SCHEDULE_PROCESS, org_id, destination_id)
    destination = WarehouseDestination.objects.filter(pk=destination_id).first()
    if destination is None or not destination.enabled:
        delete_schedule(org_id, sid)
        if destination is not None and destination.schedule_id:
            WarehouseDestination.objects.filter(pk=destination.pk).update(schedule_id="")
        return None
    sid = ensure_schedule(
        process=SCHEDULE_PROCESS,
        workflow=WarehouseExportWorkflow,
        input=WarehouseExportInput(
            organisation_id=str(org_id), destination_id=str(destination.pk), scheduled=True
        ),
        cron=[f"0 {destination.hour} * * *"],
        timezone=org_timezone(),
        parts=(destination.pk,),
    )
    WarehouseDestination.objects.filter(pk=destination.pk).update(schedule_id=sid)
    return sid


def run_now(destination: WarehouseDestination, *, user: Any, full: bool = False) -> str:
    """Start an export outside the schedule; returns the workflow id."""
    from tutortrack.core.workflows import start

    from .processes import WarehouseExportInput, WarehouseExportWorkflow, export_workflow_id

    entitlements.require(FEATURE)
    org_id = require_organisation_id()
    wid = export_workflow_id(org_id, destination.pk, now().strftime("%Y%m%dT%H%M%S%f"))
    start(
        WarehouseExportWorkflow,
        WarehouseExportInput(
            organisation_id=str(org_id),
            destination_id=str(destination.pk),
            full=full,
            requested_by=str(user.pk) if getattr(user, "pk", None) else "",
        ),
        id=wid,
        subject=("warehouse_destination", str(destination.pk)),
    )
    return wid


# --- the export -----------------------------------------------------------------------------------


def _keys(destination: WarehouseDestination) -> list[str]:
    return [k for k in (destination.datasets or list(DATASETS)) if k in DATASETS]


@transaction.atomic
def begin(
    destination_id: Any, run_key: str, *, full: bool, scheduled: bool, requested_by: str = ""
) -> dict[str, Any]:
    """Open (or, on a retry, reopen) the run; ``{"export": id, "datasets": [...]}`` or
    ``{"skipped": reason}``."""
    destination = WarehouseDestination.objects.filter(pk=destination_id).first()
    if destination is None:
        return {"skipped": "deleted"}
    if scheduled and not destination.enabled:
        return {"skipped": "disabled"}
    if not entitlements.has(FEATURE):
        return {"skipped": "not_entitled"}
    existing = WarehouseExport.objects.filter(run_key=run_key).first()
    if existing is not None:
        return {"export": str(existing.pk), "datasets": _keys(destination)}
    current = now()
    weekly_full = (
        scheduled
        and destination.full_refresh_weekday >= 0
        and current.weekday() == destination.full_refresh_weekday
    )
    full = full or weekly_full
    last = (
        WarehouseExport.objects.filter(destination=destination, status="succeeded")
        .order_by("-until")
        .first()
    )
    since = {} if full or last is None else {k: last.until.isoformat() for k in _keys(destination)}
    export = WarehouseExport.objects.create(
        destination=destination,
        run_key=run_key[:255],
        full=full or last is None,
        since=since,
        until=current,
        requested_by_id=requested_by or None,
    )
    return {"export": str(export.pk), "datasets": _keys(destination)}


def _value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def export_dataset(export_id: Any, dataset_key: str) -> dict[str, Any]:
    """Export one dataset's changed rows for the run (idempotent by file name)."""
    export = WarehouseExport.objects.select_related("destination").get(pk=export_id)
    dataset = DATASETS[dataset_key]
    done = next((m for m in export.manifest if m["dataset"] == dataset_key), None)
    if done is not None:
        return done
    qs = dataset.queryset().filter(updated_at__lte=export.until)
    since = export.since.get(dataset_key)
    if since:
        qs = qs.filter(updated_at__gt=datetime.fromisoformat(since))
    limit = int(settings.WAREHOUSE_EXPORT["MAX_ROWS"])
    lookups = [c.lookup for c in dataset.columns]
    raw_rows = list(qs.order_by("updated_at").values_list(*lookups)[:limit])
    rows = [
        {c.name: _value(v) for c, v in zip(dataset.columns, row, strict=True)} for row in raw_rows
    ]
    entry: dict[str, Any] = {
        "dataset": dataset_key,
        "rows": len(rows),
        "location": "",
        "truncated": len(rows) >= limit,
    }
    if rows:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=[c.name for c in dataset.columns])
        writer.writeheader()
        writer.writerows(rows)
        content = gzip.compress(buffer.getvalue().encode(), mtime=0)
        filename = f"{export.until:%Y%m%dT%H%M%S}-{export.pk.hex[:8]}.csv.gz"
        batch = destinations.Batch(dataset, filename, content, rows)
        entry["location"] = destinations.for_destination(export.destination).write(batch)
    with transaction.atomic():
        locked = WarehouseExport.objects.select_for_update().get(pk=export.pk)
        if not any(m["dataset"] == dataset_key for m in locked.manifest):
            locked.manifest = [*locked.manifest, entry]
            locked.row_count += entry["rows"]
            locked.save(update_fields=["manifest", "row_count", "updated_at"])
    return entry


@transaction.atomic
def finish(export_id: Any) -> str:
    export = (
        WarehouseExport.objects.select_for_update().select_related("destination").get(pk=export_id)
    )
    if export.status != WarehouseExport.Status.RUNNING:
        return export.status
    if export.destination.kind == "platform":
        manifest = json.dumps(
            {
                "until": export.until.isoformat(),
                "full": export.full,
                "files": export.manifest,
                "schemas": schema(_keys(export.destination)),
            },
            indent=2,
        ).encode()
        from tutortrack.core.storage.client import bucket, s3_client

        prefix = f"warehouse/{export.organisation_id}/{export.destination_id}"
        s3_client().put_object(
            Bucket=bucket(),
            Key=f"{prefix}/manifests/{export.until:%Y%m%dT%H%M%S}.json",
            Body=manifest,
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
    export.status = WarehouseExport.Status.SUCCEEDED
    export.finished_at = now()
    export.save(update_fields=["status", "finished_at", "updated_at"])
    WarehouseDestination.objects.filter(pk=export.destination_id).update(
        last_export_at=export.finished_at, last_status=export.status
    )
    audit.record(
        export,
        "export",
        {
            "rows": export.row_count,
            "full": export.full,
            "datasets": [m["dataset"] for m in export.manifest],
        },
    )
    from .events import WarehouseExportFinished

    publish(
        WarehouseExportFinished(subject_id=export.pk, status=export.status, rows=export.row_count)
    )
    return export.status


@transaction.atomic
def fail(export_id: Any, error: str) -> str:
    export = WarehouseExport.objects.select_for_update().get(pk=export_id)
    if export.status != WarehouseExport.Status.RUNNING:
        return export.status
    export.status = WarehouseExport.Status.FAILED
    export.error = error[:500]
    export.finished_at = now()
    export.save(update_fields=["status", "error", "finished_at", "updated_at"])
    WarehouseDestination.objects.filter(pk=export.destination_id).update(last_status=export.status)
    from .events import WarehouseExportFinished

    publish(WarehouseExportFinished(subject_id=export.pk, status=export.status, rows=0))
    return export.status


def download_url(export: WarehouseExport, dataset_key: str, *, user: Any) -> str:
    """A presigned link to one file of a platform-storage export (audited)."""
    from tutortrack.core.storage.client import bucket, presign_client

    if export.destination.kind != "platform":
        raise BusinessRuleViolation(_("Only TutorTrack-stored exports can be downloaded."))
    entry = next((m for m in export.manifest if m["dataset"] == dataset_key), None)
    if entry is None or not entry.get("location"):
        raise BusinessRuleViolation(_("Nothing was exported for that dataset."))
    key = str(entry["location"]).split(f"s3://{bucket()}/", 1)[-1]
    audit.record_read(export, reason=f"warehouse_download:{dataset_key}")
    url: str = presign_client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket(), "Key": key}, ExpiresIn=600
    )
    return url
