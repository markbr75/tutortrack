from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer, MoneySerializerField
from tutortrack.matching.api.serializers import PublicTutorCardSerializer

from .. import forms
from ..models import (
    AssignmentRule,
    Enquiry,
    EnquiryStageHistory,
    Form,
    FormSubmission,
    Pipeline,
    PipelineStage,
    Proposal,
    WaitlistEntry,
)


class StageSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)

    class Meta:
        model = PipelineStage
        fields = ["id", "name", "order", "kind", "probability", "sla_hours", "colour"]
        read_only_fields = ["order"]


class PipelineSerializer(serializers.ModelSerializer):
    stages = StageSerializer(many=True)

    class Meta:
        model = Pipeline
        fields = ["id", "name", "is_default", "active", "stages"]


class EnquirySubjectSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=100)
    level = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class EnquirySerializer(BaseModelSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    contact_name = serializers.SerializerMethodField()
    contact_email = serializers.CharField(source="contact.email", read_only=True, default="")
    contact_phone = serializers.CharField(source="contact.phone", read_only=True, default="")
    stage_name = serializers.CharField(source="stage.name", read_only=True)
    owner_name = serializers.SerializerMethodField()
    student_names = serializers.SerializerMethodField()
    age_hours = serializers.SerializerMethodField()
    sla_breached = serializers.SerializerMethodField()

    class Meta:
        model = Enquiry
        fields = [
            "id",
            "title",
            "client",
            "client_name",
            "contact",
            "contact_name",
            "contact_email",
            "contact_phone",
            "students",
            "student_names",
            "pipeline",
            "stage",
            "stage_name",
            "stage_entered_at",
            "status",
            "owner",
            "owner_name",
            "priority",
            "subjects",
            "notes",
            "value_estimate",
            "expected_start",
            "source",
            "source_detail",
            "utm",
            "first_response_at",
            "sla_breached",
            "lost_reason",
            "lost_note",
            "won_at",
            "lost_at",
            "trial_lesson",
            "trial_outcome",
            "trial_feedback",
            "converted_job_ids",
            "created_at",
            "age_hours",
        ]
        read_only_fields = fields

    def get_contact_name(self, obj: Enquiry) -> str:
        c = obj.contact
        return f"{c.first_name} {c.last_name}".strip() if c else ""

    def get_owner_name(self, obj: Enquiry) -> str:
        return (obj.owner.get_full_name() or obj.owner.email) if obj.owner else ""

    def get_student_names(self, obj: Enquiry) -> list[str]:
        return [s.first_name for s in obj.students.all()]

    def get_age_hours(self, obj: Enquiry) -> int:
        from tutortrack.core.time import now

        return int((now() - obj.created_at).total_seconds() // 3600)

    def get_sla_breached(self, obj: Enquiry) -> bool:
        return obj.sla_breached_at is not None


class StudentInSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    subjects = EnquirySubjectSerializer(many=True, required=False)


class EnquiryCreateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    students = StudentInSerializer(many=True, required=False)
    subjects = EnquirySubjectSerializer(many=True, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    source = serializers.ChoiceField(  # type: ignore[assignment]
        choices=Enquiry.Source.choices, default=Enquiry.Source.PHONE
    )
    pipeline = serializers.UUIDField(required=False, allow_null=True)
    owner = serializers.UUIDField(required=False, allow_null=True)
    priority = serializers.ChoiceField(choices=Enquiry.Priority.choices, default="normal")
    value_estimate = MoneySerializerField(required=False, allow_null=True)
    expected_start = serializers.DateField(required=False, allow_null=True)


class EnquiryUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    owner = serializers.UUIDField(required=False, allow_null=True)
    priority = serializers.ChoiceField(choices=Enquiry.Priority.choices, required=False)
    subjects = EnquirySubjectSerializer(many=True, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    value_estimate = MoneySerializerField(required=False, allow_null=True)
    expected_start = serializers.DateField(required=False, allow_null=True)


class MoveSerializer(serializers.Serializer):
    stage = serializers.UUIDField()


class LoseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=60)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    nurture = serializers.BooleanField(default=False)


class TrialSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    service = serializers.UUIDField()
    tutor = serializers.UUIDField(required=False, allow_null=True)
    price = MoneySerializerField(required=False, allow_null=True, help_text="0 for a free trial")


class TrialOutcomeSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=Enquiry.TrialOutcome.choices)
    feedback = serializers.CharField(required=False, allow_blank=True)


class ConvertJobSerializer(serializers.Serializer):
    service = serializers.UUIDField()
    tutor = serializers.UUIDField(required=False, allow_null=True)
    students = serializers.ListField(child=serializers.UUIDField(), required=False)


class ConvertSerializer(serializers.Serializer):
    jobs = ConvertJobSerializer(many=True)
    invite_to_portal = serializers.BooleanField(default=False)
    payment_setup_link = serializers.BooleanField(default=False)


class ConvertResultSerializer(serializers.Serializer):
    enquiry = EnquirySerializer()
    job_ids = serializers.ListField(child=serializers.UUIDField())
    setup_url = serializers.CharField(allow_blank=True)
    invited = serializers.BooleanField()


class StageHistorySerializer(serializers.ModelSerializer):
    from_stage_name = serializers.CharField(source="from_stage.name", default=None)
    to_stage_name = serializers.CharField(source="to_stage.name")

    class Meta:
        model = EnquiryStageHistory
        fields = ["id", "from_stage_name", "to_stage_name", "seconds_in_previous", "created_at"]


class BoardColumnSerializer(serializers.Serializer):
    stage = StageSerializer()
    enquiries = EnquirySerializer(many=True)


class AssignmentRuleSerializer(serializers.ModelSerializer):
    owners = serializers.ListField(child=serializers.UUIDField())

    class Meta:
        model = AssignmentRule
        fields = ["id", "pipeline", "branch", "subject", "owners", "order", "active"]


class FormSerializer(serializers.ModelSerializer):
    class Meta:
        model = Form
        fields = ["id", "type", "name", "slug", "schema", "settings", "published", "branch"]

    def validate_schema(self, value: Any) -> Any:
        return forms.clean_schema(value)


class FormSubmissionSerializer(serializers.ModelSerializer):
    """A form submission (G6, public API ``enquiries`` scope). The visitor's IP address and
    browser stay out of the API."""

    form_name = serializers.CharField(source="form.name", default="", read_only=True)
    answers = serializers.JSONField(source="data", read_only=True)

    class Meta:
        model = FormSubmission
        fields = ["id", "form", "form_name", "answers", "utm", "created_records", "spam",
                  "created_at"]  # fmt: skip
        read_only_fields = fields


class PublicFormSerializer(serializers.Serializer):
    name = serializers.CharField()
    type = serializers.CharField()
    schema = serializers.DictField()
    thank_you = serializers.CharField(allow_blank=True)
    redirect_url = serializers.CharField(allow_blank=True)
    consent_text = serializers.CharField(allow_blank=True)
    turnstile_site_key = serializers.CharField(allow_blank=True)
    organisation = serializers.CharField()


class PublicSubmitSerializer(serializers.Serializer):
    data = serializers.DictField()  # type: ignore[assignment]
    utm = serializers.DictField(required=False, default=dict)
    captcha_token = serializers.CharField(required=False, allow_blank=True, default="")
    website = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="Honeypot: leave empty"
    )


class PublicSubmitResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    pay_url = serializers.CharField(allow_blank=True)


class PublicEnquirySerializer(serializers.Serializer):
    """``POST /public/enquiries`` (TutorCruncher-style API)."""

    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    students = StudentInSerializer(many=True, required=False)
    subjects = EnquirySubjectSerializer(many=True, required=False)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    postcode = serializers.CharField(required=False, allow_blank=True, max_length=20)
    utm = serializers.DictField(required=False, default=dict)
    captcha_token = serializers.CharField(required=False, allow_blank=True, default="")
    website = serializers.CharField(required=False, allow_blank=True, default="")


class WaitlistEntrySerializer(BaseModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    position = serializers.SerializerMethodField()

    class Meta:
        model = WaitlistEntry
        fields = [
            "id",
            "student",
            "student_name",
            "subject",
            "level",
            "tutor",
            "service",
            "notes",
            "status",
            "offer_details",
            "offered_at",
            "offer_expires_at",
            "responded_at",
            "created_at",
            "position",
            "group_class_id",
        ]
        read_only_fields = [
            "group_class_id",
            "status",
            "offer_details",
            "offered_at",
            "offer_expires_at",
            "responded_at",
            "created_at",
        ]

    def get_position(self, obj: WaitlistEntry) -> int | None:
        from .. import services

        return services.position(obj) if obj.status == WaitlistEntry.Status.WAITING else None


class OfferSerializer(serializers.Serializer):
    details = serializers.CharField(max_length=500)
    hours = serializers.IntegerField(required=False, min_value=1, max_value=336)


class PublicOfferSerializer(serializers.Serializer):
    student = serializers.CharField()
    subject = serializers.CharField()
    details = serializers.CharField()
    status = serializers.CharField()
    expires_at = serializers.DateTimeField(allow_null=True)
    organisation = serializers.CharField()


class OfferResponseSerializer(serializers.Serializer):
    accept = serializers.BooleanField()


class FunnelStageSerializer(serializers.Serializer):
    stage = serializers.CharField()
    kind = serializers.CharField()
    reached = serializers.IntegerField()
    rate = serializers.FloatField()


class BreakdownSerializer(serializers.Serializer):
    key = serializers.CharField(allow_blank=True)
    total = serializers.IntegerField()
    won = serializers.IntegerField()


class FunnelSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    stages = FunnelStageSerializer(many=True)
    win_rate = serializers.FloatField()
    first_response_hours = serializers.FloatField(allow_null=True)
    by_source = BreakdownSerializer(many=True)
    by_owner = BreakdownSerializer(many=True)
    lost_reasons = serializers.ListField(child=serializers.DictField())
    won_value = serializers.DictField(child=serializers.CharField())


# --- proposals (E17-T09) --------------------------------------------------------------------

PROPOSAL_STATES = [c for c, _label in Proposal.Status.choices]


class ProposalLineSerializer(serializers.Serializer):
    service = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    quantity = serializers.DecimalField(max_digits=8, decimal_places=2, coerce_to_string=True)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=True)
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, coerce_to_string=True
    )


