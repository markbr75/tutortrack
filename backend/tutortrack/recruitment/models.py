"""Recruitment, onboarding and compliance (E18)."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.models import TenantModel


class JobOpening(TenantModel):
    """A role tutors can apply for, with its application form (FR-18-1)."""

    title = models.CharField(max_length=150)
    slug = models.SlugField(max_length=80)
    description = models.TextField(blank=True, default="")
    subjects = models.JSONField(default=list, blank=True)
    location = models.CharField(max_length=150, blank=True, default="")
    branch = models.ForeignKey(
        "tenancy.Branch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    form = models.ForeignKey("leads.Form", on_delete=models.PROTECT, related_name="+")
    published = models.BooleanField(default=False)
    closes_on = models.DateField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "slug"], name="opening_slug_unique")
        ]

    def __str__(self) -> str:
        return self.title


class ApplicationStage(TenantModel):
    class Kind(models.TextChoices):
        OPEN = "open", _("Open")
        HIRED = "hired", _("Hired")
        REJECTED = "rejected", _("Rejected")

    name = models.CharField(max_length=60)
    order = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.OPEN)
    criteria = models.JSONField(default=list, blank=True)  # scorecard criteria
    reminder_days = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["order"]

    def __str__(self) -> str:
        return self.name


class TutorApplication(TenantModel):
    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        HIRED = "hired", _("Hired")
        REJECTED = "rejected", _("Rejected")
        TALENT_POOL = "talent_pool", _("Talent pool")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    opening = models.ForeignKey(
        JobOpening, null=True, blank=True, on_delete=models.SET_NULL, related_name="applications"
    )
    submission = models.ForeignKey(
        "leads.FormSubmission", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True, default="")
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True, default="")
    postcode = models.CharField(max_length=20, blank=True, default="")
    subjects = models.JSONField(default=list, blank=True)  # [{subject, level, proficiency}]
    qualifications = models.TextField(blank=True, default="")
    experience = models.TextField(blank=True, default="")
    right_to_work = models.CharField(max_length=200, blank=True, default="")
    video_url = models.URLField(blank=True, default="")
    cv = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    answers = models.JSONField(default=dict, blank=True)
    stage = models.ForeignKey(ApplicationStage, on_delete=models.PROTECT, related_name="+")
    stage_entered_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    decision_reason = models.CharField(max_length=500, blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    tutor = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self) -> str:
        return self.full_name


class Scorecard(TenantModel):
    class Recommendation(models.TextChoices):
        YES = "yes", _("Hire")
        MAYBE = "maybe", _("Not sure")
        NO = "no", _("Don't hire")

    application = models.ForeignKey(
        TutorApplication, on_delete=models.CASCADE, related_name="scorecards"
    )
    stage = models.ForeignKey(ApplicationStage, on_delete=models.PROTECT, related_name="+")
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    scores = models.JSONField(default=dict)
    recommendation = models.CharField(max_length=5, choices=Recommendation.choices)
    notes = models.TextField(blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.application_id}: {self.recommendation}"


class Interview(TenantModel):
    """Staff propose times; the applicant picks one from a secure link (FR-18-2)."""

    class Status(models.TextChoices):
        PROPOSED = "proposed", _("Waiting for the applicant")
        BOOKED = "booked", _("Booked")
        CANCELLED = "cancelled", _("Cancelled")

    application = models.ForeignKey(
        TutorApplication, on_delete=models.CASCADE, related_name="interviews"
    )
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    options = models.JSONField(default=list)  # ISO datetimes
    minutes = models.PositiveSmallIntegerField(default=30)
    meeting_url = models.URLField(blank=True, default="")
    start = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PROPOSED)
    token_hash = models.CharField(max_length=64, db_index=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Interview {self.application_id}"


class ReferenceRequest(TenantModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", _("Requested")
        RECEIVED = "received", _("Received")
        DECLINED = "declined", _("Declined")
        EXPIRED = "expired", _("No reply")

    application = models.ForeignKey(
        TutorApplication, on_delete=models.CASCADE, related_name="references"
    )
    referee_name = models.CharField(max_length=150)
    referee_email = models.EmailField()
    relationship = models.CharField(max_length=150, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    token_hash = models.CharField(max_length=64, db_index=True)
    responses = models.JSONField(default=dict, blank=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    concerns = models.BooleanField(default=False)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.referee_name


class ChecklistTemplate(TenantModel):
    """Onboarding steps (FR-18-5). ``items`` = ``[{"key", "label", "kind", "mandatory",
    "link", "requirement"}]``; kinds: agreement, self_billing, document, training,
    availability, payout, profile, custom."""

    name = models.CharField(max_length=100)
    employment_type = models.CharField(max_length=15, blank=True, default="")
    items = models.JSONField(default=list)
    is_default = models.BooleanField(default=False)

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ChecklistInstance(TenantModel):
    tutor = models.OneToOneField(
        "people.TutorProfile", on_delete=models.CASCADE, related_name="onboarding"
    )
    template = models.ForeignKey(ChecklistTemplate, on_delete=models.PROTECT, related_name="+")
    items = models.JSONField(default=list)  # copy of the template items
    done = models.JSONField(default=dict)  # key -> {"at", "by"}
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Onboarding for {self.tutor_id}"


class RequirementType(TenantModel):
    """A compliance requirement (FR-18-6), e.g. Enhanced DBS. ``applies_to`` narrows it:
    ``{"employment_types": [...], "in_person_only": bool}``."""

    key = models.SlugField(max_length=50)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    has_number = models.BooleanField(default=False)
    has_expiry = models.BooleanField(default=False)
    renewal_months = models.PositiveSmallIntegerField(null=True, blank=True)
    mandatory = models.BooleanField(default=True)
    blocking = models.BooleanField(default=True)
    applies_to = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "key"], name="requirement_key_unique")
        ]

    def __str__(self) -> str:
        return self.name


class ComplianceRecord(TenantModel):
    class Status(models.TextChoices):
        MISSING = "missing", _("Missing")
        SUBMITTED = "submitted", _("Waiting for verification")
        VERIFIED = "verified", _("Verified")
        REJECTED = "rejected", _("Rejected")
        EXPIRED = "expired", _("Expired")

    tutor = models.ForeignKey(
        "people.TutorProfile", on_delete=models.CASCADE, related_name="compliance_records"
    )
    requirement = models.ForeignKey(RequirementType, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.MISSING)
    number = EncryptedField(blank=True, default="")
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    files = models.ManyToManyField("core.StoredFile", blank=True, related_name="+")
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    audit_sensitive_fields: ClassVar[frozenset[str]] = frozenset({"number"})

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["tutor", "requirement"], name="compliance_one_per_type")
        ]

    def __str__(self) -> str:
        return f"{self.tutor_id}: {self.requirement_id} ({self.status})"


class TutorComplianceState(TenantModel):
    """Whether compliance (rather than a person) restricted the tutor, and why."""

    tutor = models.OneToOneField(
        "people.TutorProfile", on_delete=models.CASCADE, related_name="compliance_state"
    )
    restricted_by_compliance = models.BooleanField(default=False)
    problems = models.JSONField(default=list, blank=True)  # requirement keys
    checked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Compliance for {self.tutor_id}"
