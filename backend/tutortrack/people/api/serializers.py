from __future__ import annotations

from typing import Any

from rest_framework import serializers

from tutortrack.billing.models import InvoiceTemplate
from tutortrack.core.api.serializers import BaseModelSerializer, TenantRelatedField

from ..models import (
    Address,
    Client,
    Contact,
    Student,
    TutorProfile,
    TutorQualification,
    TutorSubject,
)


class AddressSerializer(BaseModelSerializer):
    class Meta:
        model = Address
        fields = ["line1", "line2", "city", "region", "postcode", "country", "lat", "lng"]
        read_only_fields = ["lat", "lng"]


class AddressInput(serializers.Serializer):
    line1 = serializers.CharField(max_length=200, required=False, allow_blank=True)
    line2 = serializers.CharField(max_length=200, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    region = serializers.CharField(max_length=100, required=False, allow_blank=True)
    postcode = serializers.CharField(max_length=20, required=False, allow_blank=True)
    country = serializers.CharField(max_length=2, required=False, allow_blank=True)


class SubjectInput(serializers.Serializer):
    """A subject by name, or chosen from the catalogue by ``subject_id``/``level_id``."""

    subject = serializers.CharField(max_length=100, required=False)
    level = serializers.CharField(max_length=100, required=False, allow_blank=True)
    subject_id = serializers.UUIDField(required=False, write_only=True)
    level_id = serializers.UUIDField(required=False, write_only=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("subject") and not attrs.get("subject_id") and not attrs.get("level_id"):
            raise serializers.ValidationError({"subject": ["Give a subject."]})
        return attrs


class ContactSerializer(BaseModelSerializer):
    address = AddressSerializer(read_only=True)
    address_input = AddressInput(write_only=True, required=False, source="address_data")
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Contact
        fields = [
            "id", "client", "first_name", "last_name", "full_name", "relationship", "email",
            "phone", "mobile", "preferred_contact_method", "address", "address_input",
            "use_client_address", "is_primary", "is_bill_payer", "receives_reminders",
            "receives_invoices", "receives_reports", "receives_marketing",
            "is_emergency_contact", "language", "user", "custom_fields", "created_at",
        ]  # fmt: skip
        read_only_fields = ["id", "client", "user", "created_at"]
        # Tutors see contact details only per the organisation's toggles (FR-03-6).
        field_permissions = {
            "phone": "people.contact.view_phone",
            "mobile": "people.contact.view_phone",
            "email": "people.contact.view_details",
            "address": "people.contact.view_details",
        }


def _figure(**kwargs: Any) -> Any:
    """A computed list field (FR-05-11): ``None`` when the viewer can't see that area."""
    return serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, allow_null=True, **kwargs
    )


def _moment() -> Any:
    return serializers.DateTimeField(read_only=True, allow_null=True)


class StudentSerializer(BaseModelSerializer):
    lesson_address = AddressSerializer(read_only=True)
    lesson_address_input = AddressInput(
        write_only=True, required=False, source="lesson_address_data"
    )
    full_name = serializers.CharField(read_only=True)
    subjects = SubjectInput(many=True, required=False)
    next_lesson_at = _moment()
    last_lesson_at = _moment()
    hours_this_term = _figure()
    merged_into = serializers.UUIDField(source="merged_into_id", read_only=True, allow_null=True)
    sen_tags = serializers.ListField(
        child=serializers.CharField(max_length=60, allow_blank=True),
        required=False,
        help_text="Special educational needs tags used by matching (sensitive).",
    )

    class Meta:
        model = Student
        fields = [
            "id", "client", "branch", "first_name", "last_name", "preferred_name", "full_name",
            "date_of_birth", "year_group", "school", "status", "status_changed_at", "subjects",
            "goals", "learning_needs", "exam_boards", "target_grades", "availability",
            "lesson_address", "lesson_address_input", "contact", "user", "custom_fields",
            "archived_at", "created_at", "next_lesson_at", "last_lesson_at", "hours_this_term",
            "merged_into", "sen_tags", "tutor_gender_preference",
        ]  # fmt: skip
        read_only_fields = [
            "id", "status_changed_at", "contact", "user", "archived_at", "created_at",
        ]  # fmt: skip
        field_permissions = {
            "date_of_birth": "people.student.view_sensitive",
            "learning_needs": "people.student.view_sensitive",
            "sen_tags": "people.student.view_sensitive",
            "tutor_gender_preference": "people.student.view_sensitive",
        }
        extra_kwargs = {"branch": {"required": False}}  # defaults to the client's branch

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance is not None and not isinstance(self.instance, list | tuple):
            self.fields["client"].read_only = True  # a student can't move household by PATCH


class ClientSerializer(BaseModelSerializer):
    billing_address = AddressSerializer(read_only=True)
    billing_address_input = AddressInput(
        write_only=True, required=False, source="billing_address_data"
    )
    primary_contact = serializers.UUIDField(source="primary_contact_id", read_only=True)
    students_count = serializers.IntegerField(read_only=True, required=False)
    balance = _figure(help_text="Ledger balance in the client's currency (positive: owes).")
    next_lesson_at = _moment()
    last_lesson_at = _moment()
    hours_this_term = _figure()
    merged_into = serializers.UUIDField(source="merged_into_id", read_only=True, allow_null=True)
    invoice_template = TenantRelatedField(
        InvoiceTemplate,
        required=False,
        allow_null=True,
        help_text="How this family's invoices look; empty: the organisation's default.",
    )

    class Meta:
        model = Client
        fields = [
            "id", "type", "display_name", "status", "branch", "primary_contact",
            "billing_contact", "billing_address", "billing_address_input", "currency",
            "payment_terms_days", "invoice_delivery", "invoice_grouping",
            "preferred_payment_method", "auto_pay", "credit_limit_amount",
            "prevent_negative_balance", "tax_exempt", "tax_id", "po_number",
            "referral_source", "account_manager", "custom_fields", "students_count",
            "archived_at", "created_at", "balance", "next_lesson_at", "last_lesson_at",
            "hours_this_term", "merged_into", "invoice_template",
        ]  # fmt: skip
        read_only_fields = ["id", "status", "billing_contact", "archived_at", "created_at"]
        field_permissions = {"tax_id": "billing.client.view_tax"}
        extra_kwargs = {"currency": {"required": False}, "branch": {"required": False}}


class ClientDetailSerializer(ClientSerializer):
    contacts = ContactSerializer(many=True, read_only=True)
    students = StudentSerializer(many=True, read_only=True)

    class Meta(ClientSerializer.Meta):
        fields = [*ClientSerializer.Meta.fields, "contacts", "students"]


class QuickAddContact(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    relationship = serializers.ChoiceField(choices=Contact.Relationship.choices, default="parent")


class QuickAddStudent(serializers.Serializer):
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    year_group = serializers.CharField(max_length=40, required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    subjects = SubjectInput(many=True, required=False)


class QuickAddSerializer(serializers.Serializer):
    """One-screen "add a family" (FR-05-1 AC)."""

    contact = QuickAddContact()
    students = QuickAddStudent(many=True, required=False, default=list)
    billing_address = AddressInput(required=False)
    branch = serializers.UUIDField(required=False)


class TutorSubjectSerializer(BaseModelSerializer):
    class Meta:
        model = TutorSubject
        fields = [
            "id", "subject", "level", "catalogue_subject", "catalogue_level", "proficiency",
            "approved", "approved_by",
        ]  # fmt: skip
        read_only_fields = ["id", "catalogue_subject", "catalogue_level", "approved", "approved_by"]


class TutorQualificationSerializer(BaseModelSerializer):
    class Meta:
        model = TutorQualification
        fields = ["id", "title", "institution", "year", "document"]


class TutorSerializer(BaseModelSerializer):
    address = AddressSerializer(read_only=True)
    address_input = AddressInput(write_only=True, required=False, source="address_data")
    subjects = TutorSubjectSerializer(many=True, read_only=True)
    qualifications = TutorQualificationSerializer(many=True, read_only=True)
    full_name = serializers.CharField(read_only=True)
    has_joined = serializers.SerializerMethodField()
    invite = serializers.BooleanField(write_only=True, default=True)
    hours_this_month = _figure()
    report_sla = serializers.DecimalField(
        max_digits=5,
        decimal_places=1,
        read_only=True,
        allow_null=True,
        help_text="% of lesson reports due in the last 90 days submitted on time.",
    )
    utilisation = serializers.DecimalField(
        max_digits=6,
        decimal_places=1,
        read_only=True,
        allow_null=True,
        help_text="Booked time this month as a % of weekly availability.",
    )
    sen_tags = serializers.ListField(
        child=serializers.CharField(max_length=60, allow_blank=True),
        required=False,
        help_text="Special educational needs the tutor has experience with (matching).",
    )
    exam_boards = serializers.ListField(
        child=serializers.CharField(max_length=60, allow_blank=True),
        required=False,
        help_text="Exam boards the tutor teaches (matching).",
    )

    class Meta:
        model = TutorProfile
        fields = [
            "id", "email", "first_name", "last_name", "display_name", "full_name", "phone",
            "headline", "bio_public", "bio_private", "languages", "years_experience",
            "employment_type", "pay_rate_amount", "address", "address_input",
            "travel_radius_km", "delivers_online", "delivers_in_person", "max_weekly_hours",
            "min_lesson_minutes", "branches", "status", "status_changed_at",
            "public_profile", "tax_reference", "date_of_birth", "emergency_contact",
            "subjects", "qualifications", "custom_fields", "has_joined", "invite",
            "archived_at", "created_at", "hours_this_month", "report_sla", "utilisation",
            "gender", "sen_tags", "exam_boards",
        ]  # fmt: skip
        read_only_fields = ["id", "status", "status_changed_at", "archived_at", "created_at"]
        field_permissions = {
            "pay_rate_amount": "billing.rates.view_pay",
            "tax_reference": "people.tutor.view_financial",
            "date_of_birth": "people.tutor.view_financial",
            "gender": "people.tutor.view_sensitive",
        }

    def get_has_joined(self, obj: TutorProfile) -> bool:
        return obj.membership_id is not None


class StatusSerializer(serializers.Serializer):
    status = serializers.CharField(max_length=15)


class DuplicateSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["contact", "student", "tutor"])
    id = serializers.UUIDField()
    name = serializers.CharField()
    client_id = serializers.UUIDField(allow_null=True)
    reason = serializers.CharField()


# --- merge (FR-05-13) ---------------------------------------------------------------------------


class MergeRecordSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MergeFieldSerializer(serializers.Serializer):
    name = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    source = serializers.CharField(allow_blank=True)  # type: ignore[assignment]
    target = serializers.CharField(allow_blank=True)
    hidden = serializers.BooleanField()
    same = serializers.BooleanField()
    default = serializers.ChoiceField(choices=["source", "target"])


class MergeMoveSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    count = serializers.IntegerField()


class MergePreviewSerializer(serializers.Serializer):
    subject_type = serializers.CharField()
    source = MergeRecordSerializer()  # type: ignore[assignment]
    target = MergeRecordSerializer()
    values = MergeFieldSerializer(many=True)
    moves = MergeMoveSerializer(many=True)
    problems = serializers.ListField(child=serializers.CharField())
    warnings = serializers.ListField(child=serializers.CharField())
    can_merge = serializers.BooleanField()


class MergeRequestSerializer(serializers.Serializer):
    source = serializers.UUIDField(help_text="The duplicate (archived).")  # type: ignore[assignment]
    target = serializers.UUIDField(help_text="The record that stays.")
    choices = serializers.DictField(
        child=serializers.ChoiceField(choices=["source", "target"]), required=False
    )
    confirm = serializers.BooleanField(help_text="Must be true: a merge can't be undone.")


class MergeResultSerializer(serializers.Serializer):
    subject_type = serializers.CharField()
    target_id = serializers.UUIDField()
    merged_id = serializers.UUIDField()
    moved = serializers.DictField(child=serializers.IntegerField())
    notes = serializers.ListField(child=serializers.CharField())


class DuplicatePersonSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    detail = serializers.CharField(allow_blank=True)
    client_id = serializers.UUIDField()
    created_at = serializers.DateTimeField()


class DuplicatePairSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["client", "contact", "student"])
    a = DuplicatePersonSerializer(help_text="The older record: suggested to keep.")
    b = DuplicatePersonSerializer()
    reason = serializers.CharField()


class MapPointSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["student", "tutor"])
    id = serializers.UUIDField()
    name = serializers.CharField()
    status = serializers.CharField()
    area = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    subjects = serializers.ListField(child=serializers.CharField())
    travel_radius_km = serializers.IntegerField(allow_null=True)


class MapMissingSerializer(serializers.Serializer):
    student = serializers.IntegerField()
    tutor = serializers.IntegerField()


class PeopleMapSerializer(serializers.Serializer):
    points = MapPointSerializer(many=True)
    missing = MapMissingSerializer()


class GeocodeRequestSerializer(serializers.Serializer):
    kinds = serializers.ListField(
        child=serializers.ChoiceField(choices=["student", "tutor"]),
        required=False,
        default=["student", "tutor"],
    )


class GeocodeResultSerializer(serializers.Serializer):
    queued = serializers.IntegerField()
