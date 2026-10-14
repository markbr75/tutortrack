"""Background check API (E18-T11, FR-18-7): providers, starting and tracking checks from
the tutor record, the audited result view, the tutor's own checks and provider webhooks."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
)
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.permissions import scope_queryset
from tutortrack.people.models import TutorProfile

from .. import background_checks, checks
from ..models import BackgroundCheck, RequirementType
from .views import AUTH, perms


class BackgroundCheckSerializer(serializers.ModelSerializer):
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)
    provider_label = serializers.SerializerMethodField()
    requirement_name = serializers.CharField(
        source="requirement.name", read_only=True, default=None
    )
    verification_link = serializers.SerializerMethodField()

    class Meta:
        model = BackgroundCheck
        fields = [
            "id",
            "tutor",
            "tutor_name",
            "provider",
            "provider_label",
            "package",
            "requirement",
            "requirement_name",
            "record",
            "status",
            "result",
            "external_id",
            "certificate_issue_date",
            "certificate_expiry_date",
            "state_code",
            "consent_at",
            "completed_at",
            "last_checked_at",
            "checks_run",
            "error",
            "reviewed_at",
            "details_purged_at",
            "verification_link",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_provider_label(self, obj: BackgroundCheck) -> str:
        provider = checks.PROVIDERS.get(obj.provider)
        return str(provider.label) if provider else obj.provider

    @extend_schema_field(serializers.CharField())
    def get_verification_link(self, obj: BackgroundCheck) -> str:
        """AU WWCC: the state's verification page for staff."""
        return checks.WWCC_LINKS.get(obj.state_code, "") if obj.provider == "wwcc" else ""