class ProposalSerializer(serializers.ModelSerializer):
    lines = ProposalLineSerializer(many=True)
    tutors = serializers.ListField(child=serializers.UUIDField(), read_only=True)
    job_ids = serializers.ListField(child=serializers.UUIDField(), read_only=True)
    total = MoneySerializerField(read_only=True)
    deposit = MoneySerializerField(read_only=True, allow_null=True)
    state = serializers.SerializerMethodField()
    link = serializers.SerializerMethodField()
    contact_name = serializers.SerializerMethodField()
    chosen_tutor_name = serializers.SerializerMethodField()

    class Meta:
        model = Proposal
        fields = [
            "id",
            "enquiry",
            "number",
            "title",
            "contact",
            "contact_name",
            "status",
            "state",
            "introduction",
            "schedule",
            "terms",
            "lines",
            "tutors",
            "currency",
            "total",
            "deposit",
            "valid_days",
            "sent_at",
            "expires_at",
            "viewed_at",
            "responded_at",
            "accepted_name",
            "chosen_tutor",
            "chosen_tutor_name",
            "decline_reason",
            "payment_request",
            "job_ids",
            "link",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ChoiceField(choices=PROPOSAL_STATES))
    def get_state(self, obj: Proposal) -> str:
        from ..proposals import state

        return state(obj)

    @extend_schema_field(serializers.CharField())
    def get_link(self, obj: Proposal) -> str:
        """The family's link while the proposal is open."""
        from tutortrack.comms.catalogue import tenant_link

        from ..proposals import state, token_for

        if state(obj) != Proposal.Status.SENT:
            return ""
        return tenant_link(f"/proposals/{token_for(obj)}")

    @extend_schema_field(serializers.CharField())
    def get_contact_name(self, obj: Proposal) -> str:
        return obj.contact.full_name if obj.contact is not None else ""

    @extend_schema_field(serializers.CharField())
    def get_chosen_tutor_name(self, obj: Proposal) -> str:
        return obj.chosen_tutor.full_name if obj.chosen_tutor is not None else ""


