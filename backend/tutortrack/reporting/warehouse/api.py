"""Warehouse export API (E26-T09): ``/reporting/warehouse/destinations`` (+ check, run,
exports), the documented schemas, and downloads of platform-stored files."""

from __future__ import annotations

from typing import Any

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
)
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation

from . import services
from .datasets import DATASETS, schema
from .models import WarehouseDestination, WarehouseExport

PERMS: list[Any] = [
    IsAuthenticated,
    HasOrganisation,
    HasMethodPermission.for_(
        {
            "GET": "reporting.warehouse.manage",
            "POST": "reporting.warehouse.manage",
            "PUT": "reporting.warehouse.manage",
            "PATCH": "reporting.warehouse.manage",
            "DELETE": "reporting.warehouse.manage",
        }
    ),
]


class WarehouseDestinationSerializer(serializers.ModelSerializer):
    has_credentials = serializers.SerializerMethodField()

    class Meta:
        model = WarehouseDestination
        fields = [
            "id",
            "name",
            "kind",
            "file_format",
            "config",
            "datasets",
            "enabled",
            "hour",
            "full_refresh_weekday",
            "has_credentials",
            "last_export_at",
            "last_status",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.BooleanField())
    def get_has_credentials(self, obj: WarehouseDestination) -> bool:
        return bool(obj.credentials)


class WarehouseDestinationInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, allow_blank=True, required=False, default="")
    kind = serializers.ChoiceField(choices=WarehouseDestination.Kind.choices)
    config = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False)
    credentials = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        write_only=True,
        help_text="Write-only: an AWS key, a service account or a private key.",
    )
    datasets = serializers.ListField(child=serializers.CharField(), required=False)
    enabled = serializers.BooleanField(required=False, default=True)
    hour = serializers.IntegerField(required=False, default=2, min_value=0, max_value=23)
    full_refresh_weekday = serializers.IntegerField(
        required=False, default=6, min_value=-1, max_value=6
    )


class WarehouseExportSerializer(serializers.ModelSerializer):
    class Meta:
        model = WarehouseExport
        fields = [
            "id",
            "destination",
            "status",
            "full",
            "since",
            "until",
            "manifest",
            "row_count",
            "error",
            "finished_at",
            "created_at",
        ]
        read_only_fields = fields


class RunExportSerializer(serializers.Serializer):
    full = serializers.BooleanField(required=False, default=False)


class RunStartedSerializer(serializers.Serializer):
    workflow_id = serializers.CharField()


class DatasetSchemaSerializer(serializers.Serializer):
    dataset = serializers.CharField()
    description = serializers.CharField()
    columns = serializers.ListField(child=serializers.DictField())


class WarehouseDownloadSerializer(serializers.Serializer):
    url = serializers.CharField()


class WarehouseDestinationViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Where the organisation's data is exported (Enterprise: ``warehouse_export``)."""

    model = WarehouseDestination
    serializer_class = WarehouseDestinationSerializer
    permission_classes = PERMS
    http_method_names = ["get", "post", "put", "delete", "head", "options"]

    def get_tenant_queryset(self) -> Any:
        return WarehouseDestination.objects.all()

    def _destination(self, pk: Any) -> WarehouseDestination:
        return get_object_or_404(self.get_tenant_queryset(), pk=pk)

    @extend_schema(
        request=WarehouseDestinationInputSerializer,
        responses={201: WarehouseDestinationSerializer},
        examples=[
            OpenApiExample(
                "Nightly to S3",
                value={
                    "name": "Data lake",
                    "kind": "s3",
                    "config": {
                        "bucket": "brightminds-warehouse",
                        "region": "eu-west-2",
                        "prefix": "tutortrack",
                    },
                    "credentials": {"access_key_id": "<key id>", "secret_access_key": "<secret>"},
                    "hour": 2,
                },
                request_only=True,
            )
        ],
    )
    def create(self, request: Request) -> Response:
        payload = WarehouseDestinationInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        destination = services.save_destination(None, **payload.validated_data)
        return Response(
            WarehouseDestinationSerializer(destination).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        request=WarehouseDestinationInputSerializer, responses=WarehouseDestinationSerializer
    )
    def update(self, request: Request, pk: Any = None) -> Response:
        payload = WarehouseDestinationInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        destination = services.save_destination(self._destination(pk), **payload.validated_data)
        return Response(WarehouseDestinationSerializer(destination).data)

    def perform_destroy(self, instance: WarehouseDestination) -> None:
        services.delete_destination(instance)

    @extend_schema(request=None, responses=WarehouseDestinationSerializer)
    @action(detail=True, methods=["post"])
    def check(self, request: Request, pk: Any = None) -> Response:
        destination = self._destination(pk)
        services.check(destination)
        return Response(WarehouseDestinationSerializer(destination).data)

    @extend_schema(request=RunExportSerializer, responses={202: RunStartedSerializer})
    @action(detail=True, methods=["post"])
    def run(self, request: Request, pk: Any = None) -> Response:
        payload = RunExportSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        wid = services.run_now(
            self._destination(pk), user=request.user, full=payload.validated_data["full"]
        )
        return Response({"workflow_id": wid}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(responses=WarehouseExportSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def exports(self, request: Request, pk: Any = None) -> Response:
        """The latest 50 runs."""
        runs = WarehouseExport.objects.filter(destination=self._destination(pk))[:50]
        return Response(WarehouseExportSerializer(runs, many=True).data)


class WarehouseSchemaView(APIView):
    """``GET /reporting/warehouse/schema``: the documented dataset schemas."""

    permission_classes = PERMS

    @extend_schema(responses=DatasetSchemaSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(schema())


class WarehouseDownloadView(APIView):
    """``GET /reporting/warehouse/exports/{id}/download?dataset=``: a 10-minute link to a
    file of a TutorTrack-stored export (audited)."""

    permission_classes = PERMS

    @extend_schema(
        parameters=[OpenApiParameter("dataset", str, enum=sorted(DATASETS))],
        responses=WarehouseDownloadSerializer,
    )
    def get(self, request: Request, pk: str) -> Response:
        export = get_object_or_404(WarehouseExport.objects.select_related("destination"), pk=pk)
        url = services.download_url(
            export, str(request.query_params.get("dataset", "")), user=request.user
        )
        return Response({"url": url})
