"""Consent API (E29 FR-29-3)."""

from __future__ import annotations

import dataclasses
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core import audit
from tutortrack.core.api.serializers import BaseModelSerializer
from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation

from .. import services, subjects
from ..models import ConsentRecord, ConsentType


class ConsentTypeSerializer(BaseModelSerializer):
    class Meta:
        model = ConsentType
        fields = [
            "id", "key", "name", "description", "category", "version", "document_url",
            "required", "applies_to", "is_active", "created_at",
        ]  # fmt: skip
        read_only_fields = ["id", "version", "created_at"]

    def validate_applies_to(self, value: Any) -> list[str]:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise serializers.ValidationError("A list of subject types.")
        return value


class ConsentRecordSerializer(BaseModelSerializer):
    consent_type = serializers.CharField(source="consent_type.key", read_only=True)

    class Meta:
        model = ConsentRecord
        fields = [
            "id", "consent_type", "version", "subject_type", "subject_id", "granted",
            "method", "given_by", "given_by_name", "on_behalf_of_child", "ip", "recorded_at",
        ]  # fmt: skip
        read_only_fields = fields


class RecordConsentSerializer(serializers.Serializer):
    subject_type = serializers.CharField(max_length=60)
    subject_id = serializers.CharField(max_length=64)
    consent_type = serializers.SlugField()
    granted = serializers.BooleanField()
    method = serializers.ChoiceField(
        choices=[
            ConsentRecord.Method.STAFF,
            ConsentRecord.Method.FORM,
            ConsentRecord.Method.IMPORT,
        ],
        default=ConsentRecord.Method.STAFF,
    )
    given_by_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    on_behalf_of_child = serializers.BooleanField(default=False)


class ConsentStatusSerializer(serializers.Serializer):
    # Declared in get_fields(): "required" clashes with DRF Field's own attribute.
    def get_fields(self) -> dict[str, serializers.Field]:
        return {
            "key": serializers.CharField(),
            "name": serializers.CharField(),
            "category": serializers.CharField(),
            "required": serializers.BooleanField(),
            "current_version": serializers.IntegerField(),
            "granted": serializers.BooleanField(allow_null=True),
            "version": serializers.IntegerField(allow_null=True),
            "recorded_at": serializers.DateTimeField(allow_null=True),
            "needs_reconsent": serializers.BooleanField(),
        }


class MyConsentSerializer(serializers.Serializer):
    consent_type = serializers.SlugField()
    granted = serializers.BooleanField()


class ConsentRecordFilter(filters.FilterSet):
    subject_type = filters.CharFilter()
    subject_id = filters.CharFilter()
    consent_type = filters.CharFilter(field_name="consent_type__key")

    class Meta:
        model = ConsentRecord
        fields: list[str] = []


VIEW = "privacy.consent.view"


class ConsentTypeViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Consent types. Edit wording freely; use ``new-version`` for material changes."""

    model = ConsentType
    serializer_class = ConsentTypeSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_classes = [
        IsAuthenticated,
        HasOrganisation,
        HasMethodPermission.for_({"GET": VIEW, "*": "privacy.consent.manage"}),
    ]

    def get_tenant_queryset(self) -> QuerySet[ConsentType]:
        return ConsentType.objects.all()

    def perform_create(self, serializer: Any) -> None:
        with transaction.atomic():
            serializer.save()
            audit.record_create(serializer.instance)

    def perform_update(self, serializer: Any) -> None:
        with transaction.atomic(), audit.track(serializer.instance):
            serializer.save()

    @extend_schema(request=None, responses=ConsentTypeSerializer)
    @action(detail=True, methods=["post"], url_path="new-version")
    def new_version(self, request: Request, pk: Any = None) -> Response:
        """Everyone who consented to an older version is asked again."""
        return Response(self.get_serializer(services.publish_new_version(self.get_object())).data)


class ConsentRecordViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Consent history (append-only). ``POST`` records a grant or withdrawal on someone's
    behalf (paper form, phone call); people use ``/me/consents`` themselves."""

    model = ConsentRecord
    serializer_class = ConsentRecordSerializer
    filterset_class = ConsentRecordFilter
    permission_classes = [
        IsAuthenticated,
        HasOrganisation,
        HasMethodPermission.for_({"GET": VIEW, "POST": "privacy.consent.record"}),
    ]

    def get_tenant_queryset(self) -> QuerySet[ConsentRecord]:
        return ConsentRecord.objects.select_related("consent_type")

    @extend_schema(
        request=RecordConsentSerializer,
        responses={201: ConsentRecordSerializer},
        examples=[
            OpenApiExample(
                "Parent gave photo consent on paper",
                value={
                    "subject_type": "people.student",
                    "subject_id": "0192...",
                    "consent_type": "photo-video",
                    "granted": True,
                    "given_by_name": "Jane Smith (mother)",
                    "on_behalf_of_child": True,
                },
                request_only=True,
            )
        ],
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = RecordConsentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        record = services.record_consent(
            subject_type=data["subject_type"],
            subject_id=data["subject_id"],
            key=data["consent_type"],
            granted=data["granted"],
            method=data["method"],
            given_by=request.user,
            given_by_name=data.get("given_by_name", ""),
            on_behalf_of_child=data["on_behalf_of_child"],
        )
        return Response(
            ConsentRecordSerializer(record, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        parameters=[OpenApiParameter("subject_type", str), OpenApiParameter("subject_id", str)],
        responses=ConsentStatusSerializer(many=True),
    )
    @action(detail=False, methods=["get"], url_path="status")
    def consent_status(self, request: Request) -> Response:
        """Current consent per type for one person."""
        subject_type = request.query_params.get("subject_type", "")
        subject_id = request.query_params.get("subject_id", "")
        if not subjects.is_valid(subject_type, subject_id):
            from rest_framework.exceptions import NotFound

            raise NotFound()
        rows = [dataclasses.asdict(s) for s in services.status_for(subject_type, subject_id)]
        return Response(ConsentStatusSerializer(rows, many=True).data)


class MyConsentsView(APIView):
    """Your own consents in this organisation: see, give or withdraw (portal, FR-29-3)."""

    permission_classes = [IsAuthenticated, HasOrganisation]

    @extend_schema(responses=ConsentStatusSerializer(many=True))
    def get(self, request: Request) -> Response:
        rows = [
            dataclasses.asdict(s)
            for s in services.status_for("identity.user", str(request.user.pk))
        ]
        return Response(ConsentStatusSerializer(rows, many=True).data)

    @extend_schema(request=MyConsentSerializer, responses=ConsentStatusSerializer(many=True))
    def post(self, request: Request) -> Response:
        payload = MyConsentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.record_consent(
            subject_type="identity.user",
            subject_id=str(request.user.pk),
            key=payload.validated_data["consent_type"],
            granted=payload.validated_data["granted"],
            method=ConsentRecord.Method.PORTAL,
            given_by=request.user,
        )
        return self.get(request)
