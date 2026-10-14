"""Platform console API (E30): ``/api/v1/platform/...`` for TutorTrack staff only. Part 2
adds tenant health, SaaS metrics, NPS, product usage and the support inbox."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import filters, generics
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.pagination import CursorPagination
from tutortrack.core.middleware import client_ip
from tutortrack.core.models import FeatureFlag, PlatformNotice
from tutortrack.subscriptions.models import Plan, PlanEntitlement, PlanPrice

from .. import selectors, services
from ..permissions import IsPlatformStaff, ip_allowed
from . import serializers as s

STAFF = [IsAuthenticated, IsPlatformStaff]


class PlatformMeView(APIView):
    """Whether the signed-in user may use the console, and what's missing if not."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=s.PlatformMeSerializer)
    def get(self, request: Request) -> Response:
        session = getattr(request, "user_session", None)
        return Response(
            {
                "email": request.user.email,  # type: ignore[union-attr]
                "is_platform_staff": bool(getattr(request.user, "is_platform_staff", False)),
                # Satisfied when the deployment does not require 2FA for the console
                # (PLATFORM_REQUIRE_MFA=false, e.g. the e2e stack), as IsPlatformStaff does.
                "mfa_verified": bool(session and session.mfa_verified)
                or not settings.PLATFORM_REQUIRE_MFA,
                "network_allowed": ip_allowed(client_ip(request)),
            }
        )


class TenantPagination(CursorPagination):
    ordering = "-created_at"


def _date(value: str | None) -> Any:
    return parse_datetime(value) if value else None


TENANT_FILTERS = [
    OpenApiParameter("search", str),
    OpenApiParameter("status", str),
    OpenApiParameter("plan", str),
    OpenApiParameter("region", str),
    OpenApiParameter("created_after", str, description="ISO datetime"),
    OpenApiParameter("created_before", str, description="ISO datetime"),
    OpenApiParameter("active_since", str, description="ISO datetime"),
    OpenApiParameter("mrr_min", str, description="Latest snapshot MRR at least (G6)"),
    OpenApiParameter("mrr_max", str, description="Latest snapshot MRR at most (G6)"),
    OpenApiParameter("currency", str, description="Billing currency of the MRR filter"),
]


def _decimal(value: str | None) -> Any:
    from decimal import Decimal, InvalidOperation

    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


class TenantListView(generics.ListAPIView):
    """All organisations with plan, status, MRR and last activity (FR-30-1)."""

    permission_classes = STAFF
    serializer_class = s.TenantRowSerializer
    pagination_class = TenantPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["name", "created_at", "last_activity", "latest_mrr"]

    def get_queryset(self) -> Any:
        q = self.request.query_params
        return selectors.tenants(
            search=q.get("search", ""), status=q.get("status", ""), plan=q.get("plan", ""),
            region=q.get("region", ""), created_after=_date(q.get("created_after")),
            created_before=_date(q.get("created_before")),
            active_since=_date(q.get("active_since")),
            mrr_min=_decimal(q.get("mrr_min")), mrr_max=_decimal(q.get("mrr_max")),
            currency=q.get("currency", ""),
        )  # fmt: skip

    @extend_schema(parameters=TENANT_FILTERS)
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class TenantDetailView(APIView):
    permission_classes = STAFF

    @extend_schema(responses=s.TenantDetailSerializer)
    def get(self, request: Request, pk: str) -> Response:
        org = services.organisation(pk)
        return Response(s.TenantDetailSerializer(selectors.tenant_detail(org)).data)


def _detail(pk: Any) -> Response:
    detail = selectors.tenant_detail(services.organisation(pk))
    return Response(s.TenantDetailSerializer(detail).data)


class ExtendTrialView(APIView):
    permission_classes = STAFF

    @extend_schema(request=s.ExtendTrialSerializer, responses=s.TenantDetailSerializer)
    def post(self, request: Request, pk: str) -> Response:
        payload = s.ExtendTrialSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.extend_trial(services.organisation(pk), **payload.validated_data)
        return _detail(pk)


class OverridesView(APIView):
    permission_classes = STAFF

    @extend_schema(request=s.OverrideRequestSerializer, responses=s.TenantDetailSerializer)
    def put(self, request: Request, pk: str) -> Response:
        payload = s.OverrideRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.set_override(services.organisation(pk), user=request.user,
                              **payload.validated_data)  # fmt: skip
        return _detail(pk)


