"""Warehouse export persistence (E26-T09). Imported by ``reporting.models``."""

from __future__ import annotations

from typing import ClassVar

from django.db import models
from django.utils.translation import gettext_lazy as _

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.models import TenantModel


class WarehouseDestination(TenantModel):
    """Where the organisation's data goes. ``credentials`` (an access key, a service account
    or a private key, as JSON) are encrypted and never returned by the API."""

    class Kind(models.TextChoices):
        PLATFORM = "platform", _("TutorTrack storage (download the files)")
        S3 = "s3", _("Amazon S3 (your bucket)")
        BIGQUERY = "bigquery", _("Google BigQuery")
        SNOWFLAKE = "snowflake", _("Snowflake")

    class Format(models.TextChoices):
        CSV = "csv", _("CSV (gzip)")

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    file_format = models.CharField(max_length=10, choices=Format.choices, default=Format.CSV)
    config = models.JSONField(default=dict, blank=True)  # bucket, prefix, project, account...
    credentials = EncryptedField(blank=True, default="")
    datasets = models.JSONField(default=list, blank=True)  # [] = every dataset
    enabled = models.BooleanField(default=True)
    hour = models.PositiveSmallIntegerField(default=2)  # local time of the nightly run
    full_refresh_weekday = models.SmallIntegerField(default=6)  # 0 = Monday; -1 = never
    schedule_id = models.CharField(max_length=255, blank=True, default="")
    last_export_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=10, blank=True, default="")

    audit_sensitive_fields: ClassVar[frozenset[str]] = frozenset({"credentials"})

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class WarehouseExport(TenantModel):
    """One export run: what was sent, from which watermarks, and how it went."""

    class Status(models.TextChoices):
        RUNNING = "running", _("Running")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        SKIPPED = "skipped", _("Skipped")

    destination = models.ForeignKey(
        WarehouseDestination, on_delete=models.CASCADE, related_name="exports"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    run_key = models.CharField(max_length=255)  # the workflow id: retries reuse the run
    full = models.BooleanField(default=False)
    since = models.JSONField(default=dict, blank=True)  # {dataset: ISO watermark}
    until = models.DateTimeField()
    manifest = models.JSONField(default=list, blank=True)  # [{dataset, rows, location}]
    row_count = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=500, blank=True, default="")
    finished_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(
        "identity.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "run_key"], name="warehouse_run_once")
        ]

    def __str__(self) -> str:
        return f"{self.destination_id} {self.status}"
