"""Lessons, series, calendar events, availability and iCal feeds (E08)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.db import models
from django.db.models import Func, Q, Value
from django.utils.translation import gettext_lazy as _

from tutortrack.core.fields import CurrencyField, MoneyField, RateField
from tutortrack.core.models import BranchScopedModel, TenantModel
from tutortrack.people.models import CustomisableModel


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


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

    def __str__(self) -> str:
        return f"Lesson series from {self.start_date:%Y-%m-%d} at {self.start_time:%H:%M}"


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
    # E08-T12: a room can't hold two lessons at once (exclusion constraint below).
    room = models.ForeignKey(
        "catalogue.Room", null=True, blank=True, on_delete=models.PROTECT, related_name="lessons"
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
    # Delivery (E09): what actually happened.
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.CharField(max_length=7, blank=True, default="")  # client/tutor/...
    auto_completed = models.BooleanField(default=False)
    unconfirmed_at = models.DateTimeField(null=True, blank=True)  # flagged as not confirmed
    # E08-T15: the tutor's approved time off clashes; cover is being found (E19).
    cover_flagged_at = models.DateTimeField(null=True, blank=True)

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
            ExclusionConstraint(
                name="lesson_room_no_overlap",
                expressions=[
                    ("room", RangeOperators.EQUAL),
                    (TsTzRange("start", "end", Value("[)")), RangeOperators.OVERLAPS),
                ],
                condition=Q(room__isnull=False) & ~Q(status="cancelled"),
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
    pay_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal(100))

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["lesson", "tutor"], name="lesson_tutor_unique")
        ]


class LessonAttendee(TenantModel):
    class Outcome(models.TextChoices):
        PRESENT = "present", _("Present")
        LATE = "late", _("Late")
        ABSENT_NOTIFIED = "absent_notified", _("Absent (notified)")
        NO_SHOW = "no_show", _("No-show")
        CANCELLED_CLIENT = "cancelled_client", _("Cancelled by client")
        CANCELLED_TUTOR = "cancelled_tutor", _("Cancelled by tutor")
        CANCELLED_ADMIN = "cancelled_admin", _("Cancelled by us")

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="attendees")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="lessons")
    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="+")
    currency = CurrencyField()
    charge_rate_override = RateField(null=True, blank=True)
    charge_amount = MoneyField(null=True, blank=True)
    tax_amount = MoneyField(null=True, blank=True)
    charge_snapshot = models.JSONField(default=dict, blank=True)
    chargeable = models.BooleanField(default=True)
    # Attendance (E09 FR-09-2); the policy maps the outcome to a charge percentage.
    outcome = models.CharField(max_length=16, choices=Outcome.choices, blank=True, default="")
    late_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    charge_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal(100))
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    recorded_at = models.DateTimeField(null=True, blank=True)
    # E06-T09: the promo code used when this student booked (kept for re-pricing).
    promo_code = models.ForeignKey(
        "catalogue.PromoCode", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

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

    def __str__(self) -> str:
        return f"{self.title} {self.start:%Y-%m-%d}"


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
    # E08-T15 approval workflow.
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True, default="")
    cover_request_id = models.UUIDField(null=True, blank=True)  # E19 cover for the clashes

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


class RescheduleRequest(TenantModel):
    """A client or tutor asks to move a lesson (FR-08-8, E08-T13). The other side or an
    admin picks one of the proposed times (the lesson moves) or declines; undecided
    requests are declined automatically at ``deadline`` (``RescheduleRequestWorkflow``)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for a decision")
        APPROVED = "approved", _("Approved")
        DECLINED = "declined", _("Declined")
        CANCELLED = "cancelled", _("Withdrawn")
        EXPIRED = "expired", _("Not answered in time")

    class Party(models.TextChoices):
        CLIENT = "client", _("Client")
        TUTOR = "tutor", _("Tutor")
        STAFF = "staff", _("Staff")
        CALENDAR = "calendar", _("Tutor's calendar")

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="reschedule_requests")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    requester = models.CharField(max_length=8, choices=Party.choices)
    proposed = models.JSONField(default=list)  # [{"start": iso, "end": iso}]
    reason = models.CharField(max_length=300, blank=True, default="")
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING)
    deadline = models.DateTimeField()
    original_start = models.DateTimeField()
    original_end = models.DateTimeField()
    chosen = models.PositiveSmallIntegerField(null=True, blank=True)  # index into proposed
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["lesson"],
                condition=Q(status="pending"),
                name="reschedule_one_pending_per_lesson",
            )
        ]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(lesson__in=Lesson.objects.filter(Lesson.own_scope_q(user)).values("pk"))


