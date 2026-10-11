"""Import, migration and export API (E28)."""

from __future__ import annotations

from typing import Any

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.pagination import CursorPagination
from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.models import StoredFile
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, has_perm
from tutortrack.core.storage import services as storage

from .. import mapping, selectors, services
from ..importers import base as importers
from ..models import ExportJob, ImportBatch, MigrationProject, SavedImportMapping
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]
VIEW = "migration.import.view"
MANAGE = "migration.import.manage"


def perms(mapping_: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping_)]


class RowPagination(CursorPagination):
    ordering = "row_number"
    page_size = 100


class ImportCatalogueView(APIView):
    permission_classes = perms({"GET": VIEW})

    @extend_schema(responses=s.ImportCatalogueSerializer)
    def get(self, request: Request) -> Response:
        """What can be imported, each kind's fields (with custom fields) and the presets for
        TutorBird, TutorCruncher and Teachworks exports."""
        entities = []
        for importer in importers.all_importers():
            info = importer.describe()
            info["field_specs"] += [f.describe() for f in services.extra_fields(importer.key)]
            info["allowed"] = has_perm(request.user, MANAGE) and all(
                has_perm(request.user, p) for p in importer.permissions
            )
            entities.append(info)
        return Response(
            s.ImportCatalogueSerializer({"entities": entities, "presets": mapping.presets()}).data
        )


