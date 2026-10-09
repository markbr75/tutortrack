"""Generic CRM capabilities shared by every record (E05 FR-05-5..10, 11, 12)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from tutortrack.core.models import TenantModel


class TargetMixin(models.Model):
    """Attached to any record: ``target_type`` is the model label (``people.client``)."""

    target_type = models.CharField(max_length=60)
    target_id = models.CharField(max_length=64)

    class Meta:
        abstract = True


class CustomFieldDefinition(TenantModel):
    class Type(models.TextChoices):
        TEXT = "text", _("Text")
        LONG_TEXT = "long_text", _("Long text")
        NUMBER = "number", _("Number")
        DECIMAL = "decimal", _("Decimal")
        CURRENCY = "currency", _("Money")
        DATE = "date", _("Date")
        DATETIME = "datetime", _("Date and time")
        BOOLEAN = "boolean", _("Yes/no")
        SELECT = "select", _("Single choice")
        MULTI_SELECT = "multi_select", _("Multiple choice")
        EMAIL = "email", _("Email")
        PHONE = "phone", _("Phone")
        URL = "url", _("URL")
        FILE = "file", _("File")
        USER = "user", _("Staff member")
        ADDRESS = "address", _("Address")

    class Visibility(models.TextChoices):
        STAFF = "staff", _("Staff")
        TUTOR = "tutor", _("Staff and tutors")
        CLIENT_PORTAL = "client_portal", _("Also in the client portal")
        PUBLIC = "public", _("Public forms")

    class EditableBy(models.TextChoices):
        STAFF = "staff", _("Staff")
        TUTOR = "tutor", _("Staff and tutors")
        CLIENT = "client", _("Staff, tutors and clients")

    entity_type = models.CharField(max_length=60)  # people.client, people.student, ...
    key = models.SlugField(max_length=60)
    label = models.CharField(max_length=200)
    type = models.CharField(max_length=15, choices=Type.choices)
    required = models.BooleanField(default=False)
    options = models.JSONField(default=list, blank=True)  # for select types
    help_text = models.CharField(max_length=300, blank=True, default="")
    visibility = models.CharField(
        max_length=15, choices=Visibility.choices, default=Visibility.STAFF
    )
    editable_by = models.CharField(
        max_length=10, choices=EditableBy.choices, default=EditableBy.STAFF
    )
    group = models.CharField(max_length=100, blank=True, default="")
    order = models.PositiveIntegerField(default=0)
    validation_regex = models.CharField(max_length=300, blank=True, default="")
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["entity_type", "group", "order", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "entity_type", "key"], name="custom_field_key_unique"
            )
        ]

    def __str__(self) -> str:
        return self.label


class Tag(TenantModel):
    name = models.CharField(max_length=60)
    colour = models.CharField(max_length=7, default="#64748b")
    entity_types = models.JSONField(default=list, blank=True)  # [] = any

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "name"], name="tag_name_unique")
        ]

    def __str__(self) -> str:
        return self.name


class TaggedItem(TenantModel, TargetMixin):
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="items")

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["tag", "target_type", "target_id"], name="tagged_item_unique"
            )
        ]
        indexes = [
            models.Index(
                fields=["organisation", "target_type", "target_id"], name="tagged_target_idx"
            )
        ]

    def __str__(self) -> str:
        return f"{self.tag_id} on {self.target_type}:{self.target_id}"


class Note(TenantModel, TargetMixin):
    class Visibility(models.TextChoices):
        STAFF = "staff_only", _("Staff only")
        TUTORS = "staff_and_tutors", _("Staff and tutors")
        CLIENT = "shared_with_client", _("Shared with the client")

    body = models.TextField()  # sanitised HTML
    pinned = models.BooleanField(default=False)
    visibility = models.CharField(
        max_length=20, choices=Visibility.choices, default=Visibility.STAFF
    )
    mentions = models.JSONField(default=list, blank=True)  # user ids
    attachments = models.ManyToManyField("core.StoredFile", blank=True, related_name="+")

    class Meta(TenantModel.Meta):
        ordering = ["-pinned", "-created_at"]
        indexes = [
            models.Index(
                fields=["organisation", "target_type", "target_id"], name="note_target_idx"
            )
        ]

    def __str__(self) -> str:
        return f"Note on {self.target_type}:{self.target_id}"


class Task(TenantModel):
    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        DONE = "done", _("Done")
        CANCELLED = "cancelled", _("Cancelled")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("High")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )  # fmt: skip
    priority = models.CharField(max_length=6, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    completed_at = models.DateTimeField(null=True, blank=True)
    target_type = models.CharField(max_length=60, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    recurrence = models.CharField(max_length=200, blank=True, default="")  # RRULE (E14 creates)
    remind_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["status", "due_at", "-created_at"]

    def __str__(self) -> str:
        return self.title

    @classmethod
    def own_scope_q(cls, user: object) -> models.Q:
        return models.Q(assignee_id=getattr(user, "pk", None))


class Document(TenantModel, TargetMixin):
    class Category(models.TextChoices):
        CONTRACT = "contract", _("Contract")
        CONSENT = "consent_form", _("Consent form")
        REPORT = "report", _("Report")
        ID = "id", _("Identity document")
        OTHER = "other", _("Other")

    file = models.ForeignKey("core.StoredFile", on_delete=models.PROTECT, related_name="+")
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=15, choices=Category.choices, default=Category.OTHER)
    visibility = models.CharField(
        max_length=20, choices=Note.Visibility.choices, default=Note.Visibility.STAFF
    )
    expires_on = models.DateField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["organisation", "target_type", "target_id"], name="document_target_idx"
            )
        ]

    def __str__(self) -> str:
        return self.title


class SavedView(TenantModel):
    """A named set of list filters and columns (FR-05-11), private or shared."""

    entity_type = models.CharField(max_length=60)
    name = models.CharField(max_length=100)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    shared = models.BooleanField(default=False)
    filters = models.JSONField(default=dict, blank=True)
    columns = models.JSONField(default=list, blank=True)
    ordering = models.CharField(max_length=60, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class BulkJob(TenantModel):
    """A bulk action running in the background (FR-05-12), with progress and a report."""

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")

    entity_type = models.CharField(max_length=60)
    action = models.CharField(max_length=30)
    params = models.JSONField(default=dict, blank=True)
    target_ids = models.JSONField(default=list)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    total = models.PositiveIntegerField(default=0)
    processed = models.PositiveIntegerField(default=0)
    succeeded = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=dict, blank=True)  # {id: message}
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action} {self.entity_type} ({self.status})"
