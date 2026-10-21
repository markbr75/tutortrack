from __future__ import annotations

from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import MoneySerializerField
from tutortrack.people.models import TUTOR_GENDERS

from ..models import (
    CoverRequest,
    JobOffer,
    JobPosting,
    JobPostingApplication,
    OfferBatch,
    Shortlist,
    ShortlistShare,
)


class MatchSlotSerializer(serializers.Serializer):
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    time = serializers.RegexField(r"^\d{2}:\d{2}$")
    duration_minutes = serializers.IntegerField(min_value=5, max_value=720, required=False)


class MatchSearchSerializer(serializers.Serializer):
    job = serializers.UUIDField(required=False, allow_null=True)
    subject = serializers.UUIDField(required=False, allow_null=True)
    level = serializers.UUIDField(required=False, allow_null=True)
    mode = serializers.ChoiceField(choices=["online", "in_person", "either"], required=False)
    postcode = serializers.CharField(required=False, allow_blank=True, max_length=20)
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    slots = MatchSlotSerializer(many=True, required=False)
    start_date = serializers.DateField(required=False, allow_null=True)
    duration_minutes = serializers.IntegerField(min_value=5, max_value=720, required=False)
    branch = serializers.UUIDField(required=False, allow_null=True)
    languages = serializers.ListField(child=serializers.CharField(max_length=40), required=False)
    max_pay_rate = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    requirements = serializers.ListField(child=serializers.CharField(max_length=40), required=False)
    # Gap G5c (FR-19-1): override the job's students' needs (omit to use theirs).
    exam_boards = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, allow_null=True
    )
    sen_tags = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, allow_null=True
    )
    gender = serializers.ChoiceField(
        choices=TUTOR_GENDERS,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Tutor gender preference; ignored unless matching.gender_preference is on.",
    )
    include_restricted = serializers.BooleanField(default=False)
    limit = serializers.IntegerField(min_value=1, max_value=200, default=50)


class MatchNeedsSerializer(serializers.Serializer):
    """The students' needs the search used (gap G5c). SEN tags and the gender preference
    are empty for viewers without ``people.student.view_sensitive``."""

    exam_boards = serializers.ListField(child=serializers.CharField())
    sen_tags = serializers.ListField(child=serializers.CharField())
    gender = serializers.CharField(allow_blank=True)
    gender_preference_enabled = serializers.BooleanField()


class MatchTutorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    headline = serializers.CharField(allow_blank=True)
    status = serializers.CharField()


class PointSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()


class FactorSerializer(serializers.Serializer):
    weight = serializers.FloatField()
    score = serializers.FloatField()
    value = serializers.JSONField(allow_null=True)
    known = serializers.BooleanField()


class MatchRowSerializer(serializers.Serializer):
    rank = serializers.IntegerField()
    tutor = MatchTutorSerializer()
    score = serializers.DecimalField(max_digits=5, decimal_places=1)
    breakdown = serializers.DictField(child=FactorSerializer())
    distance_km = serializers.DecimalField(max_digits=8, decimal_places=1, allow_null=True)
    slot_fit = serializers.ListField(child=serializers.FloatField())
    restricted = serializers.BooleanField()
    reasons = serializers.ListField(child=serializers.CharField())
    point = PointSerializer(allow_null=True)
    shortlisted = serializers.BooleanField()


class MatchSearchResultSerializer(serializers.Serializer):
    query = serializers.UUIDField()
    criteria = serializers.DictField()
    needs = MatchNeedsSerializer()
    origin = PointSerializer(allow_null=True)
    results = MatchRowSerializer(many=True)


class MatchingWeightsSerializer(serializers.Serializer):
    weights = serializers.DictField(child=serializers.FloatField(min_value=0, max_value=100))
    gender_preference = serializers.BooleanField(
        read_only=True, help_text="Whether matching.gender_preference is on (gap G5c)."
    )


class ShortlistSerializer(serializers.ModelSerializer):
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)

    class Meta:
        model = Shortlist
        fields = ["id", "job", "tutor", "tutor_name", "score", "breakdown", "note", "created_at"]
        read_only_fields = ["score", "breakdown", "created_at"]


class JobOfferSerializer(serializers.ModelSerializer):
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)

    class Meta:
        model = JobOffer
        fields = [
            "id",
            "batch",
            "job",
            "tutor",
            "tutor_name",
            "cascade_order",
            "status",
            "sent_at",
            "expires_at",
            "responded_at",
            "decline_reason",
            "confirmed_at",
        ]
        read_only_fields = fields


class OfferBatchSerializer(serializers.ModelSerializer):
    offers = JobOfferSerializer(many=True, read_only=True)
    pay_rate = MoneySerializerField(decimal_places=4, read_only=True, allow_null=True)
    job_name = serializers.CharField(source="job.__str__", read_only=True)

    class Meta:
        model = OfferBatch
        fields = [
            "id",
            "job",
            "job_name",
            "mode",
            "status",
            "expiry_hours",
            "admin_confirms",
            "brief",
            "pay_rate",
            "accepted_offer",
            "closed_at",
            "created_at",
            "offers",
        ]
        read_only_fields = fields