class ImportTemplateView(APIView):
    permission_classes = perms({"GET": VIEW})

    @extend_schema(
        responses={(200, "text/csv"): OpenApiTypes.BINARY},
        description="A CSV template for this kind of record: the column names and an example.",
    )
    def get(self, request: Request, entity: str) -> HttpResponse:
        if importers.get(entity) is None:
            raise NotFound()
        response = HttpResponse(services.template_csv(entity), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="tutortrack-{entity}-template.csv"'
        return response


class ImportBatchViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Imports: upload → map columns → validate (dry run) → confirm → results → roll back."""

    model = ImportBatch
    serializer_class = s.ImportBatchSerializer
    permission_classes = perms({"GET": VIEW, "*": MANAGE})

    def get_tenant_queryset(self) -> Any:
        qs = selectors.batches(self.request.user)
        params = self.request.query_params
        if params.get("entity"):
            qs = qs.filter(entity=params["entity"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("project"):
            qs = qs.filter(project_id=params["project"])  # type: ignore[misc]
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter("entity", str, required=False),
            OpenApiParameter("status", str, required=False),
            OpenApiParameter("project", str, required=False),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def _saved(self, pk: Any) -> SavedImportMapping | None:
        if not pk:
            return None
        return get_object_or_404(selectors.saved_mappings(self.request.user), pk=pk)

    @extend_schema(
        request=s.CreateImportSerializer,
        responses={201: s.ImportBatchSerializer},
        examples=[
            OpenApiExample(
                "Students from a TutorBird export",
                value={
                    "file": "0192f0c4-0000-7000-8000-000000000001",
                    "entity": "students",
                    "preset": "tutorbird",
                    "options": {"date_format": "MDY"},
                },
                request_only=True,
            )
        ],
    )
    def create(self, request: Request) -> Response:
        """Start an import from an uploaded CSV or Excel file (``POST /files/uploads`` first;
        the file must have passed the virus scan). Columns are matched automatically."""
        payload = s.CreateImportSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        stored = get_object_or_404(StoredFile.objects.all(), pk=data["file"])
        if not storage.can_access(request.user, stored):
            raise NotFound()
        project = None
        if data.get("project"):
            project = get_object_or_404(selectors.projects(request.user), pk=data["project"])
        batch = services.create_from_file(
            user=request.user,
            file=stored,
            entity=data["entity"],
            preset=data["preset"],
            sheet=data["sheet"],
            options=data["options"],
            saved_mapping=self._saved(data.get("saved_mapping")),
            project=project,
            project_step=data["project_step"] if project else "",
        )
        return Response(s.ImportBatchSerializer(batch).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.GoogleSheetImportSerializer, responses={201: s.ImportBatchSerializer})
    @action(detail=False, methods=["post"], url_path="google-sheet")
    def google_sheet(self, request: Request) -> Response:
        """Start an import from a Google Sheet (needs a connected Google account)."""
        payload = s.GoogleSheetImportSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        batch = services.create_from_google_sheet(
            user=request.user,
            url=data["url"],
            entity=data["entity"],
            sheet=data["sheet"],
            options=data["options"],
            saved_mapping=self._saved(data.get("saved_mapping")),
        )
        return Response(s.ImportBatchSerializer(batch).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses=s.ImportPreviewSerializer)
    @action(detail=True, methods=["get"])
    def preview(self, request: Request, pk: Any = None) -> Response:
        """Headers, the current mapping, sample rows, distinct values of choice columns (for
        value mapping) and the entity's fields."""
        return Response(s.ImportPreviewSerializer(services.preview(self.get_object())).data)

    @extend_schema(request=s.UpdateMappingSerializer, responses=s.ImportPreviewSerializer)
    @action(detail=True, methods=["put"], url_path="mapping")
    def update_mapping(self, request: Request, pk: Any = None) -> Response:
        """Change the column mapping, value mapping or options (re-validates if checked)."""
        payload = s.UpdateMappingSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        batch = services.update_mapping(
            self.get_object(),
            column_map=data.get("column_map"),
            value_map=data.get("value_map"),
            options=data.get("options"),
        )
        return Response(s.ImportPreviewSerializer(services.preview(batch)).data)

    def _do(self, fn: Any) -> Response:
        batch = fn(self.get_object(), user=self.request.user)
        return Response(
            s.ImportBatchSerializer(selectors.batches(self.request.user).get(pk=batch.pk)).data
        )

    @extend_schema(request=None, responses=s.ImportBatchSerializer)
    @action(detail=True, methods=["post"])
    def submit(self, request: Request, pk: Any = None) -> Response:
        """Mapping done: check every row and work out what will happen (the dry run)."""
        return self._do(services.submit)

    @extend_schema(request=None, responses=s.ImportBatchSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request: Request, pk: Any = None) -> Response:
        """Import the valid rows (rows with errors are left out and reported)."""
        return self._do(services.confirm)

    @extend_schema(request=None, responses=s.ImportBatchSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        return self._do(services.cancel)

    @extend_schema(request=None, responses=s.ImportBatchSerializer)
    @action(detail=True, methods=["post"])
    def rollback(self, request: Request, pk: Any = None) -> Response:
        """Undo the import (within the rollback window): records nobody has changed since are
        removed, updated ones get their old values back."""
        return self._do(services.request_rollback)

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, required=False),
            OpenApiParameter("problems", bool, required=False),
        ],
        responses=s.ImportRowSerializer(many=True),
    )
    @action(detail=True, methods=["get"], pagination_class=RowPagination)
    def rows(self, request: Request, pk: Any = None) -> Response:
        """The rows with their checked values, errors, warnings and outcome."""
        batch = self.get_object()
        qs = selectors.rows(
            batch,
            status=request.query_params.get("status", ""),
            problems=request.query_params.get("problems") in ("1", "true"),
        )
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(s.ImportRowSerializer(page, many=True).data)

    @extend_schema(request=None, responses=s.DownloadLinkSerializer)
    @action(detail=True, methods=["get"], url_path="error-report")
    def error_report(self, request: Request, pk: Any = None) -> Response:
        """A short-lived link to the CSV of rows that weren't imported, with the reasons."""
        batch = self.get_object()
        if batch.error_file is None:
            raise NotFound("There is no error report for this import.")
        url, expires = storage.download_url(request.user, batch.error_file)
        return Response({"url": url, "expires_in": expires})

    @extend_schema(request=s.SaveMappingSerializer, responses={201: s.SavedImportMappingSerializer})
    @action(detail=True, methods=["post"], url_path="save-mapping")
    def save_mapping(self, request: Request, pk: Any = None) -> Response:
        payload = s.SaveMappingSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        saved = services.save_mapping(
            self.get_object(), name=payload.validated_data["name"], user=request.user
        )
        return Response(s.SavedImportMappingSerializer(saved).data, status=status.HTTP_201_CREATED)


class SavedImportMappingViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    model = SavedImportMapping
    serializer_class = s.SavedImportMappingSerializer
    permission_classes = perms({"*": MANAGE})

    def get_tenant_queryset(self) -> Any:
        return selectors.saved_mappings(
            self.request.user, self.request.query_params.get("entity", "")
        )

    @extend_schema(parameters=[OpenApiParameter("entity", str, required=False)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def perform_destroy(self, instance: SavedImportMapping) -> None:
        services.delete_saved_mapping(instance)


class MigrationProjectViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """The cutover assistant: one migration from TutorCruncher, TutorBird, Teachworks or
    spreadsheets, step by step, ending with a reconciliation report."""

    model = MigrationProject
    serializer_class = s.MigrationProjectSerializer
    permission_classes = perms({"*": "migration.project.manage"})

    def get_tenant_queryset(self) -> Any:
        return selectors.projects(self.request.user)

    @extend_schema(
        request=s.CreateMigrationProjectSerializer,
        responses={201: s.MigrationProjectSerializer},
        examples=[
            OpenApiExample(
                "From TutorCruncher",
                value={
                    "origin": "tutorcruncher",
                    "cutover_date": "2026-11-01",
                    "api_key": "abc123...",
                },
                request_only=True,
            )
        ],
    )
    def create(self, request: Request) -> Response:
        payload = s.CreateMigrationProjectSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        project = services.create_project(
            user=request.user,
            name=data["name"],
            source=data["origin"],
            cutover_date=data["cutover_date"],
            api_key=data["api_key"],
        )
        return Response(s.MigrationProjectSerializer(project).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.CompleteStepSerializer, responses=s.MigrationProjectSerializer)
    @action(detail=True, methods=["post"], url_path=r"steps/(?P<step>[a-z_]+)/complete")
    def complete_step(self, request: Request, pk: Any = None, step: str = "") -> Response:
        """Confirm the current step (or skip it) and move on."""
        payload = s.CompleteStepSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        project = services.complete_step(
            self.get_object(),
            step,
            skip=payload.validated_data["skip"],
            note=payload.validated_data["note"],
        )
        return Response(s.MigrationProjectSerializer(project).data)

    @extend_schema(request=None, responses=s.InvitedSerializer)
    @action(detail=True, methods=["post"], url_path="invite-tutors")
    def invite_tutors(self, request: Request, pk: Any = None) -> Response:
        """Send invitations to the tutors this migration created."""
        return Response({"sent": services.invite_imported_tutors(self.get_object())})

    @extend_schema(request=None, responses=s.MigrationProjectSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        return Response(
            s.MigrationProjectSerializer(services.cancel_project(self.get_object())).data
        )


class ExportJobViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Full data exports (owner): a ZIP of every record as CSV and JSON, documents and
    invoice PDFs. Downloading needs the owner's password; the file expires."""

    model = ExportJob
    serializer_class = s.ExportJobSerializer
    permission_classes = perms({"*": "migration.export.full"})

    def get_tenant_queryset(self) -> Any:
        return selectors.exports(self.request.user)

    @extend_schema(request=s.RequestExportSerializer, responses={201: s.ExportJobSerializer})
    def create(self, request: Request) -> Response:
        payload = s.RequestExportSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        job = services.request_export(user=request.user, reason=payload.validated_data["reason"])
        return Response(s.ExportJobSerializer(job).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=s.ExportDownloadSerializer,
        responses={
            200: s.DownloadLinkSerializer,
            403: OpenApiResponse(description="Wrong password"),
        },
    )
    @action(detail=True, methods=["post"])
    def download(self, request: Request, pk: Any = None) -> Response:
        """Confirm your password to get a 5-minute download link."""
        payload = s.ExportDownloadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        url = services.download_export(
            self.get_object(), user=request.user, password=payload.validated_data["password"]
        )
        return Response({"url": url, "expires_in": 300})

    @extend_schema(request=None, responses=s.ExportJobSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        return Response(s.ExportJobSerializer(services.cancel_export(self.get_object())).data)
