"""Data subject requests, erasure, legal holds and retention API (E29-T05..T07)."""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import QuerySet
from django.http import HttpResponseRedirect
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.permissions import HasOrganisation, HasPermission

from .. import dsar, erasure, holds, retention, selectors, subjects
from ..models import DataSubjectRequest, ErasureRecord, LegalHold, RetentionPolicy, RetentionRun
from . import serializers as s

DSAR: list[Any] = [IsAuthenticated, HasOrganisation, HasPermission.for_("privacy.dsar.manage")]
RETENTION: list[Any] = [
    IsAuthenticated,
    HasOrganisation,
    HasPermission.for_("privacy.retention.manage"),
]
HOLDS: list[Any] = [
    IsAuthenticated,
    HasOrganisation,
    HasPermission.for_("privacy.legal_hold.manage"),
]


class DataRequestFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=DataSubjectRequest.Status.choices)
    kind = filters.ChoiceFilter(choices=DataSubjectRequest.Kind.choices)
    open = filters.BooleanFilter(method="filter_open")
    subject_type = filters.CharFilter()
    subject_id = filters.CharFilter()

    class Meta:
        model = DataSubjectRequest
        fields: list[str] = []

    def filter_open(
        self, queryset: QuerySet[DataSubjectRequest], name: str, value: bool
    ) -> QuerySet[DataSubjectRequest]:
        opened = {"status__in": DataSubjectRequest.OPEN}
        return queryset.filter(**opened) if value else queryset.exclude(**opened)


class DataRequestViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Data subject requests (FR-29-4): intake, identity checks, the statutory deadline,
    export review and redaction, erasure approval. The process runs as
    ``DataSubjectRequestWorkflow``; each decision here signals it."""

    model = DataSubjectRequest
    serializer_class = s.DataRequestSerializer
    filterset_class = DataRequestFilter
    permission_classes = DSAR

    def get_tenant_queryset(self) -> QuerySet[DataSubjectRequest]:
        return selectors.data_requests(self.request.user)

    def _out(self, request_obj: DataSubjectRequest, code: int = 200) -> Response:
        return Response(self.get_serializer(request_obj).data, status=code)

    @extend_schema(
        request=s.DataRequestCreateSerializer,
        responses={201: s.DataRequestSerializer},
        examples=[
            OpenApiExample(
                "A parent emailed asking for their child's data",
                value={
                    "kind": "access",
                    "subject_type": "people.student",
                    "subject_id": "0192f0c2-...",
                    "requester_name": "Priya Patel",
                    "requester_email": "priya@example.com",
                    "relationship": "parent",
                    "channel": "email",
                },
                request_only=True,
            )
        ],
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.DataRequestCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        created = dsar.log_request(**payload.validated_data)
        return self._out(created, status.HTTP_201_CREATED)

    @extend_schema(
        request=s.VerifySerializer,
        responses=s.DataRequestSerializer,
        examples=[
            OpenApiExample(
                "ID checked by phone",
                value={
                    "checks": {"identity": True, "matches_records": True},
                    "note": "Called back",
                },
                request_only=True,
            )
        ],
    )
    @action(detail=True, methods=["post"])
    def verify(self, request: Request, pk: Any = None) -> Response:
        """Tick identity checks; once the required ones are done the request proceeds."""
        payload = s.VerifySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        updated = dsar.update_checks(
            self.get_object(),
            payload.validated_data["checks"],
            note=payload.validated_data.get("note", ""),
            user=request.user,
        )
        return self._out(updated)

    @extend_schema(request=s.DataRequestExtendSerializer, responses=s.DataRequestSerializer)
    @action(detail=True, methods=["post"])
    def extend(self, request: Request, pk: Any = None) -> Response:
        """Extend the deadline of a complex request (two further months at most)."""
        payload = s.DataRequestExtendSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._out(dsar.extend(self.get_object(), **payload.validated_data))

    @extend_schema(request=s.PrivacyReasonSerializer, responses=s.DataRequestSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: Any = None) -> Response:
        """Refuse a request (e.g. identity can't be verified); the requester is told why."""
        payload = s.PrivacyReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._out(
            dsar.close(
                self.get_object(),
                status=DataSubjectRequest.Status.REJECTED,
                reason=payload.validated_data["reason"],
            )
        )

    @extend_schema(request=s.PrivacyReasonSerializer, responses=s.DataRequestSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        """The requester withdrew the request."""
        payload = s.PrivacyReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._out(
            dsar.close(
                self.get_object(),
                status=DataSubjectRequest.Status.CANCELLED,
                reason=payload.validated_data["reason"],
            )
        )

    @extend_schema(responses=s.ExportPreviewSerializer)
    @action(detail=True, methods=["get"], url_path="export-preview")
    def export_preview(self, request: Request, pk: Any = None) -> Response:
        """The compiled export, for review and redaction (logged as a sensitive read)."""
        document = dsar.preview_export(self.get_object())
        return Response(
            s.ExportPreviewSerializer(
                {"sections": document.get("sections", []), "files": document.get("files", [])}
            ).data
        )

    @extend_schema(
        request=s.RedactionsSerializer,
        responses=s.DataRequestSerializer,
        examples=[
            OpenApiExample(
                "Remove a note about a third party and one field",
                value={
                    "redactions": [
                        {"section": "crm.notes", "record_id": "0192...", "reason": "third party"},
                        {
                            "section": "people.students",
                            "record_id": "0192...",
                            "record_field": "learning_needs",
                            "reason": "clinician's report",
                        },
                    ]
                },
                request_only=True,
            )
        ],
    )
    @action(detail=True, methods=["put"])
    def redactions(self, request: Request, pk: Any = None) -> Response:
        """Replace the redactions (records, fields or files left out of the export)."""
        payload = s.RedactionsSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._out(
            dsar.set_redactions(
                self.get_object(), payload.validated_data["redactions"], user=request.user
            )
        )

    @extend_schema(request=None, responses=s.DataRequestSerializer)
    @action(detail=True, methods=["post"], url_path="approve-export")
    def approve_export(self, request: Request, pk: Any = None) -> Response:
        """Approve the reviewed export: it is packaged and sent as a secure link."""
        return self._out(dsar.approve_redactions(self.get_object(), user=request.user))

    @extend_schema(request=None, responses=s.DataRequestSerializer)
    @action(detail=True, methods=["post"], url_path="approve-erasure")
    def approve_erasure(self, request: Request, pk: Any = None) -> Response:
        """Approve the erasure (refused while a legal hold applies)."""
        return self._out(dsar.approve_erasure(self.get_object(), user=request.user))

    @extend_schema(responses={200: s.ErasureRecordSerializer, 404: None})
    @action(detail=True, methods=["get"])
    def erasure(self, request: Request, pk: Any = None) -> Response:
        """What the erasure did, provider by provider."""
        record = dsar.erasure_record(self.get_object())
        if record is None:
            raise NotFound()
        return Response(s.ErasureRecordSerializer(record).data)


class ErasurePreviewView(APIView):
    """What erasing a person would cover and whether a legal hold blocks it."""

    permission_classes = DSAR

    @extend_schema(
        parameters=[
            OpenApiParameter("subject_type", str, required=True),
            OpenApiParameter("subject_id", str, required=True),
        ],
        responses=s.ErasurePreviewSerializer,
    )
    def get(self, request: Request) -> Response:
        subject_type = str(request.query_params.get("subject_type", ""))
        subject_id = str(request.query_params.get("subject_id", ""))
        if not subjects.is_valid(subject_type, subject_id):
            raise NotFound()
        return Response(s.ErasurePreviewSerializer(erasure.preview(subject_type, subject_id)).data)


class ErasureRecordViewSet(TenantScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    """Every erasure, from requests and retention policies (the audit trail of FR-29-4)."""

    model = ErasureRecord
    serializer_class = s.ErasureRecordSerializer
    permission_classes = DSAR

    def get_tenant_queryset(self) -> QuerySet[ErasureRecord]:
        return selectors.erasures(self.request.user)


class DataExportDownloadView(APIView):
    """The secure link sent to the requester: redirects to a short-lived download. The link
    is single-purpose, expires (``privacy.dsar_link_days``) and every use is audited."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(responses={302: None, 404: None})
    def get(self, request: Request, token: str) -> HttpResponseRedirect:
        _request, url = dsar.download(token)
        return HttpResponseRedirect(url)


# --- legal holds --------------------------------------------------------------------------------


class LegalHoldFilter(filters.FilterSet):
    active = filters.BooleanFilter(field_name="released_at", lookup_expr="isnull")
    subject_type = filters.CharFilter()
    subject_id = filters.CharFilter()

    class Meta:
        model = LegalHold
        fields: list[str] = []


class LegalHoldViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Legal holds: a held person is never erased or purged (FR-29-5)."""

    model = LegalHold
    serializer_class = s.LegalHoldSerializer
    filterset_class = LegalHoldFilter
    permission_classes = HOLDS

    def get_tenant_queryset(self) -> QuerySet[LegalHold]:
        return selectors.legal_holds(self.request.user)

    @extend_schema(
        examples=[
            OpenApiExample(
                "Litigation",
                value={
                    "subject_type": "people.client",
                    "subject_id": "0192...",
                    "reason": "Fee dispute in the small claims court",
                },
                request_only=True,
            )
        ]
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.LegalHoldSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        hold = holds.place(**payload.validated_data, user=request.user)
        return Response(self.get_serializer(hold).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.PrivacyReasonSerializer, responses=s.LegalHoldSerializer)
    @action(detail=True, methods=["post"])
    def release(self, request: Request, pk: Any = None) -> Response:
        payload = s.PrivacyReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        hold = holds.release(
            self.get_object(), reason=payload.validated_data["reason"], user=request.user
        )
        return Response(self.get_serializer(hold).data)


# --- retention ----------------------------------------------------------------------------------


class RetentionPolicyViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Retention periods per category of data (FR-29-5)."""

    model = RetentionPolicy
    serializer_class = s.RetentionPolicySerializer
    permission_classes = RETENTION
    http_method_names = ["get", "patch", "head", "options"]
    pagination_class = None

    def get_tenant_queryset(self) -> QuerySet[RetentionPolicy]:
        retention.ensure_policies()
        return selectors.retention_policies(self.request.user)

    def perform_update(self, serializer: Any) -> None:
        data = serializer.validated_data
        serializer.instance = retention.update_policy(
            serializer.instance, period_days=data.get("period_days"), enabled=data.get("enabled")
        )


class RetentionRunViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Purge runs: the nightly schedule's and manual ones (a dry run reports only)."""

    model = RetentionRun
    serializer_class = s.RetentionRunSerializer
    permission_classes = RETENTION

    def get_tenant_queryset(self) -> QuerySet[RetentionRun]:
        return selectors.retention_runs(self.request.user)

    @extend_schema(
        request=s.RetentionRunCreateSerializer,
        responses={201: s.RetentionRunSerializer},
        examples=[OpenApiExample("Dry run now", value={"dry_run": True}, request_only=True)],
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from django.db import transaction

        from tutortrack.core.context import require_organisation_id
        from tutortrack.core.workflows import start, workflow_id

        from ..processes import RETENTION_PROCESS, RetentionInput, RetentionPurgeWorkflow

        payload = s.RetentionRunCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        org_id = require_organisation_id()
        wid = workflow_id(RETENTION_PROCESS, org_id, f"manual-{uuid.uuid4().hex[:12]}")
        with transaction.atomic():
            run = retention.start_run(
                dry_run=payload.validated_data["dry_run"],
                trigger="manual",
                user=request.user,
                workflow_id=wid,
            )
            start(
                RetentionPurgeWorkflow,
                RetentionInput(organisation_id=str(org_id), run_id=str(run.pk)),
                id=wid,
                subject=("retention_run", str(run.pk)),
            )
        return Response(self.get_serializer(run).data, status=status.HTTP_201_CREATED)