class OverrideView(APIView):
    permission_classes = STAFF

    @extend_schema(responses=s.TenantDetailSerializer)
    def delete(self, request: Request, pk: str, key: str) -> Response:
        services.remove_override(services.organisation(pk), key)
        return _detail(pk)


class SuspendView(APIView):
    permission_classes = STAFF

    @extend_schema(request=s.PlatformReasonSerializer, responses=s.TenantDetailSerializer)
    def post(self, request: Request, pk: str) -> Response:
        payload = s.PlatformReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.suspend(services.organisation(pk), reason=payload.validated_data["reason"])
        return _detail(pk)


class UnsuspendView(APIView):
    permission_classes = STAFF

    @extend_schema(request=None, responses=s.TenantDetailSerializer)
    def post(self, request: Request, pk: str) -> Response:
        services.unsuspend(services.organisation(pk))
        return _detail(pk)


class ChangePlanView(APIView):
    permission_classes = STAFF

    @extend_schema(request=s.PlatformChangePlanSerializer, responses=s.TenantDetailSerializer)
    def post(self, request: Request, pk: str) -> Response:
        payload = s.PlatformChangePlanSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.change_plan(services.organisation(pk), **payload.validated_data)
        return _detail(pk)


class ResendVerificationView(APIView):
    permission_classes = STAFF

    @extend_schema(request=None, responses=s.CountSerializer)
    def post(self, request: Request, pk: str) -> Response:
        return Response({"count": services.resend_owner_verification(services.organisation(pk))})


class ExportView(APIView):
    permission_classes = STAFF

    @extend_schema(request=s.PlatformReasonSerializer, responses={202: None})
    def post(self, request: Request, pk: str) -> Response:
        payload = s.PlatformReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.request_export(services.organisation(pk), reason=payload.validated_data["reason"])
        return Response(status=202)


class ScheduleDeletionView(APIView):
    permission_classes = STAFF

    @extend_schema(request=s.ScheduleDeletionSerializer, responses=s.TenantDetailSerializer)
    def post(self, request: Request, pk: str) -> Response:
        payload = s.ScheduleDeletionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.schedule_deletion(services.organisation(pk), **payload.validated_data)
        return _detail(pk)


class SupportSessionView(APIView):
    """Start viewing the organisation as a member (FR-30-2); returns a single-use link."""

    permission_classes = STAFF

    @extend_schema(request=s.SupportSessionRequestSerializer, responses=s.EnterUrlSerializer)
    def post(self, request: Request, pk: str) -> Response:
        payload = s.SupportSessionRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        url = services.start_support_session(
            services.organisation(pk), staff=request.user, **payload.validated_data
        )
        return Response({"url": url})


# --- feature flags (T03) ------------------------------------------------------------------------


class FlagsView(APIView):
    permission_classes = STAFF

    @extend_schema(responses=s.FlagSerializer(many=True))
    def get(self, request: Request) -> Response:
        flags = FeatureFlag.objects.prefetch_related("overrides__organisation").order_by("key")
        return Response(s.FlagSerializer(flags, many=True).data)

    @extend_schema(request=s.FlagCreateSerializer, responses={201: s.FlagSerializer})
    def post(self, request: Request) -> Response:
        payload = s.FlagCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        flag = services.save_flag(data.pop("key"), **data)
        return Response(s.FlagSerializer(flag).data, status=201)


class FlagView(APIView):
    permission_classes = STAFF

    @extend_schema(request=s.FlagUpdateSerializer, responses=s.FlagSerializer)
    def patch(self, request: Request, key: str) -> Response:
        if not FeatureFlag.objects.filter(key=key).exists():
            raise NotFound()
        payload = s.FlagUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        return Response(s.FlagSerializer(services.save_flag(key, **payload.validated_data)).data)


class FlagOverridesView(APIView):
    permission_classes = STAFF

    @extend_schema(request=s.FlagOverrideRequestSerializer, responses=s.FlagSerializer)
    def put(self, request: Request, key: str) -> Response:
        payload = s.FlagOverrideRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        services.set_flag_override(key, data.pop("organisation"), **data)
        return Response(s.FlagSerializer(FeatureFlag.objects.get(key=key)).data)


class FlagOverrideView(APIView):
    permission_classes = STAFF

    @extend_schema(responses=s.FlagSerializer)
    def delete(self, request: Request, key: str, organisation_id: str) -> Response:
        services.remove_flag_override(key, organisation_id)
        flag = FeatureFlag.objects.filter(key=key).first()
        if flag is None:
            raise NotFound()
        return Response(s.FlagSerializer(flag).data)


