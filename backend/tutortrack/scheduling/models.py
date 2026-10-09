"""Lessons, series, calendar events, availability and iCal feeds (E08)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.fields import CurrencyField, MoneyField, RateField
from tutortrack.core.models import BranchScopedModel, TenantModel
from tutortrack.people.models import CustomisableModel


class LessonSeries(TenantModel):
    """A recurring lesson. Occurrences are materialised as ``Lesson`` rows up to a rolling
    horizon; ``rrule`` is an RFC 5545 rule (without DTSTART) expanded in ``timezone``."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        ENDED = "ended", _("Ended")

    job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.PROTECT, related_name="series"
    )
    service = models.ForeignKey("catalogue.Service", on_delete=models.PROTECT, related_name="+")
    branch = models.ForeignKey("tenancy.Branch", on_delete=models.PROTECT, related_name="+")
    rrule = models.CharField(max_length=300)  # e.g. FREQ=WEEKLY;BYDAY=MO,WE
    start_date = models.DateField()
    start_time = models.TimeField()
    timezone = models.CharField(max_length=64)
    duration_minutes = models.PositiveIntegerField()
    until = models.DateField(null=True, blank=True)
    count = models.PositiveIntegerField(null=True, blank=True)
    horizon_generated_until = models.DateField(null=True, blank=True)
    skip_holidays = models.BooleanField(default=True)
    # Who and where for new occurrences: {"tutors": [{"tutor": id, "pay_rate_override": {...}}],
    # "attendees": [{"student": id, "charge_rate_override": {...}}], "location": id,
    # "online": bool, "notes_for_tutor": str, ...}
    template = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.ACTIVE)
    split_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["start_date"]
        verbose_name_plural = "lesson series"


class Lesson(BranchScopedModel, CustomisableModel):
    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")
        MISSED = "missed", _("Missed")

    class CreatedVia(models.TextChoices):
        ADMIN = "admin", _("Admin")
        TUTOR = "tutor", _("Tutor")
        CLIENT_BOOKING = "client_booking", _("Client booking")
        API = "api", _("API")
        IMPORT = "import", _("Import")
        SERIES = "series", _("Series")

    class Lock(models.TextChoices):
        UNLOCKED = "unlocked", _("Unlocked")
        INVOICED = "invoiced", _("Invoiced")
        PAID = "paid", _("Paid")

    job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.PROTECT, related_name="lessons"
    )
    series = models.ForeignKey(
        LessonSeries, null=True, blank=True, on_delete=models.SET_NULL, related_name="lessons"
    )
    occurrence_date = models.DateField(null=True, blank=True)  # the series date it fills
    is_exception = models.BooleanField(default=False)  # changed apart from its series
    service = models.ForeignKey("catalogue.Service", on_delete=models.PROTECT, related_name="+")
    title = models.CharField(max_length=200)
    start = models.DateTimeField()
    end = models.DateTimeField()
    timezone = models.CharField(max_length=64)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNED)
    location = models.ForeignKey(
        "catalogue.Location", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    online = models.BooleanField(default=False)
    meeting_url = models.URLField(blank=True, default="")
    meeting_provider = models.CharField(max_length=20, blank=True, default="")
    notes_internal = models.TextField(blank=True, default="")
    notes_for_tutor = models.TextField(blank=True, default="")
    notes_for_client = models.TextField(blank=True, default="")
    colour = models.CharField(max_length=7, blank=True, default="")
    created_via = models.CharField(
        max_length=15, choices=CreatedVia.choices, default=CreatedVia.ADMIN
    )
    lock_state = models.CharField(max_length=8, choices=Lock.choices, default=Lock.UNLOCKED)
    rescheduled_from = models.DateTimeField(null=True, blank=True)
    reschedule_reason = models.CharField(max_length=300, blank=True, default="")
    status_reason = models.CharField(max_length=300, blank=True, default="")
    status_changed_at = models.DateTimeField(null=True, blank=True)
    chargeable_cancellation = models.BooleanField(default=False)  # E09 policies decide

    class Meta(BranchScopedModel.Meta):
        ordering = ["start"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end__gt=models.F("start")), name="lesson_end_after_start"
            ),
            models.UniqueConstraint(
                fields=["series", "occurrence_date"],
                condition=Q(series__isnull=False),
                name="lesson_series_occurrence_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["organisation", "start"], name="lesson_org_start_idx"),
            models.Index(fields=["organisation", "end"], name="lesson_org_end_idx"),
            models.Index(fields=["job", "start"], name="lesson_job_start_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.title} {self.start:%Y-%m-%d %H:%M}"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        ids = LessonTutor.objects.filter(tutor__membership__user=user).values("lesson_id")
        return Q(pk__in=ids)

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    @property
    def is_locked(self) -> bool:
        return self.lock_state != self.Lock.UNLOCKED


class LessonTutor(TenantModel):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="tutors")
    tutor = models.ForeignKey(
        "people.TutorProfile", on_delete=models.PROTECT, related_name="lessons"
    )
    currency = CurrencyField()
    pay_rate_override = RateField(null=True, blank=True)
    pay_amount = MoneyField(null=True, blank=True)
    pay_snapshot = models.JSONField(default=dict, blank=True)  # rate, units, trace
    payable = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["lesson", "tutor"], name="lesson_tutor_unique")
        ]


