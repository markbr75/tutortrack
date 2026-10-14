"""Serializers for reviews, referrals and affiliates (E25)."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import (
    BaseModelSerializer,
    MoneyOut,
    MoneySerializerField,
    TenantRelatedField,
)
from tutortrack.people.models import Client, Contact, Student, TutorProfile

from ..models import (
    Affiliate,
    AffiliateLink,
    AffiliateReferral,
    AffiliateStatement,
    CommissionItem,
    CommissionRule,
    Referral,
    ReferralCode,
    ReferralProgram,
    Review,
    ReviewRequest,
    TutorReferral,
)


def _tutor_name(tutor: Any) -> str:
    return (tutor.display_name or tutor.full_name) if tutor is not None else ""


# --- reviews ------------------------------------------------------------------------------------


class ReviewSerializer(BaseModelSerializer):
    client = TenantRelatedField(Client)
    tutor = TenantRelatedField(TutorProfile, required=False, allow_null=True)
    student = TenantRelatedField(Student, required=False, allow_null=True)
    contact = TenantRelatedField(Contact, required=False, allow_null=True)
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    tutor_name = serializers.SerializerMethodField()
    published_as_testimonial = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            "id",
            "client",
            "client_name",
            "contact",
            "student",
            "tutor",
            "tutor_name",
            "rating",
            "criteria",
            "text",
            "reviewer_name",
            "publish_consent",
            "source",
            "status",
            "moderated_at",
            "response",
            "responded_at",
            "google_prompted",
            "published_as_testimonial",
            "request",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "source",
            "status",
            "moderated_at",
            "response",
            "responded_at",
            "google_prompted",
            "request",
            "created_at",
        ]
        extra_kwargs = {"rating": {"min_value": 1, "max_value": 5}}

    @extend_schema_field(serializers.CharField())
    def get_tutor_name(self, obj: Review) -> str:
        return _tutor_name(obj.tutor)

    @extend_schema_field(serializers.BooleanField())
    def get_published_as_testimonial(self, obj: Review) -> bool:
        return bool(obj.testimonial_id and obj.testimonial and obj.testimonial.published)


class ReviewReplySerializer(serializers.Serializer):
    response = serializers.CharField(allow_blank=True, max_length=2000)


class RatingSummarySerializer(serializers.Serializer):
    average = serializers.FloatField(allow_null=True)
    count = serializers.IntegerField()
    stars = serializers.DictField(child=serializers.IntegerField())


class ReviewInviteSerializer(BaseModelSerializer):
    client = TenantRelatedField(Client)
    tutor = TenantRelatedField(TutorProfile, required=False, allow_null=True)
    student = TenantRelatedField(Student, required=False, allow_null=True)
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    tutor_name = serializers.SerializerMethodField()

    class Meta:
        model = ReviewRequest
        fields = [
            "id",
            "client",
            "client_name",
            "student",
            "tutor",
            "tutor_name",
            "trigger",
            "status",
            "lesson_count",
            "sent_at",
            "reminded_at",
            "submitted_at",
            "expires_at",
            "workflow_id",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "trigger",
            "status",
            "lesson_count",
            "sent_at",
            "reminded_at",
            "submitted_at",
            "expires_at",
            "workflow_id",
            "created_at",
        ]

    @extend_schema_field(serializers.CharField())
    def get_tutor_name(self, obj: ReviewRequest) -> str:
        return _tutor_name(obj.tutor)


class PublicReviewPageSerializer(serializers.Serializer):
    organisation = serializers.CharField()
    tutor = serializers.CharField(allow_blank=True)
    student = serializers.CharField(allow_blank=True)
    reviewer_name = serializers.CharField(allow_blank=True)
    criteria = serializers.ListField(child=serializers.CharField())
    open = serializers.BooleanField()
    status = serializers.CharField()


class PublicReviewSubmitSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    criteria = serializers.DictField(
        child=serializers.IntegerField(min_value=1, max_value=5), required=False, default=dict
    )
    text = serializers.CharField(required=False, allow_blank=True, default="", max_length=5000)
    reviewer_name = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=120
    )
    publish_consent = serializers.BooleanField(required=False, default=False)


class PublicReviewThanksSerializer(serializers.Serializer):
    status = serializers.CharField()
    google_review_url = serializers.CharField(allow_blank=True)


# --- referrals ----------------------------------------------------------------------------------


class ReferralProgramSerializer(BaseModelSerializer):
    referrer_reward = MoneySerializerField()

    class Meta:
        model = ReferralProgram
        fields = [
            "id",
            "name",
            "active",
            "referrer_reward_kind",
            "referrer_reward",
            "milestone",
            "milestone_lessons",
            "referee_discount_percent",
            "referee_discount_days",
            "deadline_days",
            "max_rewards_per_period",
            "period_days",
            "terms",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class ReferralSerializer(BaseModelSerializer):
    referrer = TenantRelatedField(Client)
    referee = TenantRelatedField(Client)
    referrer_name = serializers.CharField(source="referrer.display_name", read_only=True)
    referee_name = serializers.CharField(source="referee.display_name", read_only=True)
    code_value = serializers.CharField(source="code.code", read_only=True, default="")

    class Meta:
        model = Referral
        fields = [
            "id",
            "program",
            "referrer",
            "referrer_name",
            "referee",
            "referee_name",
            "code_value",
            "source",
            "status",
            "deadline",
            "converted_at",
            "rewarded_at",
            "fraud_flags",
            "referrer_credit",
            "referee_discount_id",
            "note",
            "enquiry_id",
            "workflow_id",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "program",
            "source",
            "status",
            "deadline",
            "converted_at",
            "rewarded_at",
            "fraud_flags",
            "referrer_credit",
            "referee_discount_id",
            "enquiry_id",
            "workflow_id",
            "created_at",
        ]


class GrowthReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=300)


class ReferralCodeSerializer(BaseModelSerializer):
    client = TenantRelatedField(Client, required=False, allow_null=True)
    tutor = TenantRelatedField(TutorProfile, required=False, allow_null=True)
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = ReferralCode
        fields = ["id", "code", "client", "tutor", "owner_name", "clicks", "active", "created_at"]
        read_only_fields = ["id", "code", "clicks", "active", "created_at"]

    @extend_schema_field(serializers.CharField())
    def get_owner_name(self, obj: ReferralCode) -> str:
        if obj.client is not None:
            return obj.client.display_name
        return _tutor_name(obj.tutor)


class PortalReferralRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    rewarded_at = serializers.DateTimeField(allow_null=True)
    reward = MoneyOut(allow_null=True)


class PortalProgramSerializer(serializers.Serializer):
    name = serializers.CharField()
    referrer_reward = MoneyOut()
    referrer_reward_kind = serializers.CharField()
    milestone = serializers.CharField()
    milestone_lessons = serializers.IntegerField()
    referee_discount_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, allow_null=True
    )
    terms = serializers.CharField(allow_blank=True)


class PortalReferralsSerializer(serializers.Serializer):
    code = serializers.CharField()
    link = serializers.CharField()
    program = PortalProgramSerializer(allow_null=True)
    referrals = PortalReferralRowSerializer(many=True)
    earned = MoneyOut(many=True)


class PublicRefSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40)


class PublicRefResultSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    kind = serializers.CharField(allow_blank=True)
    landing_path = serializers.CharField(allow_blank=True)
    remember_days = serializers.IntegerField()
    offer = serializers.CharField(allow_blank=True)


# --- affiliates ---------------------------------------------------------------------------------


class AffiliateBankDetailsSerializer(serializers.Serializer):
    sort_code = serializers.CharField(required=False, allow_blank=True)
    account_number = serializers.CharField(required=False, allow_blank=True)
    iban = serializers.CharField(required=False, allow_blank=True)
    bic = serializers.CharField(required=False, allow_blank=True)
    routing_number = serializers.CharField(required=False, allow_blank=True)
    account_type = serializers.CharField(required=False, allow_blank=True)
    bsb = serializers.CharField(required=False, allow_blank=True)
    bank_code = serializers.CharField(required=False, allow_blank=True)
    account_name = serializers.CharField(required=False, allow_blank=True)


class AffiliateSerializer(BaseModelSerializer):
    bank = AffiliateBankDetailsSerializer(write_only=True, required=False)
    has_login = serializers.SerializerMethodField()

    class Meta:
        model = Affiliate
        fields = [
            "id",
            "kind",
            "name",
            "email",
            "phone",
            "status",
            "currency",
            "payout_method",
            "payee_name",
            "bank_country",
            "bank_hint",
            "bank",
            "notes",
            "has_login",
            "created_at",
        ]
        read_only_fields = ["id", "bank_hint", "has_login", "created_at"]
        extra_kwargs = {"currency": {"required": False}}

    @extend_schema_field(serializers.BooleanField())
    def get_has_login(self, obj: Affiliate) -> bool:
        return obj.user_id is not None


class AffiliateLinkSerializer(BaseModelSerializer):
    affiliate = TenantRelatedField(Affiliate)
    affiliate_name = serializers.CharField(source="affiliate.name", read_only=True)

    class Meta:
        model = AffiliateLink
        fields = [
            "id",
            "affiliate",
            "affiliate_name",
            "code",
            "name",
            "landing_path",
            "clicks",
            "active",
            "created_at",
        ]
        read_only_fields = ["id", "clicks", "created_at"]
        extra_kwargs = {"code": {"required": False}}


class AffiliateReferralSerializer(BaseModelSerializer):
    affiliate_name = serializers.CharField(source="affiliate.name", read_only=True)
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    link_code = serializers.CharField(source="link.code", read_only=True, default="")

    class Meta:
        model = AffiliateReferral
        fields = [
            "id",
            "affiliate",
            "affiliate_name",
            "client",
            "client_name",
            "link",
            "link_code",
            "source",
            "attributed_at",
            "converted_at",
            "enquiry_id",
            "created_at",
        ]
        read_only_fields = fields


class AssignClientSerializer(serializers.Serializer):
    client = TenantRelatedField(Client)


class CommissionRuleSerializer(BaseModelSerializer):
    affiliate = TenantRelatedField(Affiliate, required=False, allow_null=True)
    bounty = MoneySerializerField(required=False, allow_null=True)
    tiers = serializers.ListField(child=serializers.DictField(), required=False)

    class Meta:
        model = CommissionRule
        fields = [
            "id",
            "affiliate",
            "name",
            "kind",
            "active",
            "percent",
            "tiers",
            "bounty",
            "duration_months",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class CommissionItemSerializer(BaseModelSerializer):
    affiliate_name = serializers.CharField(source="affiliate.name", read_only=True)
    client_name = serializers.SerializerMethodField()
    statement_number = serializers.CharField(source="statement.number", read_only=True, default="")

    class Meta:
        model = CommissionItem
        fields = [
            "id",
            "affiliate",
            "affiliate_name",
            "client",
            "client_name",
            "kind",
            "base",
            "rate",
            "amount",
            "description",
            "earned_at",
            "statement",
            "statement_number",
            "payment_id",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_client_name(self, obj: CommissionItem) -> str:
        return obj.client.display_name if obj.client is not None else ""


class AdjustSerializer(serializers.Serializer):
    amount = MoneySerializerField()
    description = serializers.CharField(max_length=300)


class AffiliateStatementSerializer(BaseModelSerializer):
    affiliate_name = serializers.CharField(source="affiliate.name", read_only=True)
    item_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = AffiliateStatement
        fields = [
            "id",
            "affiliate",
            "affiliate_name",
            "number",
            "period_start",
            "period_end",
            "total",
            "status",
            "issued_at",
            "paid_at",
            "payout_method",
            "payout_reference",
            "item_count",
        ]
        read_only_fields = fields


class IssueStatementsSerializer(serializers.Serializer):
    period_end = serializers.DateField(required=False, allow_null=True)


class PayStatementSerializer(serializers.Serializer):
    reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)


class AffiliateBankFileRequestSerializer(serializers.Serializer):
    statements = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=500)
    file_format = serializers.ChoiceField(
        choices=["csv", "bacs18", "sepa", "nacha", "aba"], required=False, allow_null=True
    )


class AffiliateBankFileSerializer(serializers.Serializer):
    filename = serializers.CharField()
    content = serializers.CharField()


class SummaryTotalsSerializer(serializers.Serializer):
    currency = serializers.CharField()
    earned = MoneyOut()
    unpaid = MoneyOut()
    paid = MoneyOut()


class AffiliateSummarySerializer(serializers.Serializer):
    clicks = serializers.IntegerField()
    referred = serializers.IntegerField()
    converted = serializers.IntegerField()
    totals = SummaryTotalsSerializer(many=True)


class InvitationSentSerializer(serializers.Serializer):
    email = serializers.EmailField()


# --- affiliate portal ---------------------------------------------------------------------------


class PortalAffiliateLinkSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    url = serializers.CharField()
    clicks = serializers.IntegerField()


class PortalAffiliateSerializer(serializers.Serializer):
    name = serializers.CharField()
    organisation = serializers.CharField()
    payout_method = serializers.CharField()
    bank_hint = serializers.CharField(allow_blank=True)
    summary = AffiliateSummarySerializer()
    links = PortalAffiliateLinkSerializer(many=True)


class PortalAffiliateClientSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    attributed_at = serializers.DateTimeField()
    converted_at = serializers.DateTimeField(allow_null=True)
    commission = MoneyOut(allow_null=True)


class PortalStatementItemSerializer(serializers.Serializer):
    kind = serializers.CharField()
    description = serializers.CharField()
    amount = MoneyOut()
    earned_at = serializers.DateTimeField()


class PortalStatementSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    number = serializers.CharField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    total = MoneyOut()
    status = serializers.CharField()
    paid_at = serializers.DateTimeField(allow_null=True)
    items = PortalStatementItemSerializer(many=True)


class PayoutDetailsSerializer(serializers.Serializer):
    payee_name = serializers.CharField(max_length=140)
    country = serializers.CharField(max_length=2)
    bank = AffiliateBankDetailsSerializer()


# --- tutor referrals ----------------------------------------------------------------------------


class TutorReferralSerializer(BaseModelSerializer):
    referrer = TenantRelatedField(TutorProfile)
    referred_tutor = TenantRelatedField(TutorProfile, required=False, allow_null=True)
    client = TenantRelatedField(Client, required=False, allow_null=True)
    referrer_name = serializers.SerializerMethodField()

    class Meta:
        model = TutorReferral
        fields = [
            "id",
            "referrer",
            "referrer_name",
            "kind",
            "application_id",
            "referred_tutor",
            "client",
            "referred_name",
            "status",
            "bonus",
            "pay_item_id",
            "qualified_at",
            "note",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "bonus",
            "pay_item_id",
            "qualified_at",
            "created_at",
        ]

    @extend_schema_field(serializers.CharField())
    def get_referrer_name(self, obj: TutorReferral) -> str:
        return _tutor_name(obj.referrer)


class PayBonusSerializer(serializers.Serializer):
    amount = MoneySerializerField(required=False, allow_null=True)


class TutorReferralRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    referred_name = serializers.CharField()
    status = serializers.CharField()
    bonus = MoneyOut(allow_null=True)
    created_at = serializers.DateTimeField()


class TutorReferralsPageSerializer(serializers.Serializer):
    code = serializers.CharField()
    client_link = serializers.CharField()
    tutor_link = serializers.CharField()
    referrals = TutorReferralRowSerializer(many=True)