# --- operations (T04) ---------------------------------------------------------------------------


class OperationsView(APIView):
    permission_classes = STAFF

    @extend_schema(responses=s.OperationsSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.OperationsSerializer(selectors.operations()).data)


class DeadLetterPagination(CursorPagination):
    ordering = "-dead_lettered_at"


class DeadLetterListView(generics.ListAPIView):
    permission_classes = STAFF
    serializer_class = s.DeadLetterSerializer
    pagination_class = DeadLetterPagination

    def get_queryset(self) -> Any:
        qs = selectors.dead_letters()
        event_type = self.request.query_params.get("event_type")
        return qs.filter(event_type=event_type) if event_type else qs

    @extend_schema(parameters=[OpenApiParameter("event_type", str)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class ReplayView(APIView):
    permission_classes = STAFF

    @extend_schema(request=s.ReplaySerializer, responses=s.CountSerializer)
    def post(self, request: Request) -> Response:
        payload = s.ReplaySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return Response({"count": services.replay(payload.validated_data["ids"])})


# --- status notices (T06) -----------------------------------------------------------------------


class NoticesView(APIView):
    permission_classes = STAFF

    @extend_schema(responses=s.NoticeSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.NoticeSerializer(PlatformNotice.objects.all()[:50], many=True).data)

    @extend_schema(request=s.NoticeSerializer, responses={201: s.NoticeSerializer})
    def post(self, request: Request) -> Response:
        from django.core.cache import cache

        payload = s.NoticeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        notice = payload.save(created_by=request.user)
        cache.delete("platform-notices")
        return Response(s.NoticeSerializer(notice).data, status=201)


class NoticeView(APIView):
    permission_classes = STAFF

    @extend_schema(request=s.NoticeSerializer, responses=s.NoticeSerializer)
    def patch(self, request: Request, pk: str) -> Response:
        from django.core.cache import cache

        notice = PlatformNotice.objects.filter(pk=pk).first()
        if notice is None:
            raise NotFound()
        payload = s.NoticeSerializer(notice, data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        payload.save()
        cache.delete("platform-notices")
        return Response(payload.data)


# --- plans (FR-30-1, E04) -----------------------------------------------------------------------


class PlansView(APIView):
    permission_classes = STAFF

    @extend_schema(responses=s.PlanAdminSerializer(many=True))
    def get(self, request: Request) -> Response:
        plans = Plan.objects.prefetch_related("prices", "entitlements")
        return Response(s.PlanAdminSerializer(plans, many=True).data)


class PlanView(APIView):
    permission_classes = STAFF

    @extend_schema(request=s.PlanAdminSerializer, responses=s.PlanAdminSerializer)
    def patch(self, request: Request, key: str) -> Response:
        plan = Plan.objects.filter(key=key).first()
        if plan is None:
            raise NotFound()
        payload = s.PlanAdminSerializer(plan, data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        payload.save()
        values = request.data.get("entitlements") if isinstance(request.data, dict) else None
        if isinstance(values, dict):
            _save_entitlements(plan, values)
        from tutortrack.subscriptions import entitlements

        entitlements.invalidate_all()
        plan.refresh_from_db()
        return Response(s.PlanAdminSerializer(plan).data)


def _save_entitlements(plan: Plan, values: dict[str, Any]) -> None:
    from tutortrack.subscriptions.catalogue import FEATURES, LIMITS

    for key, value in values.items():
        defaults: dict[str, Any]
        if key in FEATURES:
            defaults = {"bool_value": bool(value), "int_value": None}
        elif key in LIMITS:
            defaults = {"bool_value": None, "int_value": None if value is None else int(value)}
        else:
            continue
        PlanEntitlement.objects.update_or_create(plan=plan, key=key, defaults=defaults)


class PlanPriceView(APIView):
    permission_classes = STAFF

    @extend_schema(request=s.PlanAdminPriceSerializer, responses=s.PlanAdminPriceSerializer)
    def patch(self, request: Request, key: str, price_id: int) -> Response:
        price = PlanPrice.objects.filter(plan__key=key, pk=price_id).first()
        if price is None:
            raise NotFound()
        payload = s.PlanAdminPriceSerializer(price, data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        payload.save()
        return Response(payload.data)


# --- Part 2: health, SaaS metrics, NPS and usage (T09, T10) -------------------------------------


class HealthPagination(CursorPagination):
    ordering = "health_score"


class HealthListView(generics.ListAPIView):
    """Organisations by health score, lowest first (customer success worklist)."""

    permission_classes = STAFF
    serializer_class = s.HealthRowSerializer
    pagination_class = HealthPagination

    def get_queryset(self) -> Any:
        q = self.request.query_params
        return selectors.health_rows(
            risk=q.get("risk", ""), search=q.get("search", ""), plan=q.get("plan", "")
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("risk", str, enum=["healthy", "watch", "at_risk"]),
            OpenApiParameter("search", str),
            OpenApiParameter("plan", str),
        ]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class RiskCountsView(APIView):
    permission_classes = STAFF

    @extend_schema(responses=s.RiskCountsSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.RiskCountsSerializer(selectors.risk_counts()).data)


class TenantHealthView(APIView):
    """One organisation's daily health scores (last 90 days, newest first)."""

    permission_classes = STAFF

    @extend_schema(responses=s.HealthPointSerializer(many=True))
    def get(self, request: Request, pk: str) -> Response:
        rows = selectors.health_history(services.organisation(pk))
        return Response(s.HealthPointSerializer(rows, many=True).data)


class InsightsRunView(APIView):
    """Start the nightly insights run now (health scores and subscription snapshots)."""

    permission_classes = STAFF

    @extend_schema(request=None, responses={202: s.InsightsRunSerializer})
    def post(self, request: Request) -> Response:
        return Response({"workflow_id": services.run_insights_now()}, status=202)


class SaasMetricsView(APIView):
    """MRR/ARR, MRR movements, churn, NRR, ARPA, trial conversion and cohort retention per
    billing currency, from the nightly subscription snapshots (FR-30-7)."""

    permission_classes = STAFF

    @extend_schema(
        parameters=[
            OpenApiParameter("currency", str, description="ISO code; default GBP"),
            OpenApiParameter("months", int, description="1-36, default 12"),
        ],
        responses=s.SaasMetricsSerializer,
        examples=[
            OpenApiExample(
                "One month",
                response_only=True,
                value={
                    "currency": "GBP",
                    "currencies": ["GBP", "USD"],
                    "months": [
                        {
                            "month": "2026-10-14",
                            "mrr": {"amount": "1250.00", "currency": "GBP"},
                            "arr": {"amount": "15000.00", "currency": "GBP"},
                            "customers": 25,
                            "arpa": {"amount": "50.00", "currency": "GBP"},
                            "trialing": 8,
                            "past_due_mrr": {"amount": "49.00", "currency": "GBP"},
                            "new_mrr": {"amount": "98.00", "currency": "GBP"},
                            "reactivation_mrr": {"amount": "0.00", "currency": "GBP"},
                            "expansion_mrr": {"amount": "30.00", "currency": "GBP"},
                            "contraction_mrr": {"amount": "0.00", "currency": "GBP"},
                            "churned_mrr": {"amount": "49.00", "currency": "GBP"},
                            "net_new_mrr": {"amount": "79.00", "currency": "GBP"},
                            "new_customers": 2,
                            "churned_customers": 1,
                            "logo_churn_rate": "0.0417",
                            "revenue_churn_rate": "0.0418",
                            "net_revenue_retention": "0.9838",
                        }
                    ],
                    "trial_conversion": [
                        {
                            "month": "2026-09-01",
                            "trials": 10,
                            "converted": 3,
                            "conversion_rate": "0.3000",
                        }
                    ],
                    "cohorts": [],
                },
            )
        ],
    )
    def get(self, request: Request) -> Response:
        q = request.query_params
        try:
            months = int(q.get("months", "12"))
        except ValueError:
            months = 12
        data = selectors.saas_metrics(currency=q.get("currency", "").upper(), months=months)
        return Response(s.SaasMetricsSerializer(data).data)


class NpsSummaryView(APIView):
    permission_classes = STAFF

    @extend_schema(
        parameters=[OpenApiParameter("days", int, description="Window, default 90")],
        responses=s.NpsSummarySerializer,
    )
    def get(self, request: Request) -> Response:
        days = _days(request, 90)
        return Response(s.NpsSummarySerializer(selectors.nps_summary(days)).data)


class UsageSummaryView(APIView):
    """Feature usage (consented, pseudonymous events) and the onboarding funnel."""

    permission_classes = STAFF

    @extend_schema(
        parameters=[OpenApiParameter("days", int, description="Window, default 30")],
        responses=s.UsageSummarySerializer,
    )
    def get(self, request: Request) -> Response:
        days = _days(request, 30)
        return Response(s.UsageSummarySerializer(selectors.usage_summary(days)).data)


def _days(request: Request, default: int) -> int:
    try:
        return max(1, min(int(request.query_params.get("days", default)), 365))
    except ValueError:
        return default


# --- Part 2: support inbox (T08) ----------------------------------------------------------------


class SupportInboxPagination(CursorPagination):
    ordering = "-last_message_at"


class SupportInboxView(generics.ListAPIView):
    """Support conversations from every organisation, newest activity first."""

    permission_classes = STAFF
    serializer_class = s.PlatformSupportRowSerializer
    pagination_class = SupportInboxPagination

    def get_queryset(self) -> Any:
        q = self.request.query_params
        return selectors.support_inbox(status=q.get("status", ""), search=q.get("search", ""))

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, enum=["open", "answered", "closed", "unread"]),
            OpenApiParameter("search", str),
        ]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class SupportConversationView(APIView):
    permission_classes = STAFF

    @extend_schema(responses=s.PlatformSupportDetailSerializer)
    def get(self, request: Request, pk: str) -> Response:
        conversation = services.support_conversation(pk)
        return Response(s.PlatformSupportDetailSerializer(conversation).data)


class SupportReplyView(APIView):
    permission_classes = STAFF

    @extend_schema(
        request=s.PlatformSupportReplySerializer,
        responses={201: s.PlatformSupportDetailSerializer},
        examples=[
            OpenApiExample(
                "Answer",
                value={"body": "Go to Billing and select 'Invoice run'."},
                request_only=True,
            )
        ],
    )
    def post(self, request: Request, pk: str) -> Response:
        payload = s.PlatformSupportReplySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        conversation = services.support_reply(
            pk, staff=request.user, body=payload.validated_data["body"]
        )
        return Response(s.PlatformSupportDetailSerializer(conversation).data, status=201)


class SupportCloseView(APIView):
    permission_classes = STAFF

    @extend_schema(request=None, responses=s.PlatformSupportDetailSerializer)
    def post(self, request: Request, pk: str) -> Response:
        return Response(s.PlatformSupportDetailSerializer(services.support_close(pk)).data)


class SupportAssignView(APIView):
    """Assign the conversation to the signed-in staff member."""

    permission_classes = STAFF

    @extend_schema(request=None, responses=s.PlatformSupportDetailSerializer)
    def post(self, request: Request, pk: str) -> Response:
        conversation = services.support_assign(pk, staff=request.user)
        return Response(s.PlatformSupportDetailSerializer(conversation).data)


# --- G6: notify customers (FR-29-9) -------------------------------------------------------------


class NoticeTemplatesView(APIView):
    """Templates for customer notices (breach, security, service, legal)."""

    permission_classes = STAFF

    @extend_schema(responses=s.NoticeTemplateSerializer(many=True))
    def get(self, request: Request) -> Response:
        from .. import notices

        return Response(s.NoticeTemplateSerializer(notices.templates(), many=True).data)


class CustomerNoticesView(APIView):
    """Customer notices: the history (``GET``) and a new draft (``POST``)."""

    permission_classes = STAFF

    @extend_schema(responses=s.CustomerNoticeSerializer(many=True))
    def get(self, request: Request) -> Response:
        from ..models import CustomerNotice

        rows = CustomerNotice.objects.all()[:100]
        return Response(s.CustomerNoticeSerializer(rows, many=True).data)

    @extend_schema(
        request=s.CustomerNoticeSerializer,
        responses={201: s.CustomerNoticeSerializer},
        examples=[
            OpenApiExample(
                "A breach notice to everyone",
                request_only=True,
                value={
                    "template": "breach",
                    "variables": {
                        "summary": "A support laptop with an export was stolen.",
                        "when": "14 October 2026, 09:00 UTC",
                        "data_affected": "Client names and email addresses",
                        "actions_taken": "Disk encryption confirmed; device wiped remotely.",
                        "your_actions": "None needed; you may tell your regulator.",
                        "contact": "security@tutortrack.app",
                    },
                    "organisation_ids": [],
                },
            )
        ],
    )
    def post(self, request: Request) -> Response:
        from .. import notices

        payload = s.CustomerNoticeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        notice = notices.create_notice(
            template=d["template"],
            variables=d.get("variables") or {},
            organisation_ids=[str(i) for i in d.get("organisation_ids") or []],
            subject=d.get("subject", ""),
            body=d.get("body", ""),
            user=request.user,
        )
        return Response(s.CustomerNoticeSerializer(notice).data, status=201)


def _notice(pk: str) -> Any:
    from ..models import CustomerNotice

    notice = CustomerNotice.objects.filter(pk=pk).first()
    if notice is None:
        raise NotFound()
    return notice


class CustomerNoticePreviewView(APIView):
    permission_classes = STAFF

    @extend_schema(responses=s.CustomerNoticePreviewSerializer)
    def get(self, request: Request, pk: str) -> Response:
        from .. import notices

        return Response(s.CustomerNoticePreviewSerializer(notices.preview(_notice(pk))).data)


class CustomerNoticeSendView(APIView):
    """Send a draft notice (once) to the chosen organisations' owners and admins."""

    permission_classes = STAFF

    @extend_schema(request=s.PlatformReasonSerializer, responses=s.CustomerNoticeSerializer)
    def post(self, request: Request, pk: str) -> Response:
        from .. import notices

        payload = s.PlatformReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        notice = notices.send(
            _notice(pk), reason=payload.validated_data["reason"], user=request.user
        )
        return Response(s.CustomerNoticeSerializer(notice).data)


# --- G6: revenue share (FR-30-7) ----------------------------------------------------------------


def _month(value: str | None) -> Any:
    from datetime import date

    if value:
        try:
            year, month = (int(p) for p in value.split("-")[:2])
            return date(year, month, 1)
        except (TypeError, ValueError):
            pass
    from tutortrack.core.time import now

    today = now().date()
    return today.replace(day=1)


class RevenueShareView(APIView):
    """Revenue-share reconciliation for a month (``?month=YYYY-MM``, default this month):
    payments processed vs what was reported to the Stripe meter, per organisation."""

    permission_classes = STAFF

    @extend_schema(
        parameters=[OpenApiParameter("month", str)], responses=s.RevenueShareReportSerializer
    )
    def get(self, request: Request) -> Response:
        from .. import revenue_share

        month = _month(request.query_params.get("month"))
        return Response(s.RevenueShareReportSerializer(revenue_share.reconcile(month)).data)


class RevenueShareFixView(APIView):
    """Report an organisation's unreported days for a month to the meter (audited)."""

    permission_classes = STAFF

    @extend_schema(request=s.RevenueShareFixSerializer, responses=s.CountSerializer)
    def post(self, request: Request) -> Response:
        from .. import revenue_share

        payload = s.RevenueShareFixSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        count = revenue_share.report_missing(str(d["organisation_id"]), _month(d["month"]))
        return Response({"count": count})


# --- G6: failed and stuck workflows (FR-32-10) --------------------------------------------------


class WorkflowPagination(CursorPagination):
    ordering = "-updated_at"


class PlatformWorkflowListView(generics.ListAPIView):
    """Failed and stuck durable processes across organisations, with Temporal UI links.
    ``?state=failed|stuck``, ``?process=``, ``?organisation=``, ``?search=``."""

    permission_classes = STAFF
    serializer_class = s.PlatformWorkflowSerializer
    pagination_class = WorkflowPagination

    def get_queryset(self) -> Any:
        from .. import workflow_console

        q = self.request.query_params
        return workflow_console.problems(
            state=q.get("state", ""),
            process=q.get("process", ""),
            organisation_id=q.get("organisation", ""),
            search=q.get("search", ""),
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("state", str, enum=["failed", "stuck"]),
            OpenApiParameter("process", str),
            OpenApiParameter("organisation", str),
            OpenApiParameter("search", str),
        ]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class PlatformWorkflowActionView(APIView):
    """Terminate, reset or retry one process (a reason is required; audited in the
    organisation's log). ``GET`` refreshes its status from Temporal."""

    permission_classes = STAFF

    @extend_schema(responses=s.PlatformWorkflowSerializer)
    def get(self, request: Request, organisation_id: str, workflow_id: str) -> Response:
        from .. import workflow_console

        link = workflow_console.refresh(organisation_id, workflow_id)
        return Response(s.PlatformWorkflowSerializer(link).data)

    @extend_schema(request=s.WorkflowActionSerializer, responses=s.PlatformWorkflowSerializer)
    def post(self, request: Request, organisation_id: str, workflow_id: str) -> Response:
        from .. import workflow_console

        payload = s.WorkflowActionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        link = workflow_console.act(organisation_id, workflow_id, d["action"], reason=d["reason"])
        return Response(s.PlatformWorkflowSerializer(link).data)
