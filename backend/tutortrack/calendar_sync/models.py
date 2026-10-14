"""Calendar sync and online meetings (E22 §4)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.models import TenantModel


class CalendarSyncSettings(TenantModel):
    """A personal calendar connection's choices (FR-22-1): which calendars count as busy
    (free/busy only: titles are never stored), where lessons are written, two-way edits."""

    connection = models.OneToOneField(
        "integrations.IntegrationConnection", on_delete=models.CASCADE, related_name="+"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    read_calendar_ids = models.JSONField(default=list, blank=True)
    write_enabled = models.BooleanField(default=True)
    write_calendar_id = models.CharField(max_length=500, blank=True, default="")  # "" = ours
    two_way = models.BooleanField(default=False)
    title_format = models.CharField(max_length=120, blank=True, default="")  # "" = org default

    class Meta(TenantModel.Meta):
        verbose_name_plural = "calendar sync settings"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(user=user)


class SyncState(TenantModel):
    """Incremental sync position and push channel of one external calendar."""

    connection = models.ForeignKey(
        "integrations.IntegrationConnection", on_delete=models.CASCADE, related_name="+"
    )
    calendar_id = models.CharField(max_length=500)
    sync_token = models.TextField(blank=True, default="")
    channel_id = models.CharField(max_length=100, blank=True, default="")
    channel_resource_id = models.CharField(max_length=255, blank=True, default="")
    channel_expiry = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_full_sync_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["connection", "calendar_id"], name="sync_state_unique")
        ]
        indexes = [models.Index(fields=["channel_id"])]


class ExternalEventLink(TenantModel):
    """A lesson written to an external calendar (one per lesson and connection)."""

    lesson = models.ForeignKey(
        "scheduling.Lesson", on_delete=models.CASCADE, related_name="external_events"
    )
    connection = models.ForeignKey(
        "integrations.IntegrationConnection", on_delete=models.CASCADE, related_name="+"
    )
    provider = models.CharField(max_length=30)
    calendar_id = models.CharField(max_length=500)
    external_id = models.CharField(max_length=1000)
    etag = models.CharField(max_length=255, blank=True, default="")
    content_hash = models.CharField(max_length=64, blank=True, default="")
    pushed_start = models.DateTimeField(null=True, blank=True)
    pushed_end = models.DateTimeField(null=True, blank=True)
    last_pushed_at = models.DateTimeField(null=True, blank=True)
    proposed_start = models.DateTimeField(null=True, blank=True)  # a move made outside

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["lesson", "connection"], name="external_link_unique")
        ]
        indexes = [models.Index(fields=["connection", "external_id"])]


class ExternalBusyBlock(TenantModel):
    """Busy time from a connected calendar (E08 conflicts and availability). Only the
    times are kept: no titles, attendees or descriptions (privacy)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    connection = models.ForeignKey(
        "integrations.IntegrationConnection", on_delete=models.CASCADE, related_name="+"
    )
    source = models.CharField(max_length=30)  # provider
    calendar_id = models.CharField(max_length=500)
    external_id = models.CharField(max_length=1000)
    start = models.DateTimeField()
    end = models.DateTimeField()
    all_day = models.BooleanField(default=False)

    class Meta(TenantModel.Meta):
        ordering = ["start"]
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "calendar_id", "external_id"], name="busy_block_unique"
            )
        ]
        indexes = [models.Index(fields=["user", "start", "end"])]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(user=user)


