"""Account self-service: change your sign-in email (G2) and delete your whole TutorTrack
account (G6), both FR-03-9."""

from __future__ import annotations

from django.contrib.auth import logout
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .. import account_deletion, email_change
from ..impersonation import SESSION_KEY as IMPERSONATION_KEY
from ..models import User


class AccountDeletionOrganisationSerializer(serializers.Serializer):
    organisation_id = serializers.CharField()
    name = serializers.CharField()
    role = serializers.CharField(required=False)
    outcome = serializers.CharField(help_text="erased | request_logged")
    reference = serializers.CharField(required=False, allow_blank=True)


class AccountDeletionBlockerSerializer(serializers.Serializer):
    organisation_id = serializers.CharField(allow_blank=True)
    organisation_name = serializers.CharField()
    reason = serializers.CharField(help_text="last_owner | platform_staff")


class AccountDeletionPreviewSerializer(serializers.Serializer):
    organisations = AccountDeletionOrganisationSerializer(many=True)
    blockers = AccountDeletionBlockerSerializer(many=True)
    needs_password = serializers.BooleanField()


class AccountDeletionRequestSerializer(serializers.Serializer):
    password = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False, write_only=True
    )
    confirm_email = serializers.CharField(
        required=False, allow_blank=True, help_text="Without a password: type your email."
    )
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class AccountDeletionResultSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    completed_at = serializers.DateTimeField()
    organisations = AccountDeletionOrganisationSerializer(many=True)


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied()
    return request.user


class AccountDeletionView(APIView):
    """What deleting your account will do (GET), and deleting it (POST). Organisations you
    are the last owner of must be handed over or closed first."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "verify_email"

    @extend_schema(responses=AccountDeletionPreviewSerializer)
    def get(self, request: Request) -> Response:
        return Response(
            AccountDeletionPreviewSerializer(account_deletion.preview(_user(request))).data
        )

    @extend_schema(
        request=AccountDeletionRequestSerializer,
        responses=AccountDeletionResultSerializer,
        examples=[
            OpenApiExample(
                "Delete my account",
                request_only=True,
                value={"password": "my-current-password", "reason": "Not tutoring any more"},
            )
        ],
    )
    def post(self, request: Request) -> Response:
        if request.session.get(IMPERSONATION_KEY):
            raise PermissionDenied()  # never while someone is acting as the person
        payload = AccountDeletionRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        record = account_deletion.delete_account(_user(request), **payload.validated_data)
        logout(request._request)
        return Response(AccountDeletionResultSerializer(record).data)


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
