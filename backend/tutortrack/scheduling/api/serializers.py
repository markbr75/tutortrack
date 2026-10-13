from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.catalogue.models import Location, Room, Service
from tutortrack.core.api.serializers import (
    BaseModelSerializer,
    MoneyOut,
    MoneySerializerField,
    TenantRelatedField,
)
from tutortrack.jobs.models import Job
from tutortrack.people.models import Student, TutorProfile
from tutortrack.tenancy.api.serializers import validate_tz as _validate_tz

from ..models import (
    AvailabilityException,
    AvailabilityWindow,
    BookingHold,
    BookingSettings,
    CalendarEvent,
    ICalFeedToken,
    Lesson,
    LessonAttendee,
    LessonSeries,
    LessonTutor,
    RescheduleRequest,
)


def validate_tz(value: str) -> None:
    _validate_tz(value)


RATE = {"decimal_places": 4, "required": False, "allow_null": True}


class LessonTutorSerializer(BaseModelSerializer):
    name = serializers.CharField(source="tutor.full_name", read_only=True)

    class Meta:
        model = LessonTutor
        fields = [
            "id",
            "tutor",
            "name",
            "pay_rate_override",
            "pay_amount",
            "pay_snapshot",
            "payable",
            "pay_percent",
        ]
        field_permissions = {
            "pay_rate_override": "billing.rates.view_pay",
            "pay_amount": "billing.rates.view_pay",
            "pay_snapshot": "billing.rates.view_pay",
        }


class LessonAttendeeSerializer(BaseModelSerializer):
    name = serializers.CharField(source="student.full_name", read_only=True)

    class Meta:
        model = LessonAttendee
        fields = [
            "id",
            "student",
            "name",
            "client",
            "charge_rate_override",
            "charge_amount",
            "tax_amount",
            "charge_snapshot",
            "chargeable",
            "outcome",
            "late_minutes",
            "charge_percent",
            "recorded_at",
        ]
        field_permissions = {
            "charge_rate_override": "billing.rates.view_charge",
            "charge_amount": "billing.rates.view_charge",
            "tax_amount": "billing.rates.view_charge",
            "charge_snapshot": "billing.rates.view_charge",
        }


class LessonSerializer(BaseModelSerializer):
    tutors = LessonTutorSerializer(many=True, read_only=True)
    attendees = LessonAttendeeSerializer(many=True, read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Lesson
        fields = [
            "id",
            "job",
            "series",
            "occurrence_date",
            "is_exception",
            "service",
            "branch",
            "title",
            "start",
            "end",
            "duration_minutes",
            "timezone",
            "status",
            "location",
            "room",
            "online",
            "meeting_url",
            "meeting_provider",
            "notes_internal",
            "notes_for_tutor",
            "notes_for_client",
            "colour",
            "created_via",
            "lock_state",
            "rescheduled_from",
            "reschedule_reason",
            "status_reason",
            "status_changed_at",
            "chargeable_cancellation",
            "cancelled_by",
            "actual_start",
            "actual_end",
            "auto_completed",
            "unconfirmed_at",
            "cover_flagged_at",
            "tutors",
            "attendees",
            "custom_fields",
            "created_at",
        ]
        read_only_fields = fields
        field_permissions = {"notes_internal": "scheduling.lesson.edit"}


class LessonAttendeeInput(serializers.Serializer):
    student = TenantRelatedField(Student)
    charge_rate_override = MoneySerializerField(**RATE)


class LessonTutorInput(serializers.Serializer):
    tutor = TenantRelatedField(TutorProfile)
    pay_rate_override = MoneySerializerField(**RATE)


class LessonWriteSerializer(serializers.Serializer):
    job = TenantRelatedField(Job, required=False, allow_null=True)
    service = TenantRelatedField(Service, required=False, allow_null=True)
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    timezone = serializers.CharField(required=False, validators=[validate_tz])
    attendees = LessonAttendeeInput(many=True, required=False)
    tutors = LessonTutorInput(many=True, required=False)
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    location = TenantRelatedField(Location, required=False, allow_null=True)
    room = TenantRelatedField(Room, required=False, allow_null=True)
    online = serializers.BooleanField(required=False)
    meeting_url = serializers.URLField(required=False, allow_blank=True)
    notes_internal = serializers.CharField(required=False, allow_blank=True)
    notes_for_tutor = serializers.CharField(required=False, allow_blank=True)
    notes_for_client = serializers.CharField(required=False, allow_blank=True)
    colour = serializers.RegexField(r"^(#[0-9a-fA-F]{6})?$", required=False, allow_blank=True)
    override_conflicts = serializers.BooleanField(required=False, default=False)


class LessonUpdateSerializer(LessonWriteSerializer):
    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)
    job = None  # type: ignore[assignment]
    scope = serializers.ChoiceField(choices=["this", "following", "all"], default="this")
    overwrite_exceptions = serializers.BooleanField(required=False, default=False)
    notify = serializers.BooleanField(required=False, default=True)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class ConflictSerializer(serializers.Serializer):
    kind = serializers.CharField()
    severity = serializers.ChoiceField(choices=["hard", "soft"])
    message = serializers.CharField()
    lesson_id = serializers.CharField(allow_null=True)
    tutor_id = serializers.CharField(allow_null=True)
    student_id = serializers.CharField(allow_null=True)


