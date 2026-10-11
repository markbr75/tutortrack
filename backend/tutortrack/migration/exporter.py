"""The full tenant export (FR-28-7): one CSV and one JSON file per entity, a
``relationships.json`` describing how they link, documents and files, and invoice PDFs, in
one ZIP. Built entity by entity by ``TenantExportWorkflow`` (parts are checkpointed in object
storage), zipped, and offered for download for a limited time.

Secrets never leave: integration tokens, API keys, password hashes and webhook secrets are
not exported (those models are not listed, and secret-named fields are dropped).
The E29 subject access/portability export is meant to reuse ``rows_for`` with a filter
on one person; it isn't built here.
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from django.apps import apps
from django.db import models

from . import files

# (file name, app label.Model). Order: parents before children.
ENTITIES: list[tuple[str, str]] = [
    ("branches", "tenancy.Branch"),
    ("addresses", "people.Address"),
    ("clients", "people.Client"),
    ("contacts", "people.Contact"),
    ("students", "people.Student"),
    ("tutors", "people.TutorProfile"),
    ("tutor_subjects", "people.TutorSubject"),
    ("tutor_qualifications", "people.TutorQualification"),
    ("categories", "catalogue.Category"),
    ("subjects", "catalogue.Subject"),
    ("levels", "catalogue.Level"),
    ("tax_rates", "catalogue.TaxRate"),
    ("services", "catalogue.Service"),
    ("service_prices", "catalogue.ServicePrice"),
    ("locations", "catalogue.Location"),
    ("rooms", "catalogue.Room"),
    ("products", "catalogue.Product"),
    ("package_templates", "catalogue.PackageTemplate"),
    ("jobs", "jobs.Job"),
    ("job_students", "jobs.JobStudent"),
    ("job_tutors", "jobs.JobTutor"),
    ("lesson_series", "scheduling.LessonSeries"),
    ("lessons", "scheduling.Lesson"),
    ("lesson_tutors", "scheduling.LessonTutor"),
    ("lesson_attendees", "scheduling.LessonAttendee"),
    ("calendar_events", "scheduling.CalendarEvent"),
    ("availability_templates", "scheduling.AvailabilityTemplate"),
    ("availability_windows", "scheduling.AvailabilityWindow"),
    ("availability_exceptions", "scheduling.AvailabilityException"),
    ("lesson_reports", "delivery.LessonReport"),
    ("makeup_credits", "delivery.MakeupCredit"),
    ("charges", "billing.Charge"),
    ("invoices", "billing.Invoice"),
    ("invoice_lines", "billing.InvoiceLine"),
    ("credit_notes", "billing.CreditNote"),
    ("credit_note_lines", "billing.CreditNoteLine"),
    ("payment_requests", "billing.PaymentRequest"),
    ("ledger_entries", "billing.ClientLedgerEntry"),
    ("payments", "payments.Payment"),
    ("payment_allocations", "payments.PaymentAllocation"),
    ("refunds", "payments.Refund"),
    ("pay_items", "payroll.PayItem"),
    ("pay_runs", "payroll.PayRun"),
    ("payouts", "payroll.Payout"),
    ("expenses", "payroll.Expense"),
    ("pipelines", "leads.Pipeline"),
    ("pipeline_stages", "leads.PipelineStage"),
    ("enquiries", "leads.Enquiry"),
    ("waitlist", "leads.WaitlistEntry"),
    ("tutor_applications", "recruitment.TutorApplication"),
    ("compliance_records", "recruitment.ComplianceRecord"),
    ("custom_fields", "crm.CustomFieldDefinition"),
    ("tags", "crm.Tag"),
    ("tagged_items", "crm.TaggedItem"),
    ("notes", "crm.Note"),
    ("tasks", "crm.Task"),
    ("documents", "crm.Document"),
    ("consents", "privacy.ConsentRecord"),
    ("files", "core.StoredFile"),
]
SECRET_WORDS = ("token", "secret", "password", "hash", "api_key", "storage_key", "pay_token")
MAX_FILE_BYTES = 2 * 1024**3  # documents and files included in the archive, in total
MAX_INVOICE_PDFS = 5000
logger = structlog.get_logger(__name__)


def model_for(label: str) -> type[models.Model] | None:
    try:
        return apps.get_model(label)
    except LookupError:
        return None


def entities() -> list[str]:
    return [name for name, label in ENTITIES if model_for(label) is not None]


def _fields(model: type[models.Model]) -> list[models.Field[Any, Any]]:
    out = []
    for field in model._meta.concrete_fields:
        if field.name == "organisation" or any(w in field.name for w in SECRET_WORDS):
            continue
        out.append(field)
    return out


def _column(field: models.Field[Any, Any]) -> str:
    return field.attname  # foreign keys as <name>_id


def _value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal | UUID):
        return str(value)
    return value


def _queryset(label: str) -> Any:
    model = model_for(label)
    if model is None:
        return None
    manager = model._default_manager
    qs = manager.all()
    if label == "core.StoredFile":
        qs = qs.filter(status="uploaded").exclude(
            owner_content_type__app_label="migration", owner_content_type__model="exportjob"
        )
    return qs.order_by("pk")


def rows_for(label: str) -> Iterator[dict[str, Any]]:
    model = model_for(label)
    qs = _queryset(label)
    if model is None or qs is None:
        return
    fields = _fields(model)
    for obj in qs.iterator(chunk_size=1000):
        yield {_column(f): _value(getattr(obj, f.attname)) for f in fields}


def _csv_text(value: Any) -> str:
    from .parsing import safe_cell

    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return safe_cell(value)


def export_entity(job: Any, name: str) -> tuple[int, list[str]]:
    """Write ``<name>.csv`` and ``<name>.json`` parts; returns (rows, part keys)."""
    label = dict(ENTITIES)[name]
    model = model_for(label)
    if model is None:
        return 0, []
    columns = [_column(f) for f in _fields(model)]
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(columns)
    records = []
    for record in rows_for(label):
        writer.writerow([_csv_text(record.get(c)) for c in columns])
        records.append(record)
    base = f"org/{job.organisation_id}/exports/{job.pk}/parts"
    csv_key, json_key = f"{base}/csv/{name}.csv", f"{base}/json/{name}.json"
    files.put_key(csv_key, ("﻿" + text.getvalue()).encode("utf-8"), "text/csv")
    files.put_key(
        json_key,
        json.dumps(records, ensure_ascii=False, default=str).encode("utf-8"),
        "application/json",
    )
    return len(records), [csv_key, json_key]


def relationships() -> dict[str, Any]:
    by_model = {label: name for name, label in ENTITIES}
    out: dict[str, Any] = {}
    for name, label in ENTITIES:
        model = model_for(label)
        if model is None:
            continue
        refs = {}
        for field in _fields(model):
            if isinstance(field, models.ForeignKey):
                target = f"{field.related_model._meta.app_label}.{field.related_model.__name__}"
                refs[_column(field)] = by_model.get(target, target)
        generic = {}
        if {"target_type", "target_id"} <= {f.name for f in _fields(model)}:
            generic["target_id"] = "target_type"
        if {"owner_content_type", "owner_object_id"} <= {f.name for f in _fields(model)}:
            generic["owner_object_id"] = "owner_content_type_id"
        out[name] = {
            "model": label,
            "columns": [_column(f) for f in _fields(model)],
            "primary_key": "id",
            "references": refs,
            "generic_references": generic,
        }
    return out


def build_archive(job: Any, heartbeat: Any = None) -> tuple[Any, int]:
    """Zip the parts, documents/files and invoice PDFs into a temporary file."""
    from tutortrack.core.models import StoredFile

    handle = tempfile.TemporaryFile()  # noqa: SIM115 - returned to the caller, closed there
    with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive:
        for key in job.parts:
            relative = key.split("/parts/", 1)[1]
            archive.writestr(relative, files.read_key(key))
        archive.writestr(
            "relationships.json", json.dumps(relationships(), indent=2, ensure_ascii=False)
        )
        archive.writestr(
            "README.txt",
            "TutorTrack data export\n\n"
            "csv/: one file per kind of record (UTF-8, first row = column names).\n"
            "json/: the same records as JSON.\n"
            "relationships.json: the columns of each file and which file each *_id points to.\n"
            "files/: uploaded documents and files (see csv/files.csv).\n"
            "invoices/: issued invoices as PDF.\n",
        )
        included = 0
        stored = StoredFile.objects.filter(status="uploaded", scan_status__in=["clean", "skipped"])
        stored = stored.exclude(owner_content_type__app_label="migration").order_by("created_at")
        for index, item in enumerate(stored.iterator(chunk_size=200)):
            if included + item.size_bytes > MAX_FILE_BYTES:
                break
            try:
                data = files.read_key(item.storage_key)
            except Exception:  # a missing object must not fail the export
                logger.warning("export.file_missing", file=str(item.pk))
                continue
            archive.writestr(f"files/{item.pk}-{_safe(item.filename)}", data)
            included += len(data)
            if heartbeat and index % 20 == 0:
                heartbeat(f"files:{index}")
        _invoice_pdfs(archive, heartbeat)
    size = handle.tell()
    return handle, size


def _safe(name: str) -> str:
    from tutortrack.core.storage.services import safe_filename

    return safe_filename(name)


def _invoice_pdfs(archive: zipfile.ZipFile, heartbeat: Any) -> None:
    from tutortrack.billing.models import Invoice
    from tutortrack.billing.pdf import invoice_pdf

    issued = Invoice.objects.exclude(status=Invoice.Status.DRAFT).exclude(number="")
    for index, invoice in enumerate(issued.order_by("issue_date")[:MAX_INVOICE_PDFS]):
        try:
            data = invoice_pdf(invoice)
        except Exception:  # a broken template must not fail the export
            logger.warning("export.invoice_pdf_failed", invoice=str(invoice.pk))
            continue
        archive.writestr(f"invoices/{_safe(invoice.number)}.pdf", data)
        if heartbeat and index % 20 == 0:
            heartbeat(f"invoices:{index}")
