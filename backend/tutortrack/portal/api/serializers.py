from __future__ import annotations

from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer, MoneyOut, TenantRelatedField
from tutortrack.people.models import Contact, Student
from tutortrack.tenancy.models import Branch

from ..models import Announcement


class NamedRef(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()


class PortalOrgSerializer(serializers.Serializer):
    name = serializers.CharField()
    primary_colour = serializers.CharField(allow_blank=True)


class PortalFeaturesSerializer(serializers.Serializer):
    cancellations = serializers.BooleanField()
    absence = serializers.BooleanField()
    invoices = serializers.BooleanField()
    reports = serializers.BooleanField()
    profile = serializers.BooleanField()


class PortalMeSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["client", "student"])
    organisation = PortalOrgSerializer()
    clients = NamedRef(many=True)
    students = NamedRef(many=True)
    features = PortalFeaturesSerializer()
    welcome_text = serializers.CharField(allow_blank=True)
    help_url = serializers.CharField(allow_blank=True)
    terms_url = serializers.CharField(allow_blank=True)


class PortalTutorSerializer(serializers.Serializer):
    name = serializers.CharField()
    email = serializers.CharField(allow_blank=True)
    phone = serializers.CharField(allow_blank=True)


class PortalAttendeeSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    outcome = serializers.CharField(allow_blank=True)


class PortalLessonSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    timezone = serializers.CharField()
    status = serializers.CharField()
    online = serializers.BooleanField()
    meeting_url = serializers.CharField(allow_blank=True)
    location = serializers.CharField(allow_blank=True)
    notes_for_client = serializers.CharField(allow_blank=True)
    tutors = PortalTutorSerializer(many=True)
    students = PortalAttendeeSerializer(many=True)


class AnswerSerializer(serializers.Serializer):
    label = serializers.CharField()  # type: ignore[assignment]
    type = serializers.CharField()
    value = serializers.JSONField()


class PortalCommentSerializer(serializers.Serializer):
    author = serializers.CharField()
    body = serializers.CharField()
    created_at = serializers.DateTimeField()


class PortalReportSerializer(serializers.Serializer):
    id = serializers.CharField()
    lesson_title = serializers.CharField()
    lesson_start = serializers.DateTimeField()
    tutor_name = serializers.CharField()
    shared_at = serializers.DateTimeField()
    answers = AnswerSerializer(many=True)
    comments = PortalCommentSerializer(many=True)


class NewsSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    published_at = serializers.DateTimeField()


class DashboardSerializer(serializers.Serializer):
    next_lesson = PortalLessonSerializer(allow_null=True)
    upcoming = PortalLessonSerializer(many=True)
    reports = PortalReportSerializer(many=True)
    announcements = NewsSerializer(many=True)
    amount_due = MoneyOut(allow_null=True)
    credit = MoneyOut(allow_null=True)


class PortalCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class PortalCancelResultSerializer(serializers.Serializer):
    kind = serializers.CharField()
    charge_percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    message = serializers.CharField()
    makeup_credit = serializers.BooleanField()
    cancelled = serializers.BooleanField()


class AbsenceSerializer(serializers.Serializer):
    student = serializers.UUIDField()
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class ReportReplySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=5000)


class BalancesOut(serializers.Serializer):
    currency = serializers.CharField()
    invoice_balance = MoneyOut()
    available_credit = MoneyOut()
    overdue = MoneyOut()


class AccountSerializer(serializers.Serializer):
    client = serializers.CharField()
    name = serializers.CharField()
    balances = BalancesOut()
    auto_pay = serializers.BooleanField()


class PortalInvoiceSerializer(serializers.Serializer):
    id = serializers.CharField()
    number = serializers.CharField()
    status = serializers.CharField()
    issue_date = serializers.DateField(allow_null=True)
    due_date = serializers.DateField(allow_null=True)
    total = MoneyOut()
    balance_due = MoneyOut()
    pay_token = serializers.CharField(allow_blank=True)
    pdf_token = serializers.CharField(allow_blank=True)


class PortalRequestSerializer(serializers.Serializer):
    id = serializers.CharField()
    number = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    amount = MoneyOut()
    pay_token = serializers.CharField()