class LessonResultSerializer(serializers.Serializer):
    lesson = LessonSerializer()
    warnings = ConflictSerializer(many=True)


CANCELLED_BY = [("client", "Client"), ("student", "Student"), ("tutor", "Tutor"), ("admin", "Us")]


class PolicyOverrideSerializer(serializers.Serializer):
    charge_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100
    )
    pay_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100
    )
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class CancelSerializer(serializers.Serializer):
    cancelled_by = serializers.ChoiceField(choices=CANCELLED_BY, default="admin")
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    notify = serializers.BooleanField(required=False, default=True)
    scope = serializers.ChoiceField(choices=["this", "following"], default="this")
    override = PolicyOverrideSerializer(required=False, allow_null=True, default=None)


class CancelOutcomeSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["free", "late", "tutor", "admin"])
    charge_percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    pay_percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    policy_charge_percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    policy_pay_percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    notice_minutes = serializers.IntegerField()
    makeup_credit = serializers.BooleanField()
    policy_name = serializers.CharField()
    message = serializers.CharField()


class CancelResultSerializer(serializers.Serializer):
    outcome = CancelOutcomeSerializer()
    lesson = LessonSerializer(allow_null=True, help_text="Null for a preview.")
    following_cancelled = serializers.IntegerField()


class AttendanceRowSerializer(serializers.Serializer):
    attendee = serializers.UUIDField()
    outcome = serializers.ChoiceField(choices=LessonAttendee.Outcome.choices)
    late_minutes = serializers.IntegerField(
        min_value=0, max_value=600, required=False, allow_null=True
    )


class CompleteSerializer(serializers.Serializer):
    attendance = AttendanceRowSerializer(many=True, required=False, default=list)
    actual_start = serializers.DateTimeField(required=False, allow_null=True, default=None)
    actual_end = serializers.DateTimeField(required=False, allow_null=True, default=None)
    override_balance = serializers.BooleanField(required=False, default=False)


class AttendanceSerializer(serializers.Serializer):
    attendance = serializers.ListField(child=AttendanceRowSerializer(), min_length=1)


class LessonReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class RescheduleSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    notify = serializers.BooleanField(required=False, default=True)
    override_conflicts = serializers.BooleanField(required=False, default=False)


class DuplicateSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    override_conflicts = serializers.BooleanField(required=False, default=False)


class BulkLessonSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["complete", "cancel", "reassign_tutor", "change_location", "delete"]
    )
    ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=200)
    tutor = TenantRelatedField(TutorProfile, required=False)
    location = TenantRelatedField(Location, required=False, allow_null=True)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    cancelled_by = serializers.ChoiceField(choices=CANCELLED_BY, default="admin")