class BookingSettings(TenantModel):
    """Online self-booking (FR-08-9, E08-T14): one row per organisation."""

    class Payment(models.TextChoices):
        NONE = "none", _("Pay later (invoice as usual)")
        AT_BOOKING = "at_booking", _("Pay when booking")

    enabled = models.BooleanField(default=False)
    allow_new_clients = models.BooleanField(default=True)  # public widget, no account yet
    min_notice_hours = models.PositiveIntegerField(default=24)
    max_advance_days = models.PositiveIntegerField(default=60)
    slot_interval_minutes = models.PositiveIntegerField(default=30)
    buffer_minutes = models.PositiveIntegerField(default=0)
    approval_required = models.BooleanField(default=False)
    payment = models.CharField(max_length=10, choices=Payment.choices, default=Payment.NONE)
    hold_minutes = models.PositiveIntegerField(default=10)
    cancellation_window_hours = models.PositiveIntegerField(default=24)
    tutors = models.JSONField(default=list, blank=True)  # tutor ids; [] = every active tutor
    location = models.ForeignKey(
        "catalogue.Location", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    terms = models.TextField(blank=True, default="")

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["organisation"], name="booking_settings_one_per_org")
        ]


class BookingHold(TenantModel):
    """A slot held while someone books it (FR-08-9). ``BookingHoldWorkflow`` releases it
    when the hold expires unpaid, or confirms it (creating the lesson)."""

    class Status(models.TextChoices):
        HELD = "held", _("Held")
        AWAITING_PAYMENT = "awaiting_payment", _("Waiting for payment")
        AWAITING_APPROVAL = "awaiting_approval", _("Waiting for approval")
        CONFIRMED = "confirmed", _("Confirmed")
        DECLINED = "declined", _("Declined")
        EXPIRED = "expired", _("Expired")
        CANCELLED = "cancelled", _("Cancelled")

    ACTIVE = ("held", "awaiting_payment", "awaiting_approval")

    class Source(models.TextChoices):
        PORTAL = "portal", _("Client portal")
        WIDGET = "widget", _("Website widget")

    service = models.ForeignKey("catalogue.Service", on_delete=models.PROTECT, related_name="+")
    tutor = models.ForeignKey("people.TutorProfile", on_delete=models.PROTECT, related_name="+")
    branch = models.ForeignKey("tenancy.Branch", on_delete=models.PROTECT, related_name="+")
    location = models.ForeignKey(
        "catalogue.Location", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    online = models.BooleanField(default=False)
    start = models.DateTimeField()
    end = models.DateTimeField()
    timezone = models.CharField(max_length=64)
    client = models.ForeignKey(
        "people.Client", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    student = models.ForeignKey(
        "people.Student", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    contact = models.JSONField(default=dict, blank=True)  # new clients: name, email, phone...
    promo_code = models.ForeignKey(
        "catalogue.PromoCode", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    trial = models.BooleanField(default=False)
    quote = models.JSONField(default=dict, blank=True)  # the price shown when booking
    status = models.CharField(max_length=17, choices=Status.choices, default=Status.HELD)
    source = models.CharField(max_length=6, choices=Source.choices, default=Source.PORTAL)
    expires_at = models.DateTimeField()
    payment_request_id = models.UUIDField(null=True, blank=True)  # billing.PaymentRequest
    lesson = models.ForeignKey(
        Lesson, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    token_hash = models.CharField(max_length=64, blank=True, default="")  # public status link
    created_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decision_note = models.CharField(max_length=300, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organisation", "start"], name="booking_hold_start_idx")]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(created_by_user=user)


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