class ProposalWriteSerializer(serializers.Serializer):
    enquiry = serializers.UUIDField(required=False)
    title = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    contact = serializers.UUIDField(required=False, allow_null=True)
    introduction = serializers.CharField(required=False, allow_blank=True, default="")
    schedule = serializers.CharField(required=False, allow_blank=True, default="")
    terms = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    lines = ProposalLineSerializer(many=True, required=False, default=list)
    tutors = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True, default="")
    deposit = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, default=None
    )
    valid_days = serializers.IntegerField(
        min_value=1, max_value=90, required=False, allow_null=True, default=None
    )


class PublicProposalLineSerializer(serializers.Serializer):
    description = serializers.CharField()
    quantity = serializers.CharField()
    unit_price = serializers.CharField()
    amount = serializers.CharField()


class PublicProposalSerializer(serializers.Serializer):
    organisation = serializers.CharField()
    number = serializers.CharField()
    title = serializers.CharField()
    status = serializers.ChoiceField(choices=PROPOSAL_STATES)
    introduction = serializers.CharField(allow_blank=True)
    schedule = serializers.CharField(allow_blank=True)
    terms = serializers.CharField(allow_blank=True)
    lines = PublicProposalLineSerializer(many=True)
    currency = serializers.CharField()
    total = serializers.CharField()
    deposit = serializers.CharField(allow_null=True)
    expires_at = serializers.DateTimeField(allow_null=True)
    tutors = PublicTutorCardSerializer(many=True)
    chosen_tutor = serializers.UUIDField(allow_null=True)
    students = serializers.ListField(child=serializers.CharField())
    pay_url = serializers.CharField(allow_blank=True)


class ProposalAcceptSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    tutor = serializers.UUIDField(required=False, allow_null=True)


class ProposalDeclineSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