class BulkResultSerializer(serializers.Serializer):
    succeeded = serializers.ListField(child=serializers.CharField())
    failed = serializers.DictField(child=serializers.CharField(), help_text="Lesson id: reason")


class SeriesSerializer(BaseModelSerializer):
    class Meta:
        model = LessonSeries
        fields = [
            "id",
            "job",
            "service",
            "rrule",
            "start_date",
            "start_time",
            "timezone",
            "duration_minutes",
            "until",
            "count",
            "horizon_generated_until",
            "skip_holidays",
            "template",
            "status",
            "split_from",
            "created_at",
        ]
        read_only_fields = fields


class SeriesCreateSerializer(serializers.Serializer):
    job = TenantRelatedField(Job, required=False, allow_null=True)
    service = TenantRelatedField(Service, required=False, allow_null=True)
    rrule = serializers.CharField(max_length=300, help_text="e.g. FREQ=WEEKLY;BYDAY=MO,WE")
    start_date = serializers.DateField()
    start_time = serializers.TimeField()
    duration_minutes = serializers.IntegerField(min_value=5, max_value=720)
    timezone = serializers.CharField(required=False, validators=[validate_tz])
    until = serializers.DateField(required=False, allow_null=True)
    count = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=520)
    skip_holidays = serializers.BooleanField(required=False, default=True)
    attendees = LessonAttendeeInput(many=True, required=False)
    tutors = LessonTutorInput(many=True, required=False)
    location = TenantRelatedField(Location, required=False, allow_null=True)
    room = TenantRelatedField(Room, required=False, allow_null=True)
    online = serializers.BooleanField(required=False, default=False)
    notes_for_tutor = serializers.CharField(required=False, allow_blank=True, default="")
    conflict_mode = serializers.ChoiceField(choices=["skip", "create", "fail"], default="skip")


class SeriesUpdateSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(choices=["following", "all"])
    from_lesson = TenantRelatedField(Lesson, required=False)
    overwrite_exceptions = serializers.BooleanField(required=False, default=False)
    start_time = serializers.TimeField(required=False)
    duration_minutes = serializers.IntegerField(min_value=5, max_value=720, required=False)
    rrule = serializers.CharField(max_length=300, required=False)
    until = serializers.DateField(required=False, allow_null=True)
    count = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    skip_holidays = serializers.BooleanField(required=False)
    attendees = LessonAttendeeInput(many=True, required=False)
    tutors = LessonTutorInput(many=True, required=False)
    location = TenantRelatedField(Location, required=False, allow_null=True)
    online = serializers.BooleanField(required=False)
    notes_for_tutor = serializers.CharField(required=False, allow_blank=True)


class SkippedSerializer(serializers.Serializer):
    date = serializers.DateField()
    conflicts = ConflictSerializer(many=True)


class SeriesResultSerializer(serializers.Serializer):
    series = SeriesSerializer()
    lessons_created = serializers.IntegerField()
    lessons_changed = serializers.IntegerField()
    skipped = SkippedSerializer(many=True)
    conflicting = serializers.ListField(child=serializers.CharField())


class EndSeriesSerializer(serializers.Serializer):
    after = serializers.DateField(required=False)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class ConflictCheckSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    timezone = serializers.CharField(required=False, validators=[validate_tz])
    tutors = serializers.ListField(
        child=TenantRelatedField(TutorProfile), required=False, default=list
    )
    students = serializers.ListField(
        child=TenantRelatedField(Student), required=False, default=list
    )
    lesson = TenantRelatedField(
        Lesson, required=False, allow_null=True, help_text="Ignore this lesson (editing it)."
    )
    location = TenantRelatedField(Location, required=False, allow_null=True)
    room = TenantRelatedField(Room, required=False, allow_null=True)
    online = serializers.BooleanField(required=False, default=False)
    job = TenantRelatedField(Job, required=False, allow_null=True)


