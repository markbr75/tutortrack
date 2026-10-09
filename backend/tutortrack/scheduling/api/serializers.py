from __future__ import annotations

from rest_framework import serializers

from tutortrack.catalogue.models import Location, Service
from tutortrack.core.api.serializers import (
    BaseModelSerializer,
    MoneySerializerField,
    TenantRelatedField,
)
from tutortrack.jobs.models import Job
from tutortrack.people.models import Student, TutorProfile
from tutortrack.tenancy.api.serializers import validate_tz as _validate_tz

from ..models import (
    AvailabilityException,
    AvailabilityWindow,
    CalendarEvent,
    ICalFeedToken,
    Lesson,
    LessonAttendee,
    LessonSeries,
    LessonTutor,
)


def validate_tz(value: str) -> None:
    _validate_tz(value)


RATE = {"decimal_places": 4, "required": False, "allow_null": True}


class LessonTutorSerializer(BaseModelSerializer):
    name = serializers.CharField(source="tutor.full_name", read_only=True)

    class Meta:
        model = LessonTutor
        fields = ["tutor", "name", "pay_rate_override", "pay_amount", "pay_snapshot", "payable"]
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
            "student",
            "name",
            "client",
            "charge_rate_override",
            "charge_amount",
            "tax_amount",
            "charge_snapshot",
            "chargeable",
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
    online = serializers.BooleanField(required=False)
    meeting_url = serializers.URLField(required=False, allow_blank=True)
    notes_internal = serializers.CharField(required=False, allow_blank=True)
    notes_for_tutor = serializers.CharField(required=False, allow_blank=True)
    notes_for_client = serializers.CharField(required=False, allow_blank=True)
    colour = serializers.RegexField(r"^(#[0-9a-fA-F]{6})?$", required=False, allow_blank=True)
    override_conflicts = serializers.BooleanField(default=False)


class LessonUpdateSerializer(LessonWriteSerializer):
    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)
    job = None  # type: ignore[assignment]
    scope = serializers.ChoiceField(choices=["this", "following", "all"], default="this")
    overwrite_exceptions = serializers.BooleanField(default=False)
    notify = serializers.BooleanField(default=True)
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


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    chargeable = serializers.BooleanField(default=False)
    notify = serializers.BooleanField(default=True)


class LessonReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class RescheduleSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    notify = serializers.BooleanField(default=True)
    override_conflicts = serializers.BooleanField(default=False)


class DuplicateSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    override_conflicts = serializers.BooleanField(default=False)


class BulkLessonSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["complete", "cancel", "reassign_tutor", "change_location", "delete"]
    )
    ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=200)
    tutor = TenantRelatedField(TutorProfile, required=False)
    location = TenantRelatedField(Location, required=False, allow_null=True)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


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
    skip_holidays = serializers.BooleanField(default=True)
    attendees = LessonAttendeeInput(many=True, required=False)
    tutors = LessonTutorInput(many=True, required=False)
    location = TenantRelatedField(Location, required=False, allow_null=True)
    online = serializers.BooleanField(default=False)
    notes_for_tutor = serializers.CharField(required=False, allow_blank=True, default="")
    conflict_mode = serializers.ChoiceField(choices=["skip", "create", "fail"], default="skip")


class SeriesUpdateSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(choices=["following", "all"])
    from_lesson = TenantRelatedField(Lesson, required=False)
    overwrite_exceptions = serializers.BooleanField(default=False)
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
    online = serializers.BooleanField(default=False)
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

    class Meta:
        model = AvailabilityException
        fields = ["id", "tutor", "type", "start", "end", "reason", "status", "created_at"]
        read_only_fields = ["id", "status", "created_at"]


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
