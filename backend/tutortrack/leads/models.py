"""Leads (E17): forms and submissions, pipelines and stages, enquiries with their stage
history, assignment rules and the waitlist."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.fields import CurrencyField, MoneyField
from tutortrack.core.models import BranchScopedModel, TenantModel


class Form(TenantModel):
    """A public form (FR-17-1, FR-17-7). ``schema`` = ``{"steps": [{"title", "fields":
    [{"key", "label", "type", "required", "options", "maps_to", "show_if"}]}]}``."""

    class Type(models.TextChoices):
        ENQUIRY = "enquiry", _("Enquiry")
        REGISTRATION = "registration", _("Registration")
        CUSTOM = "custom", _("Other")

    type = models.CharField(max_length=15, choices=Type.choices, default=Type.ENQUIRY)
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=80)
    schema = models.JSONField(default=dict)
    settings = models.JSONField(default=dict, blank=True)
    published = models.BooleanField(default=False)
    branch = models.ForeignKey(
        "tenancy.Branch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "slug"], name="form_slug_unique")
        ]

    def __str__(self) -> str:
        return self.name


class FormSubmission(TenantModel):
    form = models.ForeignKey(
        Form, null=True, blank=True, on_delete=models.SET_NULL, related_name="submissions"
    )
    data = models.JSONField(default=dict)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    utm = models.JSONField(default=dict, blank=True)
    created_records = models.JSONField(default=dict, blank=True)
    spam = models.BooleanField(default=False)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Submission {self.pk}"


class Pipeline(TenantModel):
    name = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["-is_default", "name"]

    def __str__(self) -> str:
        return self.name


class PipelineStage(TenantModel):
    class Kind(models.TextChoices):
        OPEN = "open", _("Open")
        WON = "won", _("Won")
        LOST = "lost", _("Lost")

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE, related_name="stages")
    name = models.CharField(max_length=60)
    order = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=5, choices=Kind.choices, default=Kind.OPEN)
    probability = models.PositiveSmallIntegerField(default=0)
    sla_hours = models.PositiveIntegerField(null=True, blank=True)
    colour = models.CharField(max_length=7, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["pipeline", "order"]

    def __str__(self) -> str:
        return self.name


class Enquiry(BranchScopedModel):
    """A lead being worked to won or lost (FR-17-2)."""

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        WON = "won", _("Won")
        LOST = "lost", _("Lost")

    class Source(models.TextChoices):
        FORM = "form", _("Website form")
        API = "api", _("API")
        EMAIL = "email", _("Email")
        PHONE = "phone", _("Phone")
        MANUAL = "manual", _("Added by staff")
        IMPORT = "import", _("Import")
        REFERRAL = "referral", _("Referral")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("High")

    class TrialOutcome(models.TextChoices):
        CONTINUING = "continuing", _("Continuing")
        NOT_CONTINUING = "not_continuing", _("Not continuing")
        UNDECIDED = "undecided", _("Undecided")

    title = models.CharField(max_length=200)
    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="+")
    contact = models.ForeignKey(
        "people.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    students = models.ManyToManyField("people.Student", blank=True, related_name="+")
    pipeline = models.ForeignKey(Pipeline, on_delete=models.PROTECT, related_name="enquiries")
    stage = models.ForeignKey(PipelineStage, on_delete=models.PROTECT, related_name="enquiries")
    stage_entered_at = models.DateTimeField()
    status = models.CharField(max_length=5, choices=Status.choices, default=Status.OPEN)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    priority = models.CharField(max_length=6, choices=Priority.choices, default=Priority.NORMAL)
    subjects = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True, default="")
    currency = CurrencyField(blank=True, default="")
    value_estimate = MoneyField(null=True, blank=True)
    expected_start = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    source_detail = models.CharField(max_length=200, blank=True, default="")
    utm = models.JSONField(default=dict, blank=True)
    submission = models.ForeignKey(
        FormSubmission, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    first_response_at = models.DateTimeField(null=True, blank=True)
    sla_breached_at = models.DateTimeField(null=True, blank=True)
    lost_reason = models.CharField(max_length=60, blank=True, default="")
    lost_note = models.CharField(max_length=500, blank=True, default="")
    won_at = models.DateTimeField(null=True, blank=True)
    lost_at = models.DateTimeField(null=True, blank=True)
    trial_lesson = models.ForeignKey(
        "scheduling.Lesson", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    trial_outcome = models.CharField(
        max_length=15, choices=TrialOutcome.choices, blank=True, default=""
    )
    trial_feedback = models.TextField(blank=True, default="")
    converted_job_ids = models.JSONField(default=list, blank=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["organisation", "pipeline", "status"], name="enquiry_pipeline_status"
            )
        ]

    @classmethod
    def own_scope_q(cls, user: object) -> Q:
        return Q(owner=user)

    def __str__(self) -> str:
        return self.title


class EnquiryStageHistory(TenantModel):
    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name="history")
    from_stage = models.ForeignKey(
        PipelineStage, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    to_stage = models.ForeignKey(PipelineStage, on_delete=models.PROTECT, related_name="+")
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    seconds_in_previous = models.PositiveIntegerField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.enquiry_id} → {self.to_stage_id}"


class AssignmentRule(TenantModel):
    """Round-robin owners for new enquiries matching a branch and/or subject (FR-17-2)."""

    pipeline = models.ForeignKey(
        Pipeline, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    branch = models.ForeignKey(
        "tenancy.Branch", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    subject = models.CharField(max_length=100, blank=True, default="")
    owners = models.JSONField(default=list)  # user ids
    next_index = models.PositiveIntegerField(default=0)
    order = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["order", "created_at"]

    def __str__(self) -> str:
        return f"Rule {self.order}"


class WaitlistEntry(BranchScopedModel):
    """A student waiting for a place (FR-17-6)."""

    class Status(models.TextChoices):
        WAITING = "waiting", _("Waiting")
        OFFERED = "offered", _("Offered a place")
        ACCEPTED = "accepted", _("Accepted")
        DECLINED = "declined", _("Declined")
        EXPIRED = "expired", _("Offer expired")
        REMOVED = "removed", _("Removed")

    student = models.ForeignKey("people.Student", on_delete=models.CASCADE, related_name="+")
    subject = models.CharField(max_length=100, blank=True, default="")
    level = models.CharField(max_length=100, blank=True, default="")
    tutor = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    service = models.ForeignKey(
        "catalogue.Service", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WAITING)
    offer_details = models.CharField(max_length=500, blank=True, default="")
    offer_token_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    offered_at = models.DateTimeField(null=True, blank=True)
    offer_expires_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.student_id} waiting for {self.subject}"
