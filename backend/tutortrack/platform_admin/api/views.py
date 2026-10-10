"""Platform console API (E30 part 1): ``/api/v1/platform/...`` for TutorTrack staff only."""

from __future__ import annotations

from typing import Any

from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiParameter, extend_schema
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
                "mfa_verified": bool(session and session.mfa_verified),
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
]


class TenantListView(generics.ListAPIView):
    """All organisations with plan, status, MRR and last activity (FR-30-1)."""

    permission_classes = STAFF
    serializer_class = s.TenantRowSerializer
    pagination_class = TenantPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["name", "created_at", "last_activity"]

    def get_queryset(self) -> Any:
        q = self.request.query_params
        return selectors.tenants(
            search=q.get("search", ""), status=q.get("status", ""), plan=q.get("plan", ""),
            region=q.get("region", ""), created_after=_date(q.get("created_after")),
            created_before=_date(q.get("created_before")),
            active_since=_date(q.get("active_since")),
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