class PortalCreditNoteSerializer(serializers.Serializer):
    id = serializers.CharField()
    number = serializers.CharField()
    invoice_number = serializers.CharField()
    total = MoneyOut()
    issued_at = serializers.DateTimeField()


class PortalBillingSerializer(serializers.Serializer):
    accounts = AccountSerializer(many=True)
    invoices = PortalInvoiceSerializer(many=True)
    payment_requests = PortalRequestSerializer(many=True)
    credit_notes = PortalCreditNoteSerializer(many=True)


class PortalMethodSerializer(serializers.Serializer):
    id = serializers.CharField()
    type = serializers.CharField()
    brand = serializers.CharField(allow_blank=True)
    last4 = serializers.CharField(allow_blank=True)
    exp_month = serializers.IntegerField(allow_null=True)
    exp_year = serializers.IntegerField(allow_null=True)
    is_default = serializers.BooleanField()


class PortalMethodsSerializer(serializers.Serializer):
    auto_pay = serializers.BooleanField()
    consent_given_at = serializers.DateTimeField(allow_null=True)
    methods = PortalMethodSerializer(many=True)


class PortalMethodActionSerializer(serializers.Serializer):
    client = serializers.UUIDField()
    action = serializers.ChoiceField(choices=["add", "default", "remove", "autopay_off"])
    method = serializers.UUIDField(required=False, allow_null=True)


class PortalSetupSerializer(serializers.Serializer):
    url = serializers.CharField(allow_blank=True)


class PortalContactSerializer(BaseModelSerializer):
    class Meta:
        model = Contact
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "mobile",
            "receives_reminders",
            "receives_invoices",
            "receives_reports",
            "receives_marketing",
        ]
        read_only_fields = ["id", "email"]


class PortalStudentSerializer(BaseModelSerializer):
    class Meta:
        model = Student
        fields = ["id", "first_name", "last_name", "preferred_name", "school", "year_group",
                  "learning_needs"]  # fmt: skip
        read_only_fields = ["id", "first_name", "last_name"]


class PortalProfileSerializer(serializers.Serializer):
    contacts = PortalContactSerializer(many=True)
    students = PortalStudentSerializer(many=True)


class AnnouncementSerializer(BaseModelSerializer):
    branch = TenantRelatedField(Branch, required=False, allow_null=True)

    class Meta:
        model = Announcement
        fields = ["id", "title", "body", "audience", "branch", "published_at", "expires_at"]
        read_only_fields = ["id"]
        extra_kwargs = {"published_at": {"required": False}}


class InviteSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True, default="")


class InviteResultSerializer(serializers.Serializer):
    email = serializers.EmailField()
    expires_at = serializers.DateTimeField()


# --- tutor portal (E16) ---------------------------------------------------------------------


class TutorMeSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    email = serializers.CharField()
    can_cancel = serializers.BooleanField()
    can_edit_lessons = serializers.BooleanField()
    can_see_pay = serializers.BooleanField()


class TutorDayLessonSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    status = serializers.CharField()
    online = serializers.BooleanField()
    meeting_url = serializers.CharField(allow_blank=True)
    location = serializers.CharField(allow_blank=True)
    students = serializers.ListField(child=serializers.CharField())


class TutorTodaySerializer(serializers.Serializer):
    date = serializers.DateField()
    lessons = TutorDayLessonSerializer(many=True)
    reports_due = serializers.IntegerField()
    offers = serializers.IntegerField()
    unread = serializers.IntegerField()
    earnings_this_month = MoneyOut()


class TutorStudentSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    year_group = serializers.CharField(allow_blank=True)
    jobs = serializers.ListField(child=serializers.CharField())
    next_lesson = serializers.DateTimeField(allow_null=True)


class EarningLineSerializer(serializers.Serializer):
    lesson = serializers.CharField()
    title = serializers.CharField()
    start = serializers.DateTimeField()
    status = serializers.CharField()
    pay = MoneyOut()


class TutorEarningsSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    lessons = EarningLineSerializer(many=True)
    total = MoneyOut()
