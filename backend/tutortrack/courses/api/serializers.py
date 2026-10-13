"""Serializers for courses (E20 §4)."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.catalogue.models import Level, Location, Room, Service, Subject, TaxRate
from tutortrack.core.api.serializers import (
    BaseModelSerializer,
    MoneyOut,
    MoneySerializerField,
    TenantRelatedField,
)
from tutortrack.core.models import StoredFile
from tutortrack.people.models import Student, TutorProfile

from .. import selectors
from ..models import (
    AcademicYear,
    ClassSession,
    ClassTeacher,
    Course,
    Enrolment,
    EnrolmentTransfer,
    GroupClass,
    MakeupBooking,
    RolloverOffer,
    Term,
    TermBreak,
    TermRollover,
)

# --- terms --------------------------------------------------------------------------------------


class AcademicYearSerializer(BaseModelSerializer):
    class Meta:
        model = AcademicYear
        fields = ["id", "branch", "name", "start_date", "end_date", "created_at"]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"branch": {"required": False}}


class TermBreakSerializer(BaseModelSerializer):
    class Meta:
        model = TermBreak
        fields = ["id", "name", "start_date", "end_date"]
        read_only_fields = ["id"]


class TermSerializer(BaseModelSerializer):
    breaks = TermBreakSerializer(many=True, required=False)
    academic_year_name = serializers.CharField(source="academic_year.name", read_only=True)

    class Meta:
        model = Term
        fields = [
            "id",
            "branch",
            "academic_year",
            "academic_year_name",
            "name",
            "start_date",
            "end_date",
            "enrolment_opens",
            "enrolment_closes",
            "breaks",
            "created_at",
        ]
        read_only_fields = ["id", "branch", "created_at"]


# --- courses ------------------------------------------------------------------------------------


class CourseSerializer(BaseModelSerializer):
    service = TenantRelatedField(Service)
    subject = TenantRelatedField(Subject, required=False, allow_null=True)
    level = TenantRelatedField(Level, required=False, allow_null=True)
    tax_rate = TenantRelatedField(TaxRate, required=False, allow_null=True)
    image = TenantRelatedField(StoredFile, required=False, allow_null=True)
    price = MoneySerializerField()
    deposit = MoneySerializerField(required=False, allow_null=True)
    registration_fee = MoneySerializerField(required=False, allow_null=True)
    materials_fee = MoneySerializerField(required=False, allow_null=True)
    year_groups = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False, max_length=20
    )
    service_name = serializers.CharField(source="service.name", read_only=True)
    subject_name = serializers.SerializerMethodField()
    classes_count = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            "id",
            "name",
            "description",
            "public_description",
            "service",
            "service_name",
            "subject",
            "subject_name",
            "level",
            "min_age",
            "max_age",
            "year_groups",
            "prerequisites",
            "duration_weeks",
            "duration_sessions",
            "delivery_mode",
            "default_capacity",
            "pricing_model",
            "currency",
            "price",
            "instalments",
            "deposit",
            "registration_fee",
            "materials_fee",
            "tax_rate",
            "image",
            "is_public",
            "archived_at",
            "classes_count",
            "created_at",
        ]
        read_only_fields = ["id", "currency", "archived_at", "created_at"]

    @extend_schema_field(serializers.CharField())
    def get_subject_name(self, obj: Course) -> str:
        return obj.subject.name if obj.subject else ""

    @extend_schema_field(serializers.IntegerField())
    def get_classes_count(self, obj: Course) -> int:
        return obj.classes.exclude(status="cancelled").count()


class ArchiveSerializer(serializers.Serializer):
    archived = serializers.BooleanField()


# --- classes ------------------------------------------------------------------------------------


class ClassTeacherSerializer(BaseModelSerializer):
    tutor = TenantRelatedField(TutorProfile)
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)
    pay_per_session = MoneySerializerField(required=False, allow_null=True)

    class Meta:
        model = ClassTeacher
        fields = ["tutor", "tutor_name", "role", "pay_per_session"]
        field_permissions = {"pay_per_session": "people.tutor.view_financial"}


class TeacherInputSerializer(serializers.Serializer):
    tutor = TenantRelatedField(TutorProfile)
    role = serializers.ChoiceField(choices=ClassTeacher.Role.choices, default="lead")
    pay_per_session = MoneySerializerField(required=False, allow_null=True)


class GroupClassSerializer(BaseModelSerializer):
    course_name = serializers.CharField(source="course.name", read_only=True)
    term_name = serializers.CharField(source="term.name", read_only=True)
    location_name = serializers.SerializerMethodField()
    room_name = serializers.SerializerMethodField()
    teachers = ClassTeacherSerializer(many=True, read_only=True)
    enrolled = serializers.SerializerMethodField()
    places_left = serializers.SerializerMethodField()
    waiting = serializers.SerializerMethodField()
    weekdays = serializers.SerializerMethodField()
    year_groups = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = GroupClass
        fields = [
            "id",
            "branch",
            "course",
            "course_name",
            "term",
            "term_name",
            "name",
            "rrule",
            "weekdays",
            "start_date",
            "end_date",
            "start_time",
            "duration_minutes",
            "timezone",
            "location",
            "location_name",
            "room",
            "room_name",
            "online",
            "capacity",
            "min_size",
            "status",
            "waitlist_enabled",
            "min_age",
            "max_age",
            "year_groups",
            "teacher_pay_mode",
            "teacher_pay",
            "is_public",
            "next_class",
            "teachers",
            "enrolled",
            "places_left",
            "waiting",
            "cancelled_at",
            "cancel_reason",
            "created_at",
        ]
        read_only_fields = fields
        field_permissions = {"teacher_pay": "people.tutor.view_financial"}

    @extend_schema_field(serializers.CharField())
    def get_location_name(self, obj: GroupClass) -> str:
        return obj.location.name if obj.location else ""

    @extend_schema_field(serializers.CharField())
    def get_room_name(self, obj: GroupClass) -> str:
        return obj.room.name if obj.room else ""

    @extend_schema_field(serializers.IntegerField())
    def get_enrolled(self, obj: GroupClass) -> int:
        return selectors.active_count(obj)

    @extend_schema_field(serializers.IntegerField())
    def get_places_left(self, obj: GroupClass) -> int:
        return selectors.places_left(obj)

    @extend_schema_field(serializers.IntegerField())
    def get_waiting(self, obj: GroupClass) -> int:
        return selectors.waiting(obj).filter(status="waiting").count()

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField()))
    def get_weekdays(self, obj: GroupClass) -> list[int]:
        return selectors.meeting_days(obj)


class TeacherPayTierSerializer(serializers.Serializer):
    from_students = serializers.IntegerField(min_value=0)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)


class TeacherPaySerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    tiers = TeacherPayTierSerializer(many=True, required=False)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        value = super().to_internal_value(data)
        out: dict[str, Any] = {}
        if value.get("amount") is not None:
            out["amount"] = str(value["amount"])
        if value.get("tiers"):
            out["tiers"] = [
                {"from": t["from_students"], "amount": str(t["amount"])} for t in value["tiers"]
            ]
        return out


class _ClassFields(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    capacity = serializers.IntegerField(min_value=1, required=False)
    min_size = serializers.IntegerField(min_value=0, required=False)
    location = TenantRelatedField(Location, required=False, allow_null=True)
    room = TenantRelatedField(Room, required=False, allow_null=True)
    online = serializers.BooleanField(required=False)
    waitlist_enabled = serializers.BooleanField(required=False)
    min_age = serializers.IntegerField(min_value=0, max_value=120, required=False, allow_null=True)
    max_age = serializers.IntegerField(min_value=0, max_value=120, required=False, allow_null=True)
    year_groups = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False, max_length=20
    )
    teacher_pay_mode = serializers.ChoiceField(
        choices=GroupClass.TeacherPay.choices, required=False
    )
    teacher_pay = TeacherPaySerializer(required=False)
    is_public = serializers.BooleanField(required=False)
    next_class = TenantRelatedField(GroupClass, required=False, allow_null=True)
    teachers = TeacherInputSerializer(many=True, required=False)
    start_time = serializers.TimeField(required=False)
    duration_minutes = serializers.IntegerField(min_value=5, max_value=720, required=False)
    rrule = serializers.CharField(max_length=300, required=False)


class GroupClassCreateSerializer(_ClassFields):
    course = TenantRelatedField(Course)
    term = TenantRelatedField(Term)
    start_time = serializers.TimeField()
    duration_minutes = serializers.IntegerField(min_value=5, max_value=720)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    status = serializers.ChoiceField(
        choices=[("draft", "draft"), ("open", "open")], default="draft"
    )
    conflict_mode = serializers.ChoiceField(
        choices=[("skip", "skip"), ("create", "create"), ("fail", "fail")], default="skip"
    )


class GroupClassUpdateSerializer(_ClassFields):
    name = serializers.CharField(max_length=150, required=False)


class ClassCreatedSerializer(serializers.Serializer):
    group_class = GroupClassSerializer()
    skipped_dates = serializers.ListField(child=serializers.DateField())


class ClassCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class RosterRowSerializer(serializers.Serializer):
    enrolment = serializers.UUIDField()
    student = serializers.UUIDField()
    student_name = serializers.CharField()
    client = serializers.UUIDField()
    client_name = serializers.CharField()
    status = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField(allow_null=True)
    joined_via = serializers.CharField()


class WaitlistRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    student = serializers.UUIDField()
    student_name = serializers.CharField()
    status = serializers.CharField()
    position = serializers.IntegerField(allow_null=True)
    offer_expires_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class JoinWaitlistSerializer(serializers.Serializer):
    student = TenantRelatedField(Student)
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


# --- sessions, registers and makeups ------------------------------------------------------------


class ClassSessionSerializer(BaseModelSerializer):
    start = serializers.DateTimeField(source="lesson.start", read_only=True)
    end = serializers.DateTimeField(source="lesson.end", read_only=True)
    lesson_status = serializers.CharField(source="lesson.status", read_only=True)
    class_name = serializers.CharField(source="group_class.name", read_only=True)
    course_name = serializers.CharField(source="group_class.course.name", read_only=True)
    attendees = serializers.SerializerMethodField()

    class Meta:
        model = ClassSession
        fields = [
            "id",
            "group_class",
            "class_name",
            "course_name",
            "lesson",
            "number",
            "date",
            "start",
            "end",
            "lesson_status",
            "attendees",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.IntegerField())
    def get_attendees(self, obj: ClassSession) -> int:
        return obj.lesson.attendees.count()


class RegisterRowSerializer(serializers.Serializer):
    student = serializers.UUIDField()
    student_name = serializers.CharField(read_only=True)
    outcome = serializers.ChoiceField(
        choices=[
            "present",
            "late",
            "absent_notified",
            "no_show",
            "cancelled_client",
            "cancelled_tutor",
            "cancelled_admin",
        ]
    )
    late_minutes = serializers.IntegerField(
        min_value=0, max_value=600, required=False, allow_null=True
    )
    absence_reason = serializers.CharField(max_length=200, required=False, allow_blank=True)
    makeup = serializers.BooleanField(read_only=True)


class RegisterSerializer(serializers.Serializer):
    session = serializers.UUIDField(read_only=True)
    lesson_status = serializers.CharField(read_only=True)
    rows = RegisterRowSerializer(many=True)


class RegisterInputSerializer(serializers.Serializer):
    rows = RegisterRowSerializer(many=True)


class MakeupCreateSerializer(serializers.Serializer):
    student = TenantRelatedField(Student)
    from_session = TenantRelatedField(ClassSession, required=False, allow_null=True)
    makeup_credit = serializers.UUIDField(required=False, allow_null=True)


class MakeupBookingSerializer(BaseModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)

    class Meta:
        model = MakeupBooking
        fields = [
            "id",
            "session",
            "student",
            "student_name",
            "from_session",
            "makeup_credit_id",
            "status",
            "created_at",
        ]
        read_only_fields = fields


# --- enrolments ---------------------------------------------------------------------------------


class EnrolmentSerializer(BaseModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    class_name = serializers.CharField(source="group_class.name", read_only=True)
    course_name = serializers.CharField(source="group_class.course.name", read_only=True)
    fee = MoneySerializerField(read_only=True)

    class Meta:
        model = Enrolment
        fields = [
            "id",
            "group_class",
            "class_name",
            "course_name",
            "student",
            "student_name",
            "client",
            "client_name",
            "status",
            "source",
            "start_date",
            "end_date",
            "fee",
            "price_snapshot",
            "billing_plan_id",
            "payment",
            "payment_request_id",
            "hold_expires_at",
            "withdrawn_at",
            "withdrawal_reason",
            "created_at",
        ]
        read_only_fields = fields


class EnrolmentCreateSerializer(serializers.Serializer):
    group_class = TenantRelatedField(GroupClass)
    student = TenantRelatedField(Student)
    start_date = serializers.DateField(required=False, allow_null=True)
    trial = serializers.BooleanField(default=False)
    override_capacity = serializers.BooleanField(default=False)
    skip_eligibility = serializers.BooleanField(default=False)


class EnrolmentCreatedSerializer(EnrolmentSerializer):
    pay_url = serializers.SerializerMethodField()

    class Meta(EnrolmentSerializer.Meta):
        fields = [*EnrolmentSerializer.Meta.fields, "pay_url"]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_pay_url(self, obj: Enrolment) -> str:
        from .. import services

        return getattr(obj, "pay_url", "") or services.pay_url(obj)


class QuoteInputSerializer(serializers.Serializer):
    group_class = TenantRelatedField(GroupClass)
    student = TenantRelatedField(Student, required=False, allow_null=True)
    start_date = serializers.DateField(required=False, allow_null=True)
    trial = serializers.BooleanField(default=False)


class DiscountLineSerializer(serializers.Serializer):
    name = serializers.CharField()
    amount = MoneyOut()


class UnitsSerializer(serializers.Serializer):
    basis = serializers.CharField()
    total = serializers.IntegerField()
    remaining = serializers.IntegerField()


class QuoteSerializer(serializers.Serializer):
    list_price = MoneyOut()
    price = MoneyOut()
    discounts = DiscountLineSerializer(many=True)
    pricing_model = serializers.CharField()
    start_date = serializers.DateField()
    fee_due = MoneyOut()
    units = UnitsSerializer()
    instalments = serializers.IntegerField()
    registration_fee = MoneyOut()
    materials_fee = MoneyOut()
    due_now = MoneyOut()
    deposit = MoneyOut(allow_null=True)
    problems = serializers.ListField(child=serializers.CharField(), required=False)


class WithdrawSerializer(serializers.Serializer):
    effective_date = serializers.DateField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    refund = serializers.BooleanField(required=False, allow_null=True, default=None)


class TransferSerializer(serializers.Serializer):
    to_class = TenantRelatedField(GroupClass)
    effective_date = serializers.DateField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    override_capacity = serializers.BooleanField(default=False)


class EnrolmentTransferSerializer(BaseModelSerializer):
    class Meta:
        model = EnrolmentTransfer
        fields = [
            "id",
            "from_enrolment",
            "to_enrolment",
            "effective_date",
            "reason",
            "adjustment",
            "created_at",
        ]
        read_only_fields = fields


# --- rollover -----------------------------------------------------------------------------------


class RolloverOfferSerializer(BaseModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    from_class_name = serializers.CharField(source="enrolment.group_class.name", read_only=True)
    to_class_name = serializers.CharField(source="to_class.name", read_only=True)
    course_name = serializers.CharField(source="to_class.course.name", read_only=True)

    class Meta:
        model = RolloverOffer
        fields = [
            "id",
            "student",
            "student_name",
            "enrolment",
            "from_class_name",
            "to_class",
            "to_class_name",
            "course_name",
            "status",
            "responded_at",
            "reminded_at",
            "new_enrolment",
            "note",
        ]
        read_only_fields = fields


class TermRolloverSerializer(BaseModelSerializer):
    from_term_name = serializers.CharField(source="from_term.name", read_only=True)
    to_term_name = serializers.CharField(source="to_term.name", read_only=True)
    counts = serializers.SerializerMethodField()

    class Meta:
        model = TermRollover
        fields = [
            "id",
            "from_term",
            "from_term_name",
            "to_term",
            "to_term_name",
            "mode",
            "deadline",
            "status",
            "stats",
            "counts",
            "workflow_id",
            "finalised_at",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.DictField(child=serializers.IntegerField()))
    def get_counts(self, obj: TermRollover) -> dict[str, int]:
        from django.db.models import Count

        rows = obj.offers.values("status").annotate(n=Count("id"))
        return {r["status"]: r["n"] for r in rows}


class RolloverStartSerializer(serializers.Serializer):
    from_term = TenantRelatedField(Term)
    to_term = TenantRelatedField(Term)
    mode = serializers.ChoiceField(choices=TermRollover.Mode.choices, default="confirm")
    deadline = serializers.DateTimeField()


# --- public catalogue and online enrolment ------------------------------------------------------


class PublicCourseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    subject = serializers.CharField()
    level = serializers.CharField()
    image_url = serializers.CharField()
    prerequisites = serializers.CharField()
    delivery_mode = serializers.CharField()


class PublicClassSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    course = PublicCourseSerializer()
    term = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    weekdays = serializers.ListField(child=serializers.IntegerField())
    start_time = serializers.CharField()
    duration_minutes = serializers.IntegerField()
    location = serializers.CharField()
    online = serializers.BooleanField()
    min_age = serializers.IntegerField(allow_null=True)
    max_age = serializers.IntegerField(allow_null=True)
    year_groups = serializers.ListField(child=serializers.CharField())
    pricing_model = serializers.CharField()
    pricing_label = serializers.CharField()
    price = serializers.CharField()
    price_amount = serializers.CharField()
    currency = serializers.CharField()
    places_left = serializers.IntegerField()
    capacity = serializers.IntegerField()
    full = serializers.BooleanField()
    waitlist = serializers.BooleanField()


class PublicCatalogueSerializer(serializers.Serializer):
    classes = PublicClassSerializer(many=True)
    terms = serializers.CharField(allow_blank=True)
    payment = serializers.CharField()


class PublicContactSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")


class PublicStudentSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    year_group = serializers.CharField(max_length=40, required=False, allow_blank=True)


class PublicEnrolSerializer(serializers.Serializer):
    group_class = serializers.UUIDField()
    contact = PublicContactSerializer()
    student = PublicStudentSerializer()
    accept_terms = serializers.BooleanField(default=False)
    join_waitlist = serializers.BooleanField(default=False)
    captcha = serializers.CharField(required=False, allow_blank=True)


class PublicEnrolmentSerializer(serializers.Serializer):
    id = serializers.UUIDField(allow_null=True)
    status = serializers.CharField()
    class_name = serializers.CharField()
    course_name = serializers.CharField()
    student = serializers.CharField()
    start_date = serializers.DateField(allow_null=True)
    pay_url = serializers.CharField(allow_blank=True)
    hold_expires_at = serializers.DateTimeField(allow_null=True)
    token = serializers.CharField(required=False, allow_blank=True)
    waitlist_position = serializers.IntegerField(required=False, allow_null=True)


class RolloverPageSerializer(serializers.Serializer):
    student = serializers.CharField()
    course_name = serializers.CharField()
    class_name = serializers.CharField()
    term = serializers.CharField()
    starts = serializers.DateField()
    start_time = serializers.CharField()
    status = serializers.CharField()
    deadline = serializers.DateTimeField()
    mode = serializers.CharField()
    open = serializers.BooleanField()


class RolloverAnswerSerializer(serializers.Serializer):
    confirm = serializers.BooleanField()


# --- portal -------------------------------------------------------------------------------------


class PortalEnrolSerializer(serializers.Serializer):
    group_class = serializers.UUIDField()
    student = serializers.UUIDField()
    accept_terms = serializers.BooleanField(default=False)
    join_waitlist = serializers.BooleanField(default=False)


class PortalEnrolmentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    group_class = serializers.UUIDField()
    class_name = serializers.CharField()
    course_name = serializers.CharField()
    term = serializers.CharField()
    student = serializers.UUIDField()
    student_name = serializers.CharField()
    status = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField(allow_null=True)
    weekdays = serializers.ListField(child=serializers.IntegerField())
    start_time = serializers.CharField()
    pay_url = serializers.CharField(allow_blank=True)
    hold_expires_at = serializers.DateTimeField(allow_null=True)


class PortalWaitlistSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    group_class = serializers.UUIDField()
    class_name = serializers.CharField()
    course_name = serializers.CharField()
    student_name = serializers.CharField()
    status = serializers.CharField()
    position = serializers.IntegerField(allow_null=True)
    offer_expires_at = serializers.DateTimeField(allow_null=True)


class PortalRolloverOfferSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    student_name = serializers.CharField()
    course_name = serializers.CharField()
    class_name = serializers.CharField()
    term = serializers.CharField()
    status = serializers.CharField()
    deadline = serializers.DateTimeField()
    mode = serializers.CharField()


class PortalCoursesSerializer(serializers.Serializer):
    enrolments = PortalEnrolmentSerializer(many=True)
    waitlist = PortalWaitlistSerializer(many=True)
    rollover_offers = PortalRolloverOfferSerializer(many=True)
