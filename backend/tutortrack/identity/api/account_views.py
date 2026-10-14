"""``/me/account-deletion``: delete your whole TutorTrack account (G6, FR-03-9)."""

from __future__ import annotations

from django.contrib.auth import logout
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .. import account_deletion
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