class PersonRef(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField(allow_blank=True)


class CalendarItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["lesson", "event"])
    id = serializers.CharField()
    title = serializers.CharField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    timezone = serializers.CharField()
    status = serializers.CharField()
    colour = serializers.CharField()
    service = serializers.CharField(allow_null=True)
    job = serializers.CharField(allow_null=True)
    series = serializers.CharField(allow_null=True)
    location = serializers.CharField(allow_blank=True)
    room = serializers.CharField(allow_null=True)
    room_name = serializers.CharField(allow_blank=True)
    online = serializers.BooleanField()
    tutors = PersonRef(many=True)
    students = PersonRef(many=True)
    locked = serializers.BooleanField()
    org_wide = serializers.BooleanField(required=False)
    all_day = serializers.BooleanField(required=False)


class CalendarEventSerializer(BaseModelSerializer):
    tutors = serializers.ListField(
        child=TenantRelatedField(TutorProfile), required=False, write_only=True
    )
    participants = serializers.SerializerMethodField()
    timezone = serializers.CharField(validators=[validate_tz])

    class Meta:
        model = CalendarEvent
        fields = [
            "id",
            "type",
            "title",
            "description",
            "start",
            "end",
            "timezone",
            "all_day",
            "org_wide",
            "branch",
            "tutors",
            "participants",
            "paid",
            "cancel_lessons",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_participants(self, obj: CalendarEvent) -> list[str]:
        return [str(p.tutor_id) for p in obj.participants.all()]


class WindowSerializer(BaseModelSerializer):
    class Meta:
        model = AvailabilityWindow
        fields = ["weekday", "start_time", "end_time", "mode"]
        extra_kwargs = {"weekday": {"min_value": 0, "max_value": 6}}


class AvailabilitySerializer(serializers.Serializer):
    effective_from = serializers.DateField()
    timezone = serializers.CharField(validators=[validate_tz])
    windows = WindowSerializer(many=True)


class ExceptionSerializer(BaseModelSerializer):
    tutor = TenantRelatedField(TutorProfile)
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)

    class Meta:
        model = AvailabilityException
        fields = [
            "id", "tutor", "tutor_name", "type", "start", "end", "reason", "status",
            "decided_at", "decision_note", "cover_request_id", "created_at",
        ]  # fmt: skip
        read_only_fields = [
            "id", "status", "decided_at", "decision_note", "cover_request_id", "created_at",
        ]  # fmt: skip


class SlotSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()


class FeedSerializer(BaseModelSerializer):
    class Meta:
        model = ICalFeedToken
        fields = ["id", "kind", "subject_id", "revoked_at", "last_used_at", "created_at"]
        read_only_fields = ["id", "revoked_at", "last_used_at", "created_at"]


class FeedCreatedSerializer(FeedSerializer):
    url = serializers.CharField(read_only=True)

    class Meta(FeedSerializer.Meta):
        fields = [*FeedSerializer.Meta.fields, "url"]


# --- Phase 2: time off decisions, reschedule requests, booking, rooms, re-pricing --------------


class ApprovalDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class TimeSlotInput(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()


class LessonChangeProposal(serializers.Serializer):
    options = TimeSlotInput(many=True, min_length=1, max_length=3)  # type: ignore[call-arg]
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class LessonChangeDecisionSerializer(ApprovalDecisionSerializer):
    choice = serializers.IntegerField(min_value=0, max_value=2, required=False, default=0)
    override_conflicts = serializers.BooleanField(required=False, default=False)


class LessonChangeRequestSerializer(BaseModelSerializer):
    lesson_title = serializers.CharField(source="lesson.title", read_only=True)
    proposed = TimeSlotInput(many=True, read_only=True)

    class Meta:
        model = RescheduleRequest
        fields = [
            "id", "lesson", "lesson_title", "requester", "proposed", "reason", "status",
            "deadline", "original_start", "original_end", "chosen", "decided_at",
            "decision_note", "created_at",
        ]  # fmt: skip
        read_only_fields = fields


class BookingSettingsSerializer(BaseModelSerializer):
    tutors = serializers.ListField(child=serializers.UUIDField(), required=False)
    location = TenantRelatedField(Location, required=False, allow_null=True)

    class Meta:
        model = BookingSettings
        fields = [
            "enabled", "allow_new_clients", "min_notice_hours", "max_advance_days",
            "slot_interval_minutes", "buffer_minutes", "approval_required", "payment",
            "hold_minutes", "cancellation_window_hours", "tutors", "location", "terms",
        ]  # fmt: skip


class BookingQuoteSerializer(serializers.Serializer):
    currency = serializers.CharField()
    amount = MoneyOut()
    undiscounted_amount = MoneyOut()
    tax_amount = MoneyOut()
    trace = serializers.ListField(child=serializers.CharField())
    discounts = serializers.ListField(child=serializers.DictField())


class BookingHoldSerializer(BaseModelSerializer):
    service_name = serializers.CharField(source="service.name", read_only=True)
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)
    student_name = serializers.SerializerMethodField()
    quote = serializers.SerializerMethodField()

    class Meta:
        model = BookingHold
        fields = [
            "id", "service", "service_name", "tutor", "tutor_name", "start", "end",
            "timezone", "client", "student", "student_name", "online", "status", "source",
            "expires_at", "quote", "lesson", "trial", "decision_note", "created_at",
        ]  # fmt: skip
        read_only_fields = fields

    @extend_schema_field(BookingQuoteSerializer(allow_null=True))
    def get_quote(self, obj: BookingHold) -> dict[str, Any] | None:
        return obj.quote or None

    @extend_schema_field(serializers.CharField())
    def get_student_name(self, obj: BookingHold) -> str:
        if obj.student is not None:
            return str(obj.student.full_name)
        contact = obj.contact or {}
        return f"{contact.get('student_first_name', '')} {contact.get('last_name', '')}".strip()


class BookingServiceSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    duration_minutes = serializers.IntegerField()
    delivery_mode = serializers.CharField()
    price = MoneyOut(allow_null=True)
    tutors = PersonRef(many=True)


class BookingSlotSerializer(serializers.Serializer):
    tutor = serializers.CharField()
    tutor_name = serializers.CharField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()


class BookingContactSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    student_first_name = serializers.CharField(max_length=100)


class BookingHoldInput(serializers.Serializer):
    service = serializers.UUIDField()
    tutor = serializers.UUIDField(required=False, allow_null=True)
    start = serializers.DateTimeField()
    student = serializers.UUIDField(required=False, allow_null=True)
    contact = BookingContactSerializer(required=False)
    promo_code = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")


class BookingHoldCreatedSerializer(BookingHoldSerializer):
    token = serializers.CharField(read_only=True)

    class Meta(BookingHoldSerializer.Meta):
        fields = [*BookingHoldSerializer.Meta.fields, "token"]
        read_only_fields = fields


class BookingSubmitResultSerializer(serializers.Serializer):
    booking = BookingHoldSerializer()
    pay_url = serializers.CharField(allow_blank=True)


class RoomScheduleSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    location = serializers.CharField()
    location_name = serializers.CharField()
    capacity = serializers.IntegerField(allow_null=True)
    colour = serializers.CharField(allow_blank=True)
    lessons = CalendarItemSerializer(many=True)


class RepriceRequestSerializer(serializers.Serializer):
    service = serializers.UUIDField(required=False)
    tutor = serializers.UUIDField(required=False)
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    include_past = serializers.BooleanField(required=False, default=False)
    dry_run = serializers.BooleanField(required=False, default=True)


class RepriceResultSerializer(serializers.Serializer):
    lessons = serializers.IntegerField()
    dry_run = serializers.BooleanField()