class MyBackgroundCheckSerializer(BackgroundCheckSerializer):
    invite_url = serializers.SerializerMethodField()

    class Meta(BackgroundCheckSerializer.Meta):
        fields = [
            "id",
            "provider",
            "provider_label",
            "package",
            "status",
            "result",
            "invite_url",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_invite_url(self, obj: BackgroundCheck) -> str:
        """The link the tutor follows to complete the check (only while it's open)."""
        return obj.invite_url if obj.status in background_checks.OPEN else ""


class CheckRequestSerializer(serializers.Serializer):
    tutor = serializers.UUIDField()
    provider = serializers.ChoiceField(choices=sorted(checks.PROVIDERS))
    package = serializers.CharField(required=False, allow_blank=True, max_length=40)
    requirement = serializers.UUIDField(required=False, allow_null=True)
    consent = serializers.BooleanField(help_text="The tutor has agreed to the check.")
    certificate_number = serializers.CharField(required=False, allow_blank=True, max_length=40)
    state_code = serializers.CharField(required=False, allow_blank=True, max_length=3)


class CheckOutcomeSerializer(serializers.Serializer):
    result = serializers.ChoiceField(choices=["clear", "consider", "unable"])
    certificate_number = serializers.CharField(required=False, allow_blank=True, max_length=40)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


class CheckDetailsSerializer(serializers.Serializer):
    certificate_number = serializers.CharField()
    report_url = serializers.CharField()
    summary = serializers.DictField()
    purged = serializers.BooleanField()


class CheckProviderSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    countries = serializers.ListField(child=serializers.CharField())
    recommended = serializers.BooleanField()
    packages = serializers.ListField(child=serializers.DictField())
    connected = serializers.BooleanField()
    needs_connection = serializers.BooleanField()
    manual = serializers.BooleanField()


class BackgroundCheckViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """``/background-checks``: online checks started from the tutor record."""

    model = BackgroundCheck
    serializer_class = BackgroundCheckSerializer
    permission_classes = perms({"GET": "compliance.view", "POST": "compliance.checks.request"})

    def get_tenant_queryset(self) -> Any:
        qs = BackgroundCheck.objects.select_related("tutor", "requirement")
        tutor = self.request.query_params.get("tutor")
        if tutor:
            qs = qs.filter(tutor_id=tutor)
        return scope_queryset(self.request.user, qs, "compliance.view")

    def _check(self, pk: Any) -> BackgroundCheck:
        return get_object_or_404(self.get_tenant_queryset(), pk=pk)

    @extend_schema(parameters=[OpenApiParameter("tutor", str)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=CheckRequestSerializer,
        responses={201: BackgroundCheckSerializer},
        examples=[
            OpenApiExample(
                "Enhanced DBS through uCheck",
                value={
                    "tutor": "3f1c3c9e-6a59-4a39-8a68-2a0d7f5b2b10",
                    "provider": "ucheck",
                    "package": "enhanced_barred",
                    "consent": True,
                },
            )
        ],
    )
    def create(self, request: Request) -> Response:
        payload = CheckRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        tutor = get_object_or_404(TutorProfile.objects.all(), pk=data["tutor"])
        requirement = (
            get_object_or_404(RequirementType.objects.all(), pk=data["requirement"])
            if data.get("requirement")
            else None
        )
        check = background_checks.request_check(
            tutor,
            provider=data["provider"],
            user=request.user,
            consent=data["consent"],
            package=data.get("package", ""),
            requirement=requirement,
            certificate_number=data.get("certificate_number", ""),
            state_code=data.get("state_code", ""),
        )
        return Response(BackgroundCheckSerializer(check).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=BackgroundCheckSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        check = background_checks.cancel(self._check(pk), user=request.user)
        return Response(BackgroundCheckSerializer(check).data)

    @extend_schema(request=None, responses=BackgroundCheckSerializer)
    @action(detail=True, methods=["post"])
    def refresh(self, request: Request, pk: Any = None) -> Response:
        """Ask the provider now (signals the check's workflow)."""
        check = self._check(pk)
        background_checks._signal(check, "updated")
        return Response(BackgroundCheckSerializer(check).data)

    @extend_schema(request=CheckOutcomeSerializer, responses=BackgroundCheckSerializer)
    @action(detail=True, methods=["post"])
    def outcome(self, request: Request, pk: Any = None) -> Response:
        """Record a manual (AU WWCC) outcome or confirm a "needs review" result."""
        payload = CheckOutcomeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        check = background_checks.record_outcome(
            self._check(pk), user=request.user, **payload.validated_data
        )
        return Response(BackgroundCheckSerializer(check).data)

    @extend_schema(responses=CheckDetailsSerializer)
    @action(detail=True, methods=["get"])
    def details(self, request: Request, pk: Any = None) -> Response:
        """Result, certificate number and report link: ``compliance.checks.results``,
        audited."""
        return Response(background_checks.details(self._check(pk), user=request.user))

    @extend_schema(responses=CheckProviderSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def providers(self, request: Request) -> Response:
        return Response(background_checks.available())


class MyBackgroundChecksView(APIView):
    """``GET /me/background-checks``: the tutor's own checks with their invitation links."""

    permission_classes = AUTH

    @extend_schema(responses=MyBackgroundCheckSerializer(many=True))
    def get(self, request: Request) -> Response:
        tutor = TutorProfile.objects.filter(membership__user=request.user).first()
        if tutor is None:
            raise NotFound("You're not a tutor here.")
        checks_ = BackgroundCheck.objects.filter(tutor=tutor).order_by("-created_at")[:50]
        return Response(MyBackgroundCheckSerializer(checks_, many=True).data)


@csrf_exempt
def background_check_webhook(request: HttpRequest, provider: str) -> HttpResponse:
    """``POST /webhooks/background-checks/{provider}`` (Checkr): signed with the account's
    API key; routed by the candidate id."""
    if request.method != "POST":
        return HttpResponse(status=405)
    ok = background_checks.handle_webhook(provider, request.body, dict(request.headers))
    return HttpResponse(status=200 if ok else 400)
