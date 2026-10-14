"""Growth API (E25): reviews and review requests, the referral programme and referrals,
affiliates (links, referred clients, commission rules and items, statements) and tutor
referral bonuses. Financial POSTs (statements, payouts, adjustments, bonuses) honour
``Idempotency-Key``."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation

from .. import selectors, services
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
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def managed(view: str, manage: str) -> dict[str, str]:
    return {"GET": view, "POST": manage, "PATCH": manage, "PUT": manage, "DELETE": manage}


REVIEWS = managed("growth.review.view", "growth.review.manage")
REFERRALS = managed("growth.referral.view", "growth.referral.manage")
AFFILIATES = managed("growth.affiliate.view", "growth.affiliate.manage")
COMMISSION = managed("growth.affiliate.view", "growth.commission.manage")
TUTOR_REFERRALS = managed("growth.tutor_referral.view", "growth.tutor_referral.manage")


def _uuid_filters(model_cls, *names, choices=None, booleans=()):
    attrs = {name: filters.UUIDFilter() for name in names}
    for name, values in (choices or {}).items():
        attrs[name] = filters.ChoiceFilter(choices=values)
    for name in booleans:
        attrs[name] = filters.BooleanFilter()
    attrs["Meta"] = type("Meta", (), {"model": model_cls, "fields": []})
    return type(f"{model_cls.__name__}Filter", (filters.FilterSet,), attrs)


ReferralCodeFilter = _uuid_filters(ReferralCode, "client", "tutor")
AffiliateLinkFilter = _uuid_filters(AffiliateLink, "affiliate", booleans=("active",))
AffiliateReferralFilter = _uuid_filters(AffiliateReferral, "affiliate", "client")
CommissionRuleFilter = _uuid_filters(
    CommissionRule, "affiliate", choices={"kind": CommissionRule.Kind.choices}, booleans=("active",)
)
StatementFilter = _uuid_filters(
    AffiliateStatement, "affiliate", choices={"status": AffiliateStatement.Status.choices}
)
TutorReferralFilter = _uuid_filters(
    TutorReferral,
    "referrer",
    choices={"status": TutorReferral.Status.choices, "kind": TutorReferral.Kind.choices},
)


# --- reviews (T01, T02) -------------------------------------------------------------------------


class ReviewFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=Review.Status.choices)
    tutor = filters.UUIDFilter()
    client = filters.UUIDFilter()
    min_rating = filters.NumberFilter(field_name="rating", lookup_expr="gte")
    max_rating = filters.NumberFilter(field_name="rating", lookup_expr="lte")

    class Meta:
        model = Review
        fields: list[str] = []


class ReviewViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Reviews and the moderation queue (``?status=pending``). Tutors (own scope) see the
    approved reviews about them when ``growth.tutors_see_reviews`` is on."""

    model = Review
    serializer_class = s.ReviewSerializer
    filterset_class = ReviewFilter
    permission_classes = perms(REVIEWS)

    def get_tenant_queryset(self) -> QuerySet[Review]:
        return selectors.reviews(self.request.user)

    @extend_schema(
        examples=[
            OpenApiExample(
                "A review sent by email",
                request_only=True,
                value={
                    "client": "0192a1b2-0000-7000-8000-000000000001",
                    "tutor": "0192a1b2-0000-7000-8000-000000000002",
                    "rating": 5,
                    "criteria": {"communication": 5},
                    "text": "Nia has transformed Arjun's confidence in maths.",
                    "reviewer_name": "Priya P.",
                    "publish_consent": True,
                },
            )
        ]
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.create_review(**serializer.validated_data)

    def _moderate(self, request: Request, verb: str) -> Response:
        review = services.moderate(self.get_object(), action=verb, user=request.user)
        return Response(self.get_serializer(review).data)

    @extend_schema(request=None, responses=s.ReviewSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: Any = None) -> Response:
        """Approve: counts in ratings; 4-5 stars with consent can become a testimonial."""
        return self._moderate(request, "approve")

    @extend_schema(request=None, responses=s.ReviewSerializer)
    @action(detail=True, methods=["post"])
    def hide(self, request: Request, pk: Any = None) -> Response:
        return self._moderate(request, "hide")

    @extend_schema(request=s.ReviewReplySerializer, responses=s.ReviewSerializer)
    @action(detail=True, methods=["post"])
    def respond(self, request: Request, pk: Any = None) -> Response:
        payload = s.ReviewReplySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        review = services.respond(
            self.get_object(), response=payload.validated_data["response"], user=request.user
        )
        return Response(self.get_serializer(review).data)

    @extend_schema(request=None, responses=s.ReviewSerializer)
    @action(detail=True, methods=["post"])
    def publish(self, request: Request, pk: Any = None) -> Response:
        """Publish as a website testimonial (E24 ``<tt-reviews>``)."""
        review = services.publish_testimonial(self.get_object())
        review.refresh_from_db()
        return Response(self.get_serializer(review).data)

    @extend_schema(request=None, responses=s.ReviewSerializer)
    @action(detail=True, methods=["post"])
    def unpublish(self, request: Request, pk: Any = None) -> Response:
        review = services.unpublish_testimonial(self.get_object())
        review.refresh_from_db()
        return Response(self.get_serializer(review).data)

    @extend_schema(
        parameters=[OpenApiParameter("tutor", str, required=False)],
        responses=s.RatingSummarySerializer,
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def summary(self, request: Request) -> Response:
        """Average rating, count and stars of approved reviews the user can see (the
        organisation's, or one tutor's with ``?tutor=``)."""
        tutor = request.query_params.get("tutor") or None
        body = selectors.rating_summary(selectors.reviews(request.user), tutor_id=tutor)
        return Response(s.RatingSummarySerializer(body).data)


class ReviewRequestFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=ReviewRequest.Status.choices)
    tutor = filters.UUIDFilter()
    client = filters.UUIDFilter()

    class Meta:
        model = ReviewRequest
        fields: list[str] = []


class ReviewRequestViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Review requests (FR-25-1). ``POST`` asks a family now (``ReviewRequestWorkflow``
    sends it and a reminder)."""

    model = ReviewRequest
    serializer_class = s.ReviewInviteSerializer
    filterset_class = ReviewRequestFilter
    permission_classes = perms(REVIEWS)

    def get_tenant_queryset(self) -> QuerySet[ReviewRequest]:
        return selectors.review_requests(self.request.user)

    def perform_create(self, serializer: Any) -> None:
        request = services.request_review(**serializer.validated_data)
        if request is None:
            raise BusinessRuleViolation(
                "This family already has an open review request for this tutor.",
                extra={"errors": {"client": ["Already asked."]}},
            )
        serializer.instance = request

    @extend_schema(request=None, responses=s.ReviewInviteSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        found = services.cancel_request(self.get_object())
        return Response(self.get_serializer(found).data)


# --- referral programme (T03) -------------------------------------------------------------------


class ReferralProgramViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = ReferralProgram
    serializer_class = s.ReferralProgramSerializer
    permission_classes = perms(REFERRALS)
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[ReferralProgram]:
        return selectors.programs(self.request.user)

    @extend_schema(
        examples=[
            OpenApiExample(
                "Give £20, get 10% off",
                request_only=True,
                value={
                    "name": "Refer a friend",
                    "referrer_reward_kind": "credit",
                    "referrer_reward": {"amount": "20.00", "currency": "GBP"},
                    "milestone": "first_payment",
                    "referee_discount_percent": "10.00",
                    "referee_discount_days": 90,
                    "deadline_days": 180,
                    "max_rewards_per_period": 5,
                    "period_days": 365,
                },
            )
        ]
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.save_program(None, **serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_program(
            serializer.instance, **serializer.validated_data
        )


class ReferralFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=Referral.Status.choices)
    referrer = filters.UUIDFilter()
    referee = filters.UUIDFilter()

    class Meta:
        model = Referral
        fields: list[str] = []


class ReferralViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Referrals (FR-25-2). ``POST`` records one by hand; ``ReferralRewardWorkflow``
    rewards it at the milestone. ``approve`` rewards a referral held by the fraud checks."""

    model = Referral
    serializer_class = s.ReferralSerializer
    filterset_class = ReferralFilter
    permission_classes = perms(REFERRALS)

    def get_tenant_queryset(self) -> QuerySet[Referral]:
        return selectors.referrals(self.request.user)

    def perform_create(self, serializer: Any) -> None:
        d = serializer.validated_data
        serializer.instance = services.create_referral(
            referrer=d["referrer"],
            referee=d["referee"],
            source=Referral.Source.STAFF,
            note=d.get("note", ""),
        )

    @extend_schema(request=None, responses=s.ReferralSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: Any = None) -> Response:
        """Financial: gives the rewards despite the fraud flags (``Idempotency-Key``)."""
        referral = services.approve_blocked(self.get_object(), user=request.user)
        return Response(self.get_serializer(referral).data)

    @extend_schema(request=s.GrowthReasonSerializer, responses=s.ReferralSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        payload = s.GrowthReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        referral = services.cancel_referral(
            self.get_object(), reason=payload.validated_data["reason"]
        )
        return Response(self.get_serializer(referral).data)


class ReferralCodeViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Clients' and tutors' referral codes. ``POST`` with ``client`` or ``tutor`` returns
    their code (made on first use)."""

    model = ReferralCode
    serializer_class = s.ReferralCodeSerializer
    permission_classes = perms(REFERRALS)
    filterset_class = ReferralCodeFilter

    def get_tenant_queryset(self) -> QuerySet[ReferralCode]:
        from tutortrack.core.permissions import permission_scope

        if permission_scope(self.request.user, "growth.referral.view") in (None, "own"):
            return ReferralCode.objects.none()
        return ReferralCode.objects.select_related("client", "tutor")

    def perform_create(self, serializer: Any) -> None:
        d = serializer.validated_data
        if d.get("client") is not None:
            serializer.instance = services.code_for_client(d["client"])
        elif d.get("tutor") is not None:
            serializer.instance = services.code_for_tutor(d["tutor"])
        else:
            raise BusinessRuleViolation(
                "Choose the client or tutor.", extra={"errors": {"client": ["Required."]}}
            )


# --- affiliates (T04) ---------------------------------------------------------------------------


class AffiliateFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=Affiliate.Status.choices)

    class Meta:
        model = Affiliate
        fields: list[str] = []


class AffiliateViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """Affiliates (FR-25-3) with ``invite`` (portal login), ``summary``, ``assign_client``
    and ``adjust`` (a manual commission correction)."""

    model = Affiliate
    serializer_class = s.AffiliateSerializer
    filterset_class = AffiliateFilter
    permission_classes = perms({**AFFILIATES, "POST": "growth.affiliate.manage"})
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[Affiliate]:
        return selectors.affiliates(self.request.user)

    @extend_schema(
        examples=[
            OpenApiExample(
                "A school partner paid by bank transfer",
                request_only=True,
                value={
                    "kind": "organisation",
                    "name": "Hillside Primary PTA",
                    "email": "pta@hillside.example",
                    "payout_method": "bank_file",
                    "payee_name": "Hillside PTA",
                    "bank_country": "GB",
                    "bank": {"sort_code": "040004", "account_number": "12345678"},
                },
            )
        ]
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().create(request, *args, **kwargs)

    def _save(self, serializer: Any, affiliate: Affiliate | None) -> None:
        data = dict(serializer.validated_data)
        bank = data.pop("bank", None)
        serializer.instance = services.save_affiliate(
            affiliate, bank=dict(bank) if bank else None, **data
        )

    def perform_create(self, serializer: Any) -> None:
        self._save(serializer, None)

    def perform_update(self, serializer: Any) -> None:
        self._save(serializer, serializer.instance)

    @extend_schema(request=None, responses={201: s.InvitationSentSerializer})
    @action(detail=True, methods=["post"])
    def invite(self, request: Request, pk: Any = None) -> Response:
        """Email the affiliate an invitation to the partner portal."""
        affiliate = self.get_object()
        services.invite_affiliate(affiliate)
        return Response({"email": affiliate.email}, status=status.HTTP_201_CREATED)

    @extend_schema(responses=s.AffiliateSummarySerializer)
    @action(detail=True, methods=["get"], pagination_class=None)
    def summary(self, request: Request, pk: Any = None) -> Response:
        return Response(
            s.AffiliateSummarySerializer(selectors.affiliate_summary(self.get_object())).data
        )

    @extend_schema(request=s.AssignClientSerializer, responses={201: s.AffiliateReferralSerializer})
    @action(detail=True, methods=["post"], url_path="assign-client")
    def assign_client(self, request: Request, pk: Any = None) -> Response:
        payload = s.AssignClientSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        referral = services.assign_client(self.get_object(), payload.validated_data["client"])
        return Response(
            s.AffiliateReferralSerializer(referral).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        request=s.AdjustSerializer,
        responses={201: s.CommissionItemSerializer},
        examples=[
            OpenApiExample(
                "Goodwill bonus",
                request_only=True,
                value={
                    "amount": {"amount": "25.00", "currency": "GBP"},
                    "description": "Thank-you for the open evening",
                },
            )
        ],
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=perms({"POST": "growth.commission.manage"}),
    )
    def adjust(self, request: Request, pk: Any = None) -> Response:
        """Financial: a manual commission item for the next statement (``Idempotency-Key``)."""
        payload = s.AdjustSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        item = services.adjust_commission(
            self.get_object(),
            amount=payload.validated_data["amount"],
            description=payload.validated_data["description"],
            user=request.user,
        )
        return Response(s.CommissionItemSerializer(item).data, status=status.HTTP_201_CREATED)


class AffiliateLinkViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = AffiliateLink
    serializer_class = s.AffiliateLinkSerializer
    permission_classes = perms(AFFILIATES)
    http_method_names = ["get", "post", "patch", "head", "options"]
    filterset_class = AffiliateLinkFilter

    def get_tenant_queryset(self) -> QuerySet[AffiliateLink]:
        return selectors.affiliate_links(self.request.user)

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        affiliate = data.pop("affiliate")
        serializer.instance = services.save_link(None, affiliate=affiliate, **data)

    def perform_update(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        data.pop("affiliate", None)
        serializer.instance = services.save_link(serializer.instance, **data)


class AffiliateReferralViewSet(TenantScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    """Clients attributed to affiliates."""

    model = AffiliateReferral
    serializer_class = s.AffiliateReferralSerializer
    permission_classes = perms(AFFILIATES)
    filterset_class = AffiliateReferralFilter

    def get_tenant_queryset(self) -> QuerySet[AffiliateReferral]:
        return selectors.affiliate_referrals(self.request.user)


# --- commission (T05) ---------------------------------------------------------------------------


class CommissionRuleViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """Commission rules: defaults (no affiliate) and per-affiliate overrides."""

    model = CommissionRule
    serializer_class = s.CommissionRuleSerializer
    permission_classes = perms(AFFILIATES)
    http_method_names = ["get", "post", "patch", "head", "options"]
    filterset_class = CommissionRuleFilter

    def get_tenant_queryset(self) -> QuerySet[CommissionRule]:
        return selectors.commission_rules(self.request.user)

    @extend_schema(
        examples=[
            OpenApiExample(
                "10% for 12 months, 15% from the 10th client",
                request_only=True,
                value={
                    "name": "Standard partner rate",
                    "kind": "percent",
                    "percent": "10.00",
                    "duration_months": 12,
                    "tiers": [{"from_clients": 10, "percent": "15.00"}],
                },
            )
        ]
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.save_rule(None, **serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_rule(serializer.instance, **serializer.validated_data)


class CommissionItemFilter(filters.FilterSet):
    affiliate = filters.UUIDFilter()
    statement = filters.UUIDFilter()
    kind = filters.ChoiceFilter(choices=CommissionItem.Kind.choices)
    unstatemented = filters.BooleanFilter(field_name="statement", lookup_expr="isnull")

    class Meta:
        model = CommissionItem
        fields: list[str] = []


class CommissionItemViewSet(TenantScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    """Commission items: earned, bounties, clawbacks (negative) and adjustments."""

    model = CommissionItem
    serializer_class = s.CommissionItemSerializer
    filterset_class = CommissionItemFilter
    permission_classes = perms(AFFILIATES)

    def get_tenant_queryset(self) -> QuerySet[CommissionItem]:
        return selectors.commission_items(self.request.user)


class StatementViewSet(TenantScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    """Affiliate statements: ``issue`` (to a period end), ``pay`` and ``bank-file``
    (financial POSTs honour ``Idempotency-Key``)."""

    model = AffiliateStatement
    serializer_class = s.AffiliateStatementSerializer
    permission_classes = perms(COMMISSION)
    filterset_class = StatementFilter

    def get_tenant_queryset(self) -> QuerySet[AffiliateStatement]:
        return selectors.statements(self.request.user)

    @extend_schema(
        request=s.IssueStatementsSerializer,
        responses={201: s.AffiliateStatementSerializer(many=True)},
        examples=[
            OpenApiExample(
                "September's statements", request_only=True, value={"period_end": "2026-09-30"}
            )
        ],
    )
    @action(detail=False, methods=["post"], pagination_class=None)
    def issue(self, request: Request) -> Response:
        payload = s.IssueStatementsSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        issued = services.issue_statements(
            payload.validated_data.get("period_end"), user=request.user
        )
        return Response(
            s.AffiliateStatementSerializer(issued, many=True).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=s.PayStatementSerializer, responses=s.AffiliateStatementSerializer)
    @action(detail=True, methods=["post"])
    def pay(self, request: Request, pk: Any = None) -> Response:
        payload = s.PayStatementSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        statement = services.mark_statement_paid(
            self.get_object(), reference=payload.validated_data["reference"], user=request.user
        )
        return Response(self.get_serializer(statement).data)

    @extend_schema(
        request=s.AffiliateBankFileRequestSerializer, responses=s.AffiliateBankFileSerializer
    )
    @action(detail=False, methods=["post"], url_path="bank-file", pagination_class=None)
    def bank_file(self, request: Request) -> Response:
        """An E12 bank payment file for statements of bank-transfer affiliates."""
        payload = s.AffiliateBankFileRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ids = [str(i) for i in payload.validated_data["statements"]]
        found = list(self.get_queryset().filter(pk__in=ids).select_related("affiliate"))
        if len(found) != len(set(ids)):
            raise BusinessRuleViolation(
                "Some statements weren't found.", extra={"errors": {"statements": ["Not found."]}}
            )
        filename, content = services.statements_bank_file(
            found, fmt=payload.validated_data.get("file_format")
        )
        return Response({"filename": filename, "content": content})


# --- tutor referrals (T06) ----------------------------------------------------------------------


class TutorReferralViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Tutor referral bonuses (FR-25-4): ``pay`` adds the bonus to the tutor's pay (E12)."""

    model = TutorReferral
    serializer_class = s.TutorReferralSerializer
    permission_classes = perms(TUTOR_REFERRALS)
    filterset_class = TutorReferralFilter

    def get_tenant_queryset(self) -> QuerySet[TutorReferral]:
        return selectors.tutor_referrals(self.request.user)

    def perform_create(self, serializer: Any) -> None:
        d = dict(serializer.validated_data)
        serializer.instance = services.record_tutor_referral(
            referrer=d["referrer"],
            kind=d["kind"],
            application_id=d.get("application_id", ""),
            referred_tutor=d.get("referred_tutor"),
            client=d.get("client"),
            referred_name=d.get("referred_name", ""),
            note=d.get("note", ""),
        )

    @extend_schema(request=s.PayBonusSerializer, responses=s.TutorReferralSerializer)
    @action(detail=True, methods=["post"])
    def pay(self, request: Request, pk: Any = None) -> Response:
        """Financial: pay the bonus now (the configured amount, or ``amount``)."""
        payload = s.PayBonusSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        referral = services.pay_tutor_referral(
            self.get_object(), amount=payload.validated_data.get("amount")
        )
        if referral.status != TutorReferral.Status.PAID:
            raise BusinessRuleViolation(
                "Set a bonus amount in referral settings or give one here.",
                extra={"errors": {"amount": ["Required."]}},
            )
        return Response(self.get_serializer(referral).data)

    @extend_schema(request=s.GrowthReasonSerializer, responses=s.TutorReferralSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: Any = None) -> Response:
        payload = s.GrowthReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        referral = services.reject_tutor_referral(
            self.get_object(), note=payload.validated_data["reason"]
        )
        return Response(self.get_serializer(referral).data)
