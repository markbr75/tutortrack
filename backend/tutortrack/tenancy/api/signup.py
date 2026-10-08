"""Signup, email verification and session handoff endpoints (E02-T06)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth import login
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tutortrack.core.captcha import verify_turnstile
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.middleware import client_ip
from tutortrack.identity import services as identity
from tutortrack.identity.models import User
from tutortrack.identity.tokens import InvalidToken, consume_handoff_token, handoff_token

from .. import slugs
from ..models import Organisation
from ..signup import sign_up

SESSION_BACKEND = "django.contrib.auth.backends.ModelBackend"


class InvalidTokenProblem(BusinessRuleViolation):
    status_code = 400
    problem_type = "invalid-token"
    title = "This link is invalid or has expired"


class CaptchaFailed(BusinessRuleViolation):
    status_code = 400
    problem_type = "captcha-failed"
    title = "Please complete the security check"


class SignupRequestSerializer(serializers.Serializer):
    business_name = serializers.CharField(max_length=200)
    country = serializers.RegexField(r"^[A-Za-z]{2}$", help_text="ISO 3166-1 alpha-2")
    business_type = serializers.ChoiceField(
        choices=Organisation.BusinessType.choices, default=Organisation.BusinessType.SOLE_TRADER
    )
    slug = serializers.CharField(max_length=63, required=False, allow_blank=True)
    timezone = serializers.CharField(max_length=64, required=False, allow_blank=True)
    first_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
    )
    turnstile_token = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        request = self.context["request"]
        if not request.user.is_authenticated:
            missing = {
                k: [_("This field is required.")]
                for k in ("email", "password", "first_name")
                if not attrs.get(k)
            }
            if missing:
                raise serializers.ValidationError(missing)
        return attrs


class SignupOrganisationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    url = serializers.CharField()


class SignupUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    email_verified = serializers.BooleanField()


class SignupResponseSerializer(serializers.Serializer):
    user = SignupUserSerializer()
    organisation = SignupOrganisationSerializer()
    continue_url = serializers.CharField(
        help_text="Open this to continue onboarding on the new organisation's address."
    )


class SignupView(APIView):
    """Create an organisation, and a login for new people (FR-02-6).

    Signed-in users may call it to add another organisation (no credentials needed).
    Public, rate-limited per IP and protected by Cloudflare Turnstile.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "signup"

    @extend_schema(
        request=SignupRequestSerializer,
        responses={201: SignupResponseSerializer},
        examples=[
            OpenApiExample(
                "New tutor",
                value={
                    "first_name": "Sam",
                    "last_name": "Patel",
                    "email": "sam@example.com",
                    "password": "a-long-passphrase",
                    "business_name": "Sam Patel Tutoring",
                    "country": "GB",
                    "business_type": "sole_trader",
                    "timezone": "Europe/London",
                    "turnstile_token": "<token from the widget>",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        payload = SignupRequestSerializer(data=request.data, context={"request": request})
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        if not verify_turnstile(data.get("turnstile_token", ""), client_ip(request)):
            raise CaptchaFailed()
        signed_in = request.user if request.user.is_authenticated else None
        result = sign_up(
            user=signed_in,
            business_name=data["business_name"],
            country=data["country"],
            business_type=data["business_type"],
            slug=data.get("slug") or None,
            timezone=data.get("timezone") or None,
            email=data.get("email", ""),
            password=data.get("password", ""),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
        )
        if signed_in is None:
            login(request, result.user, backend=SESSION_BACKEND)
        org = result.organisation
        token = handoff_token(result.user, org.pk)
        return Response(
            {
                "user": {
                    "id": result.user.pk,
                    "email": result.user.email,
                    "email_verified": result.user.email_verified_at is not None,
                },
                "organisation": {
                    "id": org.pk,
                    "name": org.name,
                    "slug": org.slug,
                    "url": org.base_url,
                },
                "continue_url": f"{org.base_url}/onboarding?handoff={token}",
            },
            status=status.HTTP_201_CREATED,
        )


class SignupConfigSerializer(serializers.Serializer):
    turnstile_site_key = serializers.CharField(allow_blank=True)


class SignupConfigView(APIView):
    """Public configuration for the signup form."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(responses=SignupConfigSerializer)
    def get(self, request: Request) -> Response:
        return Response({"turnstile_site_key": settings.TURNSTILE_SITE_KEY})


class SlugCheckSerializer(serializers.Serializer):
    slug = serializers.CharField()
    available = serializers.BooleanField()
    reason = serializers.CharField(allow_null=True)
    suggestion = serializers.CharField(allow_null=True)


class SlugCheckView(APIView):
    """Is a subdomain available? Optionally suggests one from a business name."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "verify_email"

    @extend_schema(
        parameters=[
            OpenApiParameter("slug", str, description="Subdomain to check."),
            OpenApiParameter("name", str, description="Business name to suggest a slug from."),
        ],
        responses=SlugCheckSerializer,
    )
    def get(self, request: Request) -> Response:
        slug = slugs.normalise(request.query_params.get("slug", ""))
        name = request.query_params.get("name", "")
        suggestion = slugs.suggest_slug(name) if name else None
        if not slug:
            slug = suggestion or ""
        reason = slugs.slug_problem(slug) if slug else _("Enter a subdomain.")
        return Response(
            {"slug": slug, "available": reason is None, "reason": reason, "suggestion": suggestion}
        )


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField()


class VerifyEmailView(APIView):
    """Confirm an email address from the link in the verification email."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "verify_email"

    @extend_schema(request=TokenSerializer, responses={200: SignupUserSerializer})
    def post(self, request: Request) -> Response:
        payload = TokenSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            user = identity.verify_email(payload.validated_data["token"])
        except InvalidToken as exc:
            raise InvalidTokenProblem() from exc
        return Response({"id": user.pk, "email": user.email, "email_verified": True})


class ResendVerificationView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "verify_email"

    @extend_schema(request=None, responses={202: None})
    def post(self, request: Request) -> Response:
        user = request.user
        if isinstance(user, User) and user.email_verified_at is None:
            identity.send_verification_email(user)
        return Response(status=status.HTTP_202_ACCEPTED)


class HandoffView(APIView):
    """Exchange a signup handoff token for a session on this organisation's host."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "handoff"

    @extend_schema(request=TokenSerializer, responses={200: SignupUserSerializer})
    def post(self, request: Request) -> Response:
        organisation = getattr(request, "organisation", None)
        if organisation is None:
            raise NotFound()
        payload = TokenSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            user = consume_handoff_token(payload.validated_data["token"], organisation.pk)
        except InvalidToken as exc:
            raise InvalidTokenProblem() from exc
        login(request, user, backend=SESSION_BACKEND)
        return Response(
            {
                "id": user.pk,
                "email": user.email,
                "email_verified": user.email_verified_at is not None,
            }
        )
