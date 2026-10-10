"""Support access, as the organisation sees it (E30 FR-30-2), and the hand-off link that
starts a support session on the tenant's host."""

from __future__ import annotations

from typing import Any

from django.http import HttpResponseRedirect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.permissions import HasMethodPermission, HasOrganisation

from .. import support
from ..models import SupportAccessGrant, SupportSession


class SupportGrantSerializer(serializers.ModelSerializer):
    granted_by_name = serializers.SerializerMethodField()
    active = serializers.SerializerMethodField()

    class Meta:
        model = SupportAccessGrant
        fields = ["id", "created_at", "expires_at", "allow_write", "note", "revoked_at",
                  "granted_by_name", "active"]  # fmt: skip

    def get_granted_by_name(self, obj: SupportAccessGrant) -> str:
        user = obj.granted_by
        return (user.get_full_name() or user.email) if user else ""

    def get_active(self, obj: SupportAccessGrant) -> bool:
        from tutortrack.core.time import now

        return obj.revoked_at is None and obj.expires_at > now()


class SupportSessionSerializer(serializers.ModelSerializer):
    viewed_as = serializers.EmailField(source="target_membership.user.email")

    class Meta:
        model = SupportSession
        fields = ["id", "staff_name", "viewed_as", "reason", "ticket", "write", "created_at",
                  "entered_at", "ended_at"]  # fmt: skip


class SupportAccessSerializer(serializers.Serializer):
    requires_grant = serializers.BooleanField()
    grants = SupportGrantSerializer(many=True)
    sessions = SupportSessionSerializer(many=True)


class GrantRequestSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=1, max_value=support.MAX_GRANT_DAYS)
    allow_write = serializers.BooleanField(default=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)


def perms(mapping: dict[str, str]) -> list[Any]:
    return [IsAuthenticated, HasOrganisation, HasMethodPermission.for_(mapping)]


class SupportAccessView(APIView):
    """Who from TutorTrack support looked at the account, and the grants in place."""

    permission_classes = perms({"GET": "support.access.view"})

    @extend_schema(responses=SupportAccessSerializer)
    def get(self, request: Request) -> Response:
        from tutortrack.tenancy.settings_service import get_setting

        return Response(
            SupportAccessSerializer(
                {
                    "requires_grant": get_setting("security.support_access_requires_grant"),
                    "grants": SupportAccessGrant.objects.select_related("granted_by")[:20],
                    "sessions": SupportSession.objects.select_related("target_membership__user")[
                        :50
                    ],
                }
            ).data
        )


class SupportGrantsView(APIView):
    permission_classes = perms({"POST": "support.access.manage"})

    @extend_schema(request=GrantRequestSerializer, responses={201: SupportGrantSerializer})
    def post(self, request: Request) -> Response:
        payload = GrantRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        grant = support.grant_access(
            days=payload.validated_data["days"],
            allow_write=payload.validated_data["allow_write"],
            note=payload.validated_data.get("note", ""),
            user=request.user,
        )
        return Response(SupportGrantSerializer(grant).data, status=201)


class RevokeSupportGrantView(APIView):
    permission_classes = perms({"POST": "support.access.manage"})

    @extend_schema(request=None, responses=SupportGrantSerializer)
    def post(self, request: Request, pk: str) -> Response:
        grant = SupportAccessGrant.objects.filter(pk=pk).first()
        if grant is None:
            raise NotFound()
        return Response(SupportGrantSerializer(support.revoke_grant(grant)).data)


class SupportEnterView(APIView):
    """``GET /support/enter?token=``: the single-use link from the platform console."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        parameters=[OpenApiParameter("token", str, required=True)],
        responses={302: None},
    )
    def get(self, request: Request) -> HttpResponseRedirect:
        support.enter(request._request, str(request.query_params.get("token", "")))
        return HttpResponseRedirect("/")