class StartOffersSerializer(serializers.Serializer):
    job = serializers.UUIDField()
    tutors = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=50)
    mode = serializers.ChoiceField(choices=OfferBatch.Mode.choices, default="sequential")
    expiry_hours = serializers.IntegerField(min_value=1, max_value=336, required=False)
    admin_confirms = serializers.BooleanField(required=False, allow_null=True, default=None)
    pay_rate = MoneySerializerField(decimal_places=4, required=False, allow_null=True)


class DecideSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class DeclineOfferSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class MyJobOfferSerializer(serializers.ModelSerializer):
    brief = serializers.JSONField(source="batch.brief", read_only=True)

    class Meta:
        model = JobOffer
        fields = [
            "id",
            "status",
            "brief",
            "sent_at",
            "expires_at",
            "responded_at",
            "decline_reason",
        ]
        read_only_fields = fields


class PostingApplicationSerializer(serializers.ModelSerializer):
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)

    class Meta:
        model = JobPostingApplication
        fields = [
            "id",
            "tutor",
            "tutor_name",
            "message",
            "proposed_availability",
            "status",
            "score",
            "breakdown",
            "created_at",
        ]
        read_only_fields = fields


class JobPostingSerializer(serializers.ModelSerializer):
    applications_count = serializers.SerializerMethodField()
    eligible_count = serializers.SerializerMethodField()

    class Meta:
        model = JobPosting
        fields = [
            "id",
            "job",
            "title",
            "brief",
            "audience",
            "status",
            "published_at",
            "closes_on",
            "closed_at",
            "applications_count",
            "eligible_count",
        ]
        read_only_fields = fields

    def get_applications_count(self, obj: JobPosting) -> int:
        return obj.applications.exclude(status="withdrawn").count()

    def get_eligible_count(self, obj: JobPosting) -> int:
        return len(obj.eligible or [])


class JobPostingDetailSerializer(JobPostingSerializer):
    applications = serializers.SerializerMethodField()

    class Meta(JobPostingSerializer.Meta):
        fields = [*JobPostingSerializer.Meta.fields, "applications"]
        read_only_fields = fields

    @extend_schema_field(PostingApplicationSerializer(many=True))
    def get_applications(self, obj: JobPosting) -> list[dict[str, Any]]:
        rows = obj.applications.select_related("tutor").order_by("-score", "created_at")
        return PostingApplicationSerializer(rows, many=True).data  # type: ignore[return-value]


class PublishPostingSerializer(serializers.Serializer):
    job = serializers.UUIDField()
    title = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    min_score = serializers.DecimalField(
        max_digits=4, decimal_places=1, min_value=Decimal(0), default=Decimal(0)
    )
    closes_on = serializers.DateField(required=False, allow_null=True)


class MyPostingSerializer(serializers.ModelSerializer):
    applied = serializers.SerializerMethodField()

    class Meta:
        model = JobPosting
        fields = ["id", "title", "brief", "published_at", "closes_on", "applied"]
        read_only_fields = fields

    def get_applied(self, obj: JobPosting) -> str | None:
        tutor = self.context.get("tutor")
        app = obj.applications.filter(tutor=tutor).first() if tutor is not None else None
        return app.status if app else None


class ApplyPostingSerializer(serializers.Serializer):
    message = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")
    proposed_availability = MatchSlotSerializer(many=True, required=False)


class CoverLessonSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="lesson.pk")
    title = serializers.CharField(source="lesson.title")
    start = serializers.DateTimeField(source="lesson.start")
    end = serializers.DateTimeField(source="lesson.end")
    timezone = serializers.CharField(source="lesson.timezone")


class CoverRequestSerializer(serializers.ModelSerializer):
    original_tutor_name = serializers.CharField(source="original_tutor.full_name", read_only=True)
    accepted_by_name = serializers.CharField(
        source="accepted_by.full_name", read_only=True, default=""
    )
    lessons = CoverLessonSerializer(many=True, read_only=True)
    notified_count = serializers.SerializerMethodField()

    class Meta:
        model = CoverRequest
        fields = [
            "id",
            "original_tutor",
            "original_tutor_name",
            "reason",
            "status",
            "deadline",
            "notified_count",
            "accepted_by",
            "accepted_by_name",
            "accepted_at",
            "closed_at",
            "lessons",
            "created_at",
        ]
        read_only_fields = fields

    def get_notified_count(self, obj: CoverRequest) -> int:
        return len(obj.notified or [])


class CreateCoverSerializer(serializers.Serializer):
    lessons = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=50)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class AssignCoverSerializer(serializers.Serializer):
    tutor = serializers.UUIDField()


class TimeToMatchSerializer(serializers.Serializer):
    jobs = serializers.IntegerField()
    average_hours = serializers.FloatField(allow_null=True)
    median_hours = serializers.FloatField(allow_null=True)


