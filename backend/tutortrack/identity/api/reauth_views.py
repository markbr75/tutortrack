"""Step-up re-authentication API (gap G3): ``/auth/reauthenticate`` (+ ``/options``)."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .. import reauth
from .phase2_views import PublicKeyOptionsSerializer


class ReauthStatusSerializer(serializers.Serializer):
    recent = serializers.BooleanField(help_text="Confirmed within the last few minutes")
    methods = serializers.ListField(
        child=serializers.ChoiceField(choices=["password", "totp", "passkey"])
    )


class ReauthRequestSerializer(serializers.Serializer):
    password = serializers.CharField(required=False, allow_blank=True, default="")
    code = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="Authenticator or recovery code"
    )
    credential = serializers.DictField(
        required=False, allow_null=True, default=None, help_text="Passkey assertion"
    )


class ReauthView(APIView):
    """Confirm it's you before seeing sensitive details (e.g. full bank details)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa"

    @extend_schema(responses=ReauthStatusSerializer)
    def get(self, request: Request) -> Response:
        return Response(
            {"recent": reauth.is_recent(request._request), "methods": reauth.methods(request.user)}
        )

    @extend_schema(
        request=ReauthRequestSerializer,
        responses=ReauthStatusSerializer,
        examples=[
            OpenApiExample("Password", value={"password": "correct horse"}, request_only=True)
        ],
    )
    def post(self, request: Request) -> Response:
        payload = ReauthRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        reauth.confirm(
            request._request,
            password=data["password"],
            code=data["code"],
            credential=data["credential"],
        )
        return Response({"recent": True, "methods": reauth.methods(request.user)})


class ReauthOptionsView(APIView):
    """Passkey options for re-authentication (the challenge is kept in the session)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa"

    @extend_schema(request=None, responses=PublicKeyOptionsSerializer)
    def post(self, request: Request) -> Response:
        return Response(reauth.passkey_options(request._request))
