"""Account self-service added in gap batch G2: change your sign-in email (FR-03-9)."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .. import email_change
from .views import _user


class EmailChangeRequestSerializer(serializers.Serializer):
    new_email = serializers.EmailField()
    password = serializers.CharField(
        trim_whitespace=False,
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Your current password (required when the account has one).",
    )


class EmailChangePendingSerializer(serializers.Serializer):
    pending_email = serializers.EmailField()


class EmailChangeConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()


class EmailChangeDoneSerializer(serializers.Serializer):
    email = serializers.EmailField()


class EmailChangeView(APIView):
    """Ask to change your sign-in email: a link goes to the new address, a notice to the
    old one. Nothing changes until the link is used."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    @extend_schema(
        request=EmailChangeRequestSerializer,
        responses={202: EmailChangePendingSerializer},
        examples=[
            OpenApiExample(
                "Change email",
                value={"new_email": "sam.new@example.com", "password": "correct horse"},
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        serializer = EmailChangeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = email_change.request_change(
            request._request,
            _user(request),
            new_email=serializer.validated_data["new_email"],
            password=serializer.validated_data.get("password", ""),
        )
        return Response({"pending_email": email}, status=status.HTTP_202_ACCEPTED)


class EmailChangeConfirmView(APIView):
    """Confirm a new email from the emailed link (works signed in or not)."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "verify_email"

    @extend_schema(
        request=EmailChangeConfirmSerializer,
        responses={200: EmailChangeDoneSerializer},
        examples=[OpenApiExample("Confirm", value={"token": "eyJ1Ijoi..."}, request_only=True)],
    )
    def post(self, request: Request) -> Response:
        serializer = EmailChangeConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = email_change.confirm_change(
            serializer.validated_data["token"], request=request._request
        )
        return Response({"email": user.email})