class LessonAttendee(TenantModel):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="attendees")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="lessons")
    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="+")
    currency = CurrencyField()
    charge_rate_override = RateField(null=True, blank=True)
    charge_amount = MoneyField(null=True, blank=True)
    tax_amount = MoneyField(null=True, blank=True)
    charge_snapshot = models.JSONField(default=dict, blank=True)
    chargeable = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["lesson", "student"], name="lesson_attendee_unique")
        ]


class CalendarEvent(TenantModel):
    """Non-lesson time: meetings, training, blocked time and organisation-wide closures."""

    class Type(models.TextChoices):
        MEETING = "meeting", _("Meeting")
        TRAINING = "training", _("Training")
        ADMIN = "admin", _("Admin")
        BLOCKED = "blocked", _("Blocked / unavailable")
        HOLIDAY = "holiday", _("Holiday / closure")
        CUSTOM = "custom", _("Other")

    type = models.CharField(max_length=10, choices=Type.choices, default=Type.MEETING)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    start = models.DateTimeField()
    end = models.DateTimeField()
    timezone = models.CharField(max_length=64)
    all_day = models.BooleanField(default=False)
    org_wide = models.BooleanField(default=False)
    branch = models.ForeignKey(
        "tenancy.Branch", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    tutors = models.ManyToManyField(
        "people.TutorProfile", blank=True, related_name="+", through="CalendarEventParticipant"
    )
    paid = models.BooleanField(default=False)  # paid hours become pay items (E12)
    cancel_lessons = models.BooleanField(default=False)  # closures cancel lessons in range

    class Meta(TenantModel.Meta):
        ordering = ["start"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end__gt=models.F("start")), name="event_end_after_start"
            )
        ]
        indexes = [models.Index(fields=["organisation", "start"], name="event_org_start_idx")]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        mine = CalendarEventParticipant.objects.filter(tutor__membership__user=user)
        return Q(org_wide=True) | Q(pk__in=mine.values("event_id"))


class CalendarEventParticipant(TenantModel):
    event = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE, related_name="participants")
    tutor = models.ForeignKey("people.TutorProfile", on_delete=models.CASCADE, related_name="+")

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["event", "tutor"], name="event_participant_unique")
        ]


class AvailabilityTemplate(TenantModel):
    """A tutor's weekly availability from ``effective_from`` (until the next template)."""

    tutor = models.ForeignKey(
        "people.TutorProfile", on_delete=models.CASCADE, related_name="availability_templates"
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    timezone = models.CharField(max_length=64)

    class Meta(TenantModel.Meta):
        ordering = ["tutor", "-effective_from"]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(tutor__membership__user=user)


class AvailabilityWindow(TenantModel):
    class Mode(models.TextChoices):
        ANY = "any", _("In person or online")
        IN_PERSON = "in_person", _("In person only")
        ONLINE = "online", _("Online only")

    template = models.ForeignKey(
        AvailabilityTemplate, on_delete=models.CASCADE, related_name="windows"
    )
    weekday = models.PositiveSmallIntegerField()  # Monday = 0
    start_time = models.TimeField()
    end_time = models.TimeField()
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.ANY)

    class Meta(TenantModel.Meta):
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=models.F("start_time")), name="window_end_after_start"
            ),
            models.CheckConstraint(condition=Q(weekday__lte=6), name="window_weekday_range"),
        ]


class AvailabilityException(TenantModel):
    """Extra availability or time off for a tutor (FR-08-5)."""

    class Type(models.TextChoices):
        EXTRA = "extra", _("Extra availability")
        OFF = "off", _("Time off")

    class Status(models.TextChoices):
        REQUESTED = "requested", _("Requested")
        APPROVED = "approved", _("Approved")
        DECLINED = "declined", _("Declined")

    tutor = models.ForeignKey(
        "people.TutorProfile", on_delete=models.CASCADE, related_name="availability_exceptions"
    )
    type = models.CharField(max_length=5, choices=Type.choices)
    start = models.DateTimeField()
    end = models.DateTimeField()
    reason = models.CharField(max_length=300, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.APPROVED)

    class Meta(TenantModel.Meta):
        ordering = ["start"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end__gt=models.F("start")), name="exception_end_after_start"
            )
        ]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(tutor__membership__user=user)


class ICalFeedToken(TenantModel):
    """A secret, revocable, read-only calendar feed URL (FR-08-11). Only the hash is kept."""

    class Kind(models.TextChoices):
        TUTOR = "tutor", _("Tutor schedule")
        CLIENT = "client", _("Household schedule")
        STUDENT = "student", _("Student schedule")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=7, choices=Kind.choices)
    subject_id = models.UUIDField()
    token_hash = models.CharField(max_length=64, unique=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