class OfferStatsSerializer(serializers.Serializer):
    tutor = serializers.UUIDField()
    name = serializers.CharField()
    sent = serializers.IntegerField()
    accepted = serializers.IntegerField()
    declined = serializers.IntegerField()
    expired = serializers.IntegerField()
    acceptance_rate = serializers.FloatField()


class UnmatchedDemandSerializer(serializers.Serializer):
    subject = serializers.CharField(allow_blank=True)
    area = serializers.CharField(allow_blank=True)
    jobs = serializers.IntegerField()
    oldest_days = serializers.IntegerField()


class EmptySearchSerializer(serializers.Serializer):
    subject = serializers.CharField(allow_blank=True)
    searches = serializers.IntegerField()


class MatchingAnalyticsSerializer(serializers.Serializer):
    days = serializers.IntegerField()
    time_to_match = TimeToMatchSerializer()
    offers = OfferStatsSerializer(many=True)
    unmatched = UnmatchedDemandSerializer(many=True)
    empty_searches = EmptySearchSerializer(many=True)


# --- shared shortlists (E19-T08) ------------------------------------------------------------

SHARE_STATES = ["active", "chosen", "revoked", "expired"]


class ShortlistShareSerializer(serializers.ModelSerializer):
    tutors = serializers.ListField(child=serializers.UUIDField(), read_only=True)
    state = serializers.SerializerMethodField()
    link = serializers.SerializerMethodField()
    contact_name = serializers.SerializerMethodField()
    chosen_tutor_name = serializers.SerializerMethodField()

    class Meta:
        model = ShortlistShare
        fields = [
            "id",
            "job",
            "tutors",
            "contact",
            "contact_name",
            "message",
            "status",
            "state",
            "expires_at",
            "viewed_at",
            "chosen_tutor",
            "chosen_tutor_name",
            "chosen_at",
            "client_note",
            "offer_batch",
            "link",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ChoiceField(choices=SHARE_STATES))
    def get_state(self, obj: ShortlistShare) -> str:
        from tutortrack.core.time import now

        return obj.state(now())

    @extend_schema_field(serializers.CharField())
    def get_link(self, obj: ShortlistShare) -> str:
        """The family's link (empty once it is no longer open)."""
        from tutortrack.comms.catalogue import tenant_link
        from tutortrack.core.time import now

        from ..sharing import token_for

        if obj.state(now()) != "active":
            return ""
        return tenant_link(f"/shortlists/{token_for(obj)}")

    @extend_schema_field(serializers.CharField())
    def get_contact_name(self, obj: ShortlistShare) -> str:
        return obj.contact.full_name if obj.contact is not None else ""

    @extend_schema_field(serializers.CharField())
    def get_chosen_tutor_name(self, obj: ShortlistShare) -> str:
        return obj.chosen_tutor.full_name if obj.chosen_tutor is not None else ""


class ShortlistShareCreateSerializer(serializers.Serializer):
    job = serializers.UUIDField()
    tutors = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=False)
    contact = serializers.UUIDField(required=False, allow_null=True)
    message = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    days = serializers.IntegerField(min_value=1, max_value=90, required=False, allow_null=True)


class PublicTutorSubjectSerializer(serializers.Serializer):
    subject = serializers.CharField()
    level = serializers.CharField(allow_blank=True)


class PublicTutorQualificationSerializer(serializers.Serializer):
    title = serializers.CharField()
    institution = serializers.CharField(allow_blank=True)
    year = serializers.IntegerField(allow_null=True)


class PublicTutorCardSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    headline = serializers.CharField(allow_blank=True)
    bio = serializers.CharField(allow_blank=True)
    photo_url = serializers.CharField(allow_blank=True)
    subjects = PublicTutorSubjectSerializer(many=True)
    qualifications = PublicTutorQualificationSerializer(many=True)
    years_experience = serializers.IntegerField(allow_null=True)
    languages = serializers.ListField(child=serializers.CharField())
    online = serializers.BooleanField()
    in_person = serializers.BooleanField()
    rating = serializers.FloatField(allow_null=True)
    rating_count = serializers.IntegerField()


class PublicShortlistJobSerializer(serializers.Serializer):
    subject = serializers.CharField(allow_blank=True)
    level = serializers.CharField(allow_blank=True)
    service = serializers.CharField()
    students = serializers.ListField(child=serializers.CharField())
    online = serializers.BooleanField()


class PublicShortlistSerializer(serializers.Serializer):
    organisation = serializers.CharField()
    status = serializers.ChoiceField(choices=SHARE_STATES)
    expires_at = serializers.DateTimeField()
    message = serializers.CharField(allow_blank=True)
    job = PublicShortlistJobSerializer()
    tutors = PublicTutorCardSerializer(many=True)
    chosen_tutor = serializers.UUIDField(allow_null=True)


class ShortlistChoiceSerializer(serializers.Serializer):
    tutor = serializers.UUIDField()
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
