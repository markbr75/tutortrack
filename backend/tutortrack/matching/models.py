"""Tutor matching, job offers, the internal job board and cover requests (E19)."""

from __future__ import annotations

from typing import Any

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.fields import CurrencyField, RateField
from tutortrack.core.models import TenantModel


def _own_tutor(user: Any, prefix: str = "") -> Q:
    return Q(**{f"{prefix}tutor__membership__user": user})


class MatchQuery(TenantModel):
    """One matching search: its criteria and how many tutors it found (analytics)."""

    job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    criteria = models.JSONField(default=dict, blank=True)
    include_restricted = models.BooleanField(default=False)
    result_count = models.PositiveIntegerField(default=0)
    top_score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]


class MatchResult(TenantModel):
    query = models.ForeignKey(MatchQuery, on_delete=models.CASCADE, related_name="results")
    tutor = models.ForeignKey("people.TutorProfile", on_delete=models.CASCADE, related_name="+")
    rank = models.PositiveSmallIntegerField()
    score = models.DecimalField(max_digits=5, decimal_places=1)
    breakdown = models.JSONField(default=dict, blank=True)
    restricted = models.BooleanField(default=False)

    class Meta(TenantModel.Meta):
        ordering = ["rank"]


class Shortlist(TenantModel):
    """A tutor shortlisted for a job (FR-19-2)."""

    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, related_name="shortlist")
    tutor = models.ForeignKey("people.TutorProfile", on_delete=models.CASCADE, related_name="+")
    score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    breakdown = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=300, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-score", "created_at"]
        constraints = [models.UniqueConstraint(fields=["job", "tutor"], name="shortlist_unique")]


class OfferBatch(TenantModel):
    """Offers of one job to several tutors, at once or one after another (FR-19-2).
    ``JobOfferCascadeWorkflow`` runs it."""

    class Mode(models.TextChoices):
        SIMULTANEOUS = "simultaneous", _("All at once")
        SEQUENTIAL = "sequential", _("One after another")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        AWAITING_CONFIRMATION = "awaiting_confirmation", _("Waiting for confirmation")
        FILLED = "filled", _("Filled")
        EXHAUSTED = "exhausted", _("No one accepted")
        CANCELLED = "cancelled", _("Cancelled")

    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, related_name="offer_batches")
    mode = models.CharField(max_length=12, choices=Mode.choices, default=Mode.SEQUENTIAL)
    status = models.CharField(max_length=21, choices=Status.choices, default=Status.OPEN)
    expiry_hours = models.PositiveSmallIntegerField(default=24)
    admin_confirms = models.BooleanField(default=False)
    brief = models.JSONField(default=dict, blank=True)
    currency = CurrencyField()
    pay_rate = RateField(null=True, blank=True, currency_field="currency")
    accepted_offer = models.ForeignKey(
        "JobOffer", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]


class JobOffer(TenantModel):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        SENT = "sent", _("Sent")
        ACCEPTED = "accepted", _("Accepted")
        DECLINED = "declined", _("Declined")
        EXPIRED = "expired", _("Expired")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    batch = models.ForeignKey(OfferBatch, on_delete=models.CASCADE, related_name="offers")
    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, related_name="+")
    tutor = models.ForeignKey(
        "people.TutorProfile", on_delete=models.PROTECT, related_name="job_offers"
    )
    cascade_order = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    sent_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.CharField(max_length=300, blank=True, default="")
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["cascade_order", "created_at"]
        constraints = [models.UniqueConstraint(fields=["batch", "tutor"], name="job_offer_unique")]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return _own_tutor(user)


class JobPosting(TenantModel):
    """A job on the internal job board for eligible tutors (FR-19-3)."""

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        CLOSED = "closed", _("Closed")
        FILLED = "filled", _("Filled")

    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, related_name="postings")
    title = models.CharField(max_length=200)
    brief = models.JSONField(default=dict, blank=True)
    audience = models.JSONField(default=dict, blank=True)  # {"min_score": 0, "tutors": [...]}
    eligible = models.JSONField(default=list, blank=True)  # tutor ids, fixed at publishing
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    published_at = models.DateTimeField(null=True, blank=True)
    closes_on = models.DateField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-published_at"]


class JobPostingApplication(TenantModel):
    class Status(models.TextChoices):
        APPLIED = "applied", _("Applied")
        SELECTED = "selected", _("Selected")
        REJECTED = "rejected", _("Not selected")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    posting = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name="applications")
    tutor = models.ForeignKey("people.TutorProfile", on_delete=models.CASCADE, related_name="+")
    message = models.TextField(blank=True, default="")
    proposed_availability = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.APPLIED)
    score = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    breakdown = models.JSONField(default=dict, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-score", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["posting", "tutor"], name="posting_application_unique")
        ]


class CoverRequest(TenantModel):
    """Cover for one or more lessons of a tutor who is away (FR-19-4)."""

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        ACCEPTED = "accepted", _("Accepted")
        FILLED = "filled", _("Filled")
        UNFILLED = "unfilled", _("Unfilled")
        CANCELLED = "cancelled", _("Cancelled")

    original_tutor = models.ForeignKey(
        "people.TutorProfile", on_delete=models.PROTECT, related_name="+"
    )
    reason = models.CharField(max_length=300, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    deadline = models.DateTimeField()
    notified = models.JSONField(default=list, blank=True)  # tutor ids
    accepted_by = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["deadline"]


class CoverLesson(TenantModel):
    request = models.ForeignKey(CoverRequest, on_delete=models.CASCADE, related_name="lessons")
    lesson = models.ForeignKey("scheduling.Lesson", on_delete=models.CASCADE, related_name="+")

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["request", "lesson"], name="cover_lesson_unique")
        ]
