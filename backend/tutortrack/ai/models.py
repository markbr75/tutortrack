"""AI assistant records (E31 §5).

Nothing here stores a prompt or raw model output: ``AIRequestLog`` keeps a hash of the
*redacted* input, token counts and the outcome; ``AIFeedback`` keeps a rating and edit
statistics, not the texts. Drafts are returned to the person and only reach other apps'
records through their own services after a human applies them.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.models import TenantModel


class Feature(models.TextChoices):
    LESSON_REPORT = "lesson_report", _("Lesson report drafting")
    PROGRESS_REPORT = "progress_report", _("Progress report comments")
    PARENT_REWRITE = "parent_rewrite", _("Explain to parent and translate")
    ENQUIRY = "enquiry", _("Enquiry extraction and triage")
    INBOX = "inbox", _("Inbox replies, intent and summaries")
    COMMAND_BAR = "command_bar", _("Command bar")
    COPILOT = "copilot", _("Business copilot")
    CONTENT = "content", _("Content writing")
    MATCHING = "matching", _("Matching explanations")


class AIFeatureSetting(TenantModel):
    """A tenant's opt-in for one feature (off until turned on), with tone and spelling
    overrides (blank = the organisation's ``ai.tone`` / ``ai.spelling``)."""

    class Tone(models.TextChoices):
        DEFAULT = "", _("Organisation default")
        FRIENDLY = "friendly", _("Friendly")
        FORMAL = "formal", _("Formal")

    class Language(models.TextChoices):
        DEFAULT = "", _("Organisation default")
        EN_GB = "en-GB", _("UK English")
        EN_US = "en-US", _("US English")

    feature = models.CharField(max_length=20, choices=Feature.choices)
    enabled = models.BooleanField(default=False)
    tone = models.CharField(max_length=10, choices=Tone.choices, blank=True, default="")
    language = models.CharField(max_length=5, choices=Language.choices, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["feature"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "feature"], name="ai_feature_unique")
        ]

    def __str__(self) -> str:
        return f"{self.feature}: {'on' if self.enabled else 'off'}"


class AIRequestLog(TenantModel):
    """One call to the model (a tool loop counts as one request with several rounds)."""

    class Status(models.TextChoices):
        OK = "ok", _("Completed")
        REFUSED = "refused", _("Declined by the model")
        INCOMPLETE = "incomplete", _("Cut short")
        ERROR = "error", _("Failed")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    feature = models.CharField(max_length=20, choices=Feature.choices)
    prompt_key = models.CharField(max_length=60)
    prompt_version = models.PositiveSmallIntegerField()
    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=60, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    credits = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    tool_rounds = models.PositiveSmallIntegerField(default=0)
    fallback_used = models.BooleanField(default=False)
    redacted_input_hash = models.CharField(max_length=64)  # sha256 of what was sent
    provider_request_id = models.CharField(max_length=100, blank=True, default="")
    error_code = models.CharField(max_length=60, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organisation", "feature", "created_at"])]

    def __str__(self) -> str:
        return f"{self.prompt_key}@{self.prompt_version} {self.status}"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(user_id=getattr(user, "pk", None))


class AIUsage(TenantModel):
    """Monthly totals per person and feature (FR-04-8 metering, usage reports)."""

    period = models.DateField()  # first day of the month (UTC)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    feature = models.CharField(max_length=20, choices=Feature.choices)
    requests = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    cache_read_tokens = models.PositiveBigIntegerField(default=0)
    cache_write_tokens = models.PositiveBigIntegerField(default=0)
    credits = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        ordering = ["-period", "feature"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "period", "user", "feature"],
                name="ai_usage_unique",
                nulls_distinct=False,
            )
        ]

    def __str__(self) -> str:
        return f"{self.period:%Y-%m} {self.feature}: {self.credits}"


class AIFeedback(TenantModel):
    """Thumbs up/down on a response, with how much the person changed the draft."""

    class Rating(models.TextChoices):
        UP = "up", _("Helpful")
        DOWN = "down", _("Not helpful")

    request = models.ForeignKey(AIRequestLog, on_delete=models.CASCADE, related_name="feedback")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    rating = models.CharField(max_length=4, choices=Rating.choices, blank=True, default="")
    comment = models.CharField(max_length=500, blank=True, default="")
    similarity_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    chars_added = models.PositiveIntegerField(null=True, blank=True)
    chars_removed = models.PositiveIntegerField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["request", "user"], name="ai_feedback_unique")
        ]

    def __str__(self) -> str:
        return f"{self.rating or '-'} on {self.request_id}"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(user_id=getattr(user, "pk", None))


class AIAssist(TenantModel):
    """A draft a person applied to a record: the "AI-assisted" flag (FR-31-1)."""

    request = models.ForeignKey(AIRequestLog, on_delete=models.CASCADE, related_name="assists")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    feature = models.CharField(max_length=20, choices=Feature.choices)
    subject_type = models.CharField(max_length=40)
    subject_id = models.CharField(max_length=64)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organisation", "subject_type", "subject_id"])]
        constraints = [
            models.UniqueConstraint(
                fields=["request", "subject_type", "subject_id"], name="ai_assist_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.subject_type}:{self.subject_id}"


class AIProposal(TenantModel):
    """An action the AI proposed (command bar, triage, routing). Nothing changes until the
    person confirms it; then ``actions`` runs it through the owning app's services with
    the person's permissions (human in the loop)."""

    class Status(models.TextChoices):
        PROPOSED = "proposed", _("Waiting for confirmation")
        EXECUTED = "executed", _("Done")
        FAILED = "failed", _("Failed")
        DISCARDED = "discarded", _("Discarded")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    request = models.ForeignKey(
        AIRequestLog, null=True, blank=True, on_delete=models.SET_NULL, related_name="proposals"
    )
    feature = models.CharField(max_length=20, choices=Feature.choices)
    action = models.CharField(max_length=40)
    params = models.JSONField(default=dict)
    summary = models.CharField(max_length=300)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PROPOSED)
    result = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=300, blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action} ({self.status})"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(user_id=getattr(user, "pk", None))


class ThreadInsight(TenantModel):
    """The latest intent classification of an inbox conversation (FR-31-3)."""

    thread = models.OneToOneField("comms.Thread", on_delete=models.CASCADE, related_name="+")
    intent = models.CharField(max_length=20)
    confidence = models.PositiveSmallIntegerField(default=0)  # percent
    message_count = models.PositiveIntegerField(default=0)  # messages when classified
    request = models.ForeignKey(
        AIRequestLog, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    classified_at = models.DateTimeField()

    def __str__(self) -> str:
        return f"{self.thread_id}: {self.intent}"
