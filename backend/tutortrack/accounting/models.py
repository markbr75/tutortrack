"""Accounting integrations (E23 §3).

* ``AccountingConnection``: the accounting side of an organisation-level
  ``IntegrationConnection`` (Xero, QuickBooks Online): sync options, the provider's
  chart of accounts/tax codes/tracking categories as last fetched, lock date, backfill
  progress. Tokens stay on the framework's connection.
* ``AccountMapping``/``TaxMapping``/``TrackingMapping``: what our records post to, per
  mapping set (a provider key, or ``export`` for GL file exports).
* ``ExternalRecordLink``: one TutorTrack record (invoice, payment, ...) as pushed to one
  connection: external id, content hash, ``pending|synced|error|skipped``, last error.
* ``SyncLogEntry``: the attempt history behind the sync dashboard.

The sync queue itself is Temporal (``AccountingSyncWorkflow``), so there is no
``AccountingSyncJob`` table (E23-TW1).
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.models import TenantModel


class AccountingConnection(TenantModel):
    class Mode(models.TextChoices):
        INDIVIDUAL = "individual", _("Each invoice, payment and credit note")
        SUMMARY = "summary", _("A daily summary journal")

    class LockBehaviour(models.TextChoices):
        POST_TO_OPEN = "post_to_open", _("Post on the first open date, with a note")
        HOLD = "hold", _("Hold it until the period is unlocked")

    connection = models.OneToOneField(
        "integrations.IntegrationConnection", on_delete=models.CASCADE, related_name="+"
    )
    provider = models.CharField(max_length=30)
    enabled = models.BooleanField(default=False)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.INDIVIDUAL)
    start_date = models.DateField(null=True, blank=True)  # nothing earlier syncs
    sync_bills = models.BooleanField(default=True)
    attach_pdf = models.BooleanField(default=True)
    lock_behaviour = models.CharField(
        max_length=12, choices=LockBehaviour.choices, default=LockBehaviour.POST_TO_OPEN
    )
    company_name = models.CharField(max_length=255, blank=True, default="")
    base_currency = models.CharField(max_length=3, blank=True, default="")
    lock_date = models.DateField(null=True, blank=True)
    chart = models.JSONField(default=dict, blank=True)  # accounts, tax_codes, tracking
    chart_fetched_at = models.DateTimeField(null=True, blank=True)
    enabled_at = models.DateTimeField(null=True, blank=True)
    schedule_id = models.CharField(max_length=255, blank=True, default="")
    backfill = models.JSONField(default=dict, blank=True)  # status, since, counts, checkpoint
    last_digest_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.provider} ({self.company_name})"


class AccountMapping(TenantModel):
    """``kind`` is what the account is for (revenue, clearing, bank, fees, tutor_cost,
    expense, rounding, bad_debt, receivable, payable, sales_tax); ``key`` narrows it
    (``default``, ``service_category:<id>``, ``product_category:<category>``,
    ``method:<method>``, ``provider:stripe``, ``expense_category:<id>``)."""

    provider = models.CharField(max_length=30)  # mapping set: xero | quickbooks | export
    kind = models.CharField(max_length=20)
    key = models.CharField(max_length=80, default="default")
    external_id = models.CharField(max_length=100)
    code = models.CharField(max_length=40, blank=True, default="")
    name = models.CharField(max_length=200, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["provider", "kind", "key"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "provider", "kind", "key"], name="account_mapping_unique"
            )
        ]


class TaxMapping(TenantModel):
    """Our tax rate (empty = no tax) ↔ the provider's tax code."""

    provider = models.CharField(max_length=30)
    tax_rate = models.ForeignKey(
        "catalogue.TaxRate", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    external_id = models.CharField(max_length=100)
    name = models.CharField(max_length=200, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["provider", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "provider", "tax_rate"], name="tax_mapping_unique"
            ),
            models.UniqueConstraint(
                fields=["organisation", "provider"],
                condition=Q(tax_rate__isnull=True),
                name="tax_mapping_no_tax_unique",
            ),
        ]


class TrackingMapping(TenantModel):
    """A branch ↔ a Xero tracking option (or a QuickBooks class/location)."""

    provider = models.CharField(max_length=30)
    branch = models.ForeignKey("tenancy.Branch", on_delete=models.CASCADE, related_name="+")
    category_id = models.CharField(max_length=100)
    option_id = models.CharField(max_length=100)
    name = models.CharField(max_length=200, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["provider", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "provider", "branch"], name="tracking_mapping_unique"
            )
        ]


class ExternalRecordLink(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting to sync")
        SYNCED = "synced", _("Synced")
        ERROR = "error", _("Error")
        SKIPPED = "skipped", _("Skipped")

    connection = models.ForeignKey(
        AccountingConnection, on_delete=models.CASCADE, related_name="links"
    )
    provider = models.CharField(max_length=30)
    object_type = models.CharField(max_length=20)
    object_id = models.CharField(max_length=64)
    label = models.CharField(max_length=200, blank=True, default="")  # "INV-000012", a name
    external_id = models.CharField(max_length=100, blank=True, default="")
    external_number = models.CharField(max_length=100, blank=True, default="")
    synced_hash = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=500, blank=True, default="")
    error_code = models.CharField(max_length=40, blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    posted_date = models.DateField(null=True, blank=True)
    workflow_id = models.CharField(max_length=255, blank=True, default="")
    meta = models.JSONField(default=dict, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "object_type", "object_id"], name="external_record_unique"
            )
        ]
        indexes = [
            models.Index(fields=["organisation", "status"], name="acct_link_status_idx"),
            models.Index(fields=["object_type", "object_id"], name="acct_link_object_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.object_type}:{self.object_id} → {self.external_id or '-'}"


class SyncLogEntry(TenantModel):
    class Outcome(models.TextChoices):
        CREATED = "created", _("Created")
        UPDATED = "updated", _("Updated")
        UNCHANGED = "unchanged", _("Already up to date")
        VOIDED = "voided", _("Voided")
        ERROR = "error", _("Error")
        RETRYING = "retrying", _("Will retry")
        SKIPPED = "skipped", _("Skipped")

    link = models.ForeignKey(ExternalRecordLink, on_delete=models.CASCADE, related_name="log")
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    message = models.CharField(max_length=500, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        verbose_name_plural = "sync log entries"
