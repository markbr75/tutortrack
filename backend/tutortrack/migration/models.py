"""Imports, competitor migration and full data export (E28).

* ``ImportBatch``/``ImportRow``: one uploaded (or pulled) file for one entity, its column
  mapping and each row's outcome. Rows are applied idempotently (``batch``+``row_number``).
* ``SavedImportMapping``: reusable column mappings.
* ``ExternalRef``: the source system's id of a record we created or matched, used to
  upsert by external id and to resolve references between files (a lesson's client).
* ``MigrationProject``: the cutover assistant for one source (TutorCruncher, TutorBird,
  Teachworks or spreadsheets).
* ``ExportJob``: a full tenant export (ZIP), its download link and expiry.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.models import TenantModel


class Source(models.TextChoices):
    CSV = "csv", _("CSV file")
    XLSX = "xlsx", _("Excel file")
    GOOGLE_SHEETS = "google_sheets", _("Google Sheets")
    TUTORCRUNCHER = "tutorcruncher", _("TutorCruncher")
    TUTORBIRD = "tutorbird", _("TutorBird")
    TEACHWORKS = "teachworks", _("Teachworks")


class ImportBatch(TenantModel):
    class Status(models.TextChoices):
        MAPPING = "mapping", _("Mapping columns")
        VALIDATING = "validating", _("Validating")
        VALIDATED = "validated", _("Ready to import")
        IMPORTING = "importing", _("Importing")
        COMPLETED = "completed", _("Imported")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")
        ROLLING_BACK = "rolling_back", _("Rolling back")
        ROLLED_BACK = "rolled_back", _("Rolled back")
        FINALISED = "finalised", _("Finalised")

    entity = models.CharField(max_length=30)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.CSV)
    preset = models.CharField(max_length=40, blank=True, default="")  # e.g. tutorbird
    file = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    filename = models.CharField(max_length=255, blank=True, default="")
    sheet = models.CharField(max_length=100, blank=True, default="")
    headers = models.JSONField(default=list, blank=True)
    mapping = models.JSONField(default=dict, blank=True)  # {column: field key or ""}
    value_map = models.JSONField(default=dict, blank=True)  # {field: {source value: ours}}
    options = models.JSONField(default=dict, blank=True)  # upsert_key, date_format, ...
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.MAPPING)
    stats = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    error_file = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    project = models.ForeignKey(
        "MigrationProject",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="batches",
    )
    project_step = models.CharField(max_length=30, blank=True, default="")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    workflow_id = models.CharField(max_length=255, blank=True, default="")
    validated_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    rollback_until = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    finalised_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organisation", "status"], name="import_batch_status")]

    def __str__(self) -> str:
        return f"{self.entity} import {self.filename or self.source}"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(requested_by=user)

    @property
    def can_rollback(self) -> bool:
        from tutortrack.core.time import now

        return (
            self.status == self.Status.COMPLETED
            and self.rollback_until is not None
            and self.rollback_until > now()
        )


class ImportRow(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Not checked")
        VALID = "valid", _("Valid")
        INVALID = "invalid", _("Invalid")
        CREATED = "created", _("Created")
        UPDATED = "updated", _("Updated")
        SKIPPED = "skipped", _("Skipped")
        FAILED = "failed", _("Failed")
        ROLLED_BACK = "rolled_back", _("Rolled back")
        KEPT = "kept", _("Kept (changed since import)")

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()  # 1-based data row (header excluded)
    raw = models.JSONField(default=dict, blank=True)  # {column: text}
    values = models.JSONField(default=dict, blank=True)  # mapped, normalised
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    action = models.CharField(max_length=10, blank=True, default="")  # create|update|skip
    errors = models.JSONField(default=list, blank=True)  # [{field, message}]
    warnings = models.JSONField(default=list, blank=True)
    target_type = models.CharField(max_length=40, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    created_refs = models.JSONField(default=list, blank=True)  # [{type, id}] in creation order
    previous = models.JSONField(default=dict, blank=True)  # values before an update
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["batch", "row_number"]
        constraints = [
            models.UniqueConstraint(fields=["batch", "row_number"], name="import_row_unique")
        ]
        indexes = [models.Index(fields=["batch", "status"], name="import_row_status")]

    def __str__(self) -> str:
        return f"row {self.row_number}"


class SavedImportMapping(TenantModel):
    name = models.CharField(max_length=120)
    entity = models.CharField(max_length=30)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.CSV)
    mapping = models.JSONField(default=dict, blank=True)
    value_map = models.JSONField(default=dict, blank=True)
    options = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["entity", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "entity", "name"], name="saved_import_mapping_unique"
            )
        ]

    def __str__(self) -> str:
        return self.name


class ExternalRef(TenantModel):
    """``(system, target_type, external_id)`` → our record. ``system`` is the source
    (``tutorcruncher``...) or ``file`` for ids in spreadsheets."""

    system = models.CharField(max_length=20)
    target_type = models.CharField(max_length=40)  # people.client, scheduling.lesson, ...
    external_id = models.CharField(max_length=120)
    target_id = models.CharField(max_length=64)
    batch = models.ForeignKey(
        ImportBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "system", "target_type", "external_id"],
                name="external_ref_unique",
            )
        ]
        indexes = [models.Index(fields=["target_type", "target_id"], name="external_ref_target")]

    def __str__(self) -> str:
        return f"{self.system}:{self.target_type}:{self.external_id}"


class MigrationProject(TenantModel):
    class Status(models.TextChoices):
        ACTIVE = "active", _("In progress")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")

    name = models.CharField(max_length=120)
    source = models.CharField(max_length=20, choices=Source.choices)
    # API credentials live on the integration framework's connection (encrypted there).
    connection = models.ForeignKey(
        "integrations.IntegrationConnection",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    cutover_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    current_step = models.CharField(max_length=30, blank=True, default="")
    steps = models.JSONField(default=dict, blank=True)  # {step: {status, at, note, batches}}
    source_totals = models.JSONField(default=dict, blank=True)
    reconciliation = models.JSONField(default=dict, blank=True)
    workflow_id = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class ExportJob(TenantModel):
    class Kind(models.TextChoices):
        FULL = "full", _("Full data export")

    class Status(models.TextChoices):
        REQUESTED = "requested", _("Requested")
        RUNNING = "running", _("Preparing")
        READY = "ready", _("Ready to download")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")
        EXPIRED = "expired", _("Expired")

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.FULL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    reason = models.CharField(max_length=200, blank=True, default="")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    progress = models.JSONField(default=dict, blank=True)  # {entity: rows}
    parts = models.JSONField(default=list, blank=True)  # storage keys of finished parts
    file = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    size_bytes = models.PositiveBigIntegerField(default=0)
    error = models.TextField(blank=True, default="")
    workflow_id = models.CharField(max_length=255, blank=True, default="")
    ready_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"export {self.created_at:%Y-%m-%d}"