class OnlineMeeting(TenantModel):
    """The online meeting of a lesson (FR-22-4). ``join_url`` is for families,
    ``host_url`` for the tutor; ``attendee_urls`` holds per-student links (Lessonspace)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Being created")
        ACTIVE = "active", _("Ready")
        FAILED = "failed", _("Failed")
        DELETED = "deleted", _("Deleted")

    lesson = models.OneToOneField(
        "scheduling.Lesson", on_delete=models.CASCADE, related_name="online_meeting"
    )
    provider = models.CharField(max_length=20)
    connection = models.ForeignKey(
        "integrations.IntegrationConnection",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    external_id = models.CharField(max_length=255, blank=True, default="")
    join_url = models.URLField(max_length=1000, blank=True, default="")
    host_url = models.URLField(max_length=2000, blank=True, default="")
    passcode = EncryptedField(blank=True, default="")
    attendee_urls = models.JSONField(default=dict, blank=True)
    recording_urls = models.JSONField(default=list, blank=True)  # Phase 3 (E22-T10)
    provisioned_start = models.DateTimeField(null=True, blank=True)
    provisioned_end = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True, default="")
    data = models.JSONField(default=dict, blank=True)

    audit_sensitive_fields = frozenset({"passcode", "host_url"})

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.provider} meeting for {self.lesson_id}"


class MeetingParticipantEvent(TenantModel):
    """A join or leave in an online lesson, from the provider's webhook (E22-T10). Stored
    once per provider event id; the person is matched to the lesson's tutor or students
    where possible. Names only: no emails or IP addresses are kept."""

    class Kind(models.TextChoices):
        JOINED = "joined", _("Joined")
        LEFT = "left", _("Left")

    lesson = models.ForeignKey(
        "scheduling.Lesson", on_delete=models.CASCADE, related_name="video_events"
    )
    meeting = models.ForeignKey(
        OnlineMeeting, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=200)
    kind = models.CharField(max_length=6, choices=Kind.choices)
    at = models.DateTimeField()
    participant_key = models.CharField(max_length=120)  # provider's participant id
    name = models.CharField(max_length=200, blank=True, default="")
    role = models.CharField(max_length=10, blank=True, default="")  # tutor | student | guest
    student = models.ForeignKey(
        "people.Student", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    tutor = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "provider", "event_id"], name="video_event_once"
            )
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.name} at {self.at}"


class LessonRecording(TenantModel):
    """A recording of an online lesson (E22-T10, FR-22-4 "Recordings"): a reference to the
    file at the provider, never a copy. Links are encrypted and handed out only through
    an access-checked, audited endpoint. Recordings of lessons where a student has not
    consented to recording (E29 ``lesson-recording``) are ``restricted``: hidden from
    families and tutors until staff review them."""

    class Status(models.TextChoices):
        AVAILABLE = "available", _("Available")
        RESTRICTED = "restricted", _("Restricted (no recording consent)")
        DELETED = "deleted", _("Deleted")

    lesson = models.ForeignKey(
        "scheduling.Lesson", on_delete=models.CASCADE, related_name="recordings"
    )
    meeting = models.ForeignKey(
        OnlineMeeting, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    provider = models.CharField(max_length=20)
    external_id = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.AVAILABLE)
    started_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    size_bytes = models.BigIntegerField(default=0)
    file_type = models.CharField(max_length=10, blank=True, default="")
    play_url = EncryptedField(blank=True, default="")
    download_url = EncryptedField(blank=True, default="")
    password = EncryptedField(blank=True, default="")
    missing_consent = models.JSONField(default=list, blank=True)  # student ids
    shared_with_family = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_reason = models.CharField(max_length=200, blank=True, default="")

    audit_sensitive_fields = frozenset({"play_url", "download_url", "password"})

    class Meta(TenantModel.Meta):
        ordering = ["-started_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "provider", "external_id"], name="recording_once"
            )
        ]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(lesson__tutors__tutor__membership__user=user)

    def __str__(self) -> str:
        return f"Recording of {self.lesson_id}"


class MeetingPreference(TenantModel):
    """A tutor's default video provider (FR-22-4 "default per tutor")."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    provider = models.CharField(max_length=20, blank=True, default="")  # "" = org default
    use_personal_room = models.BooleanField(default=False)  # Zoom personal meeting room

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["organisation", "user"], name="meeting_pref_unique")
        ]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(user=user)
