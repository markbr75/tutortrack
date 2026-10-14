"""Reporting API (E26): reports, exports, dashboards, widgets, saved and scheduled reports."""

from __future__ import annotations

from typing import Any

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, HasPermission
from tutortrack.core.storage.services import download_url
from tutortrack.core.time import now

from .. import reports, selectors, services, widgets
from ..models import CustomReport, ReportRun, SavedReport, ScheduledReport
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]

PERIOD_PARAMS = [
    OpenApiParameter("period", str, description="this_month, last_month, last_30_days, custom..."),
    OpenApiParameter("from", OpenApiTypes.DATE, description="Start (custom period)"),
    OpenApiParameter("to", OpenApiTypes.DATE, description="End (custom period)"),
    OpenApiParameter("branch", str, description="Branch ids, comma separated"),
]
REPORT_PARAMS = [
    *PERIOD_PARAMS,
    OpenApiParameter("tutor", str, description="Tutor ids, comma separated"),
    OpenApiParameter("client", str, description="Client ids, comma separated"),
    OpenApiParameter("service", str, description="Service ids, comma separated"),
    OpenApiParameter("subject", str, description="Subject ids, comma separated"),
    OpenApiParameter("tag", str, description="Tag id (clients, students or tutors)"),
    OpenApiParameter("custom_field", str, description="Client custom field, key=value"),
    OpenApiParameter("group_by", str),
    OpenApiParameter("ordering", str, description="Column key, '-' for descending"),
    OpenApiParameter("currency", str, description="Reporting currency (converted at FX rates)"),
]
RESULT_EXAMPLE = OpenApiExample(
    "Revenue by month",
    value={
        "report": {"key": "revenue", "title": "Revenue", "category": "finance"},
        "params": {"period": "this_month", "group_by": "month"},
        "period": {"from": "2026-10-01", "to": "2026-10-31"},
        "columns": [
            {"key": "group", "label": "Month", "type": "text"},
            {"key": "net", "label": "Net", "type": "money"},
        ],
        "rows": [{"group": "2026-10-01", "currency": "GBP", "net": "1250.00"}],
        "totals": [{"currency": "GBP", "net": "1250.00"}],
        "chart": {"kind": "bar", "x": "group", "y": ["net"], "stacked": False},
        "notes": [],
        "generated_at": "2026-10-10T09:00:00Z",
    },
    response_only=True,
)


def _result_body(report: Any, params: Any, result: Any) -> dict[str, Any]:
    chart = None
    if result.chart:
        chart = {
            "kind": result.chart["type"],
            "x": result.chart["x"],
            "y": result.chart["y"],
            "stacked": bool(result.chart.get("stacked")),
        }
    return {
        "report": report.describe(),
        "params": {k: str(v) for k, v in params.as_query().items()},
        "period": params.period.as_dict() if report.period else None,
        "columns": [c.as_dict() for c in result.columns],
        "rows": result.rows,
        "totals": result.totals or [],
        "chart": chart,
        "notes": result.notes,
        "generated_at": now(),
    }


# --- reports ------------------------------------------------------------------------------------


class ReportListView(APIView):
    permission_classes = AUTH

    @extend_schema(responses=s.ReportDefinitionSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The standard reports the user may run, by category (FR-26-2)."""
        return Response([r.describe() for r in reports.available(request.user)])


class ReportRunView(APIView):
    permission_classes = AUTH

    @extend_schema(
        parameters=REPORT_PARAMS,
        responses=s.ReportResultSerializer,
        examples=[RESULT_EXAMPLE],
    )
    def get(self, request: Request, key: str) -> Response:
        """Run a report with filters, grouping and sorting. Figures follow the data scope of
        the report's permission (e.g. tutors see only their own)."""
        report, params, result = reports.run(key, request.user, request.query_params)
        return Response(s.ReportResultSerializer(_result_body(report, params, result)).data)


class ReportExportView(APIView):
    permission_classes = [*AUTH, HasPermission.for_("reporting.export")]

    @extend_schema(
        parameters=[
            *REPORT_PARAMS,
            OpenApiParameter("file_format", str, enum=["csv", "xlsx", "pdf"], required=True),
        ],
        responses={(200, "application/octet-stream"): OpenApiResponse(OpenApiTypes.BINARY)},
    )
    def get(self, request: Request, key: str) -> HttpResponse:
        """Download the report as CSV, Excel or PDF (audited as an export)."""
        fmt = request.query_params.get("file_format", "csv")
        name, content_type, content = services.export(request.user, key, request.query_params, fmt)
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response


# --- dashboards ---------------------------------------------------------------------------------


class DashboardView(APIView):
    permission_classes = [*AUTH, HasPermission.for_("reporting.dashboard.view")]

    @extend_schema(responses=s.DashboardLayoutSerializer)
    def get(self, request: Request) -> Response:
        """The user's dashboard layout: their own, or their role's (``simple`` for sole
        traders, FR-26-1 MVP)."""
        return Response(s.DashboardLayoutSerializer(selectors.dashboard(request.user)).data)

    @extend_schema(request=s.DashboardLayoutSerializer, responses=s.DashboardLayoutSerializer)
    def put(self, request: Request) -> Response:
        """Save the user's own layout (widget order and sizes)."""
        payload = s.DashboardLayoutSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.save_layout(request.user, payload.validated_data["widgets"])
        return Response(s.DashboardLayoutSerializer(selectors.dashboard(request.user)).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request) -> Response:
        """Go back to the role's default layout."""
        services.reset_layout(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class WidgetListView(APIView):
    permission_classes = [*AUTH, HasPermission.for_("reporting.dashboard.view")]

    @extend_schema(responses=s.WidgetInfoSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The widget library the user may add."""
        return Response([w.describe() for w in widgets.available(request.user)])


class WidgetDataView(APIView):
    permission_classes = [*AUTH, HasPermission.for_("reporting.dashboard.view")]

    @extend_schema(
        parameters=[
            *PERIOD_PARAMS,
            OpenApiParameter("compare", str, enum=["previous_period", "previous_year", "none"]),
        ],
        responses=s.WidgetDataSerializer,
    )
    def get(self, request: Request, key: str) -> Response:
        """One widget's figures for the period, compared with the previous period."""
        widget = widgets.get(key)
        if widget is None or widget not in widgets.available(request.user):
            raise NotFound("Unknown widget.")
        ctx = selectors.widget_context(request.user, request.query_params)
        data = widget.compute(ctx)
        body = {
            "widget": widget.describe(),
            "unit": data.unit,
            "period": ctx.period.as_dict(),
            "previous_period": ctx.previous.as_dict() if ctx.previous else None,
            "values": data.values,
            "series": data.series,
            "rows": [
                {
                    "label": r.get("label", ""),
                    "value": r.get("value", ""),
                    "detail": r.get("detail", ""),
                }
                for r in data.rows
            ],
            "report_params": {
                "period": ctx.preset,
                **(
                    {"from": ctx.period.start.isoformat(), "to": ctx.period.end.isoformat()}
                    if ctx.preset == "custom"
                    else {}
                ),
                **({"branch": ",".join(ctx.branch)} if ctx.branch else {}),
                **{k: str(v) for k, v in data.report_params.items()},
            },
        }
        return Response(s.WidgetDataSerializer(body).data)


# --- saved and scheduled reports ----------------------------------------------------------------


class SavedReportViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Saved report views (``?report=`` filters by report key)."""

    model = SavedReport
    serializer_class = s.SavedReportSerializer
    permission_classes = AUTH
    http_method_names = ["get", "post", "patch", "delete"]

    def get_tenant_queryset(self) -> Any:
        qs = selectors.saved_reports(self.request.user).select_related("owner")
        key = self.request.query_params.get("report")
        return qs.filter(report_key=key) if key else qs

    @extend_schema(parameters=[OpenApiParameter("report", str, required=False)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.SavedReportSerializer(data=request.data, context={"request": request})
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        saved = services.create_saved_report(
            request.user,
            name=data["name"],
            report_key=data["report_key"],
            params=data.get("params") or {},
            shared=data.get("shared", False),
        )
        body = s.SavedReportSerializer(saved, context={"request": request}).data
        return Response(body, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.SavedReportUpdateSerializer, responses=s.SavedReportSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.SavedReportUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        saved = services.update_saved_report(
            request.user, self.get_object(), **payload.validated_data
        )
        return Response(s.SavedReportSerializer(saved, context={"request": request}).data)

    def perform_destroy(self, instance: SavedReport) -> None:
        services.delete_saved_report(self.request.user, instance)


class ScheduledReportViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Reports emailed to staff on a schedule (FR-26-4)."""

    model = ScheduledReport
    serializer_class = s.ScheduledReportSerializer
    permission_classes = [*AUTH, HasPermission.for_("reporting.schedule.manage")]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_tenant_queryset(self) -> Any:
        return selectors.scheduled_reports(self.request.user)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.ScheduledReportSerializer(data=request.data, context={"request": request})
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        saved = data.pop("saved_report")
        recipients = data.pop("recipients")
        scheduled = services.create_scheduled_report(
            request.user, saved, recipients=recipients, **data
        )
        return Response(s.ScheduledReportSerializer(scheduled).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.ScheduledReportUpdateSerializer, responses=s.ScheduledReportSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.ScheduledReportUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        recipients = data.pop("recipients", None)
        scheduled = services.update_scheduled_report(
            request.user, self.get_object(), recipients=recipients, **data
        )
        return Response(s.ScheduledReportSerializer(scheduled).data)

    def perform_destroy(self, instance: ScheduledReport) -> None:
        services.delete_scheduled_report(self.request.user, instance)

    @extend_schema(responses=s.StaffMemberSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def recipients(self, request: Request) -> Response:
        """Active staff who could receive scheduled reports."""
        from tutortrack.identity.models import Membership

        members = (
            Membership.objects.filter(
                status=Membership.Status.ACTIVE,
                role__in=("owner", "admin", "branch_manager", "coordinator", "finance"),
            )
            .select_related("user")
            .order_by("user__first_name", "user__email")
        )
        return Response(
            [
                {
                    "id": m.user.pk,
                    "name": m.user.get_full_name() or m.user.email,
                    "email": m.user.email,
                }
                for m in members
            ]
        )


class ReportRunViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Report exports and scheduled deliveries."""

    model = ReportRun
    serializer_class = s.ReportRunSerializer
    permission_classes = [*AUTH, HasPermission.for_("reporting.export")]

    def get_tenant_queryset(self) -> Any:
        return selectors.report_runs(self.request.user)

    @extend_schema(request=None, responses=s.ReportDownloadSerializer)
    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: Any = None) -> Response:
        """A short-lived link to a scheduled run's file."""
        run = self.get_object()
        if run.file is None:
            raise NotFound("This run has no file.")
        url, expires = download_url(request.user, run.file)
        return Response({"url": url, "expires_in": expires})


# --- maintenance --------------------------------------------------------------------------------


class RebuildView(APIView):
    permission_classes = [*AUTH, HasMethodPermission.for_({"POST": "reporting.manage"})]

    @extend_schema(request=None, responses=s.RebuildSerializer)
    def post(self, request: Request) -> Response:
        """Recompute the reporting facts from the operational records (repair, backfill)."""
        return Response(services.rebuild_facts(request.user))


# --- custom report builder (T08) ----------------------------------------------------------------

BUILDER_EXAMPLE = {
    "dataset": "charges",
    "group_by": ["service", "date:month"],
    "measures": ["count", "gross"],
    "filters": [{"field": "kind", "op": "in", "value": ["lesson"]}],
    "period": "this_year",
    "ordering": "-gross",
    "limit": 100,
    "chart": "bar",
}


def _custom_body(output: Any) -> dict[str, Any]:
    spec = output.spec
    result = output.result
    return {
        "definition": spec.clean,
        "period": spec.period.as_dict() if spec.period else None,
        "columns": [c.as_dict() for c in result.columns],
        "rows": result.rows,
        "totals": result.totals or [],
        "chart": result.chart,
        "notes": [str(n) for n in result.notes],
        "truncated": output.truncated,
        "generated_at": now(),
    }


def _file(name: str, content_type: str, content: bytes) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


class BuilderDatasetsView(APIView):
    permission_classes = [*AUTH, HasPermission.for_("reporting.builder.use")]

    @extend_schema(responses=s.BuilderDatasetSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The datasets this user may build reports on, with their whitelisted columns
        (dimensions, incl. client/student custom fields) and measures."""
        from .. import builder

        return Response([ds.describe() for ds in builder.available(request.user)])


class BuilderRunView(APIView):
    permission_classes = [*AUTH, HasPermission.for_("reporting.builder.use")]

    @extend_schema(
        request=s.ReportDefinitionInputSerializer,
        responses=s.CustomResultSerializer,
        examples=[
            OpenApiExample("Gross by service and month", request_only=True, value=BUILDER_EXAMPLE)
        ],
    )
    def post(self, request: Request) -> Response:
        """Run a report definition (nothing is saved). Figures follow the data scope of
        the dataset's report family."""
        from .. import builder

        output = builder.run(request.user, s.definition_input(request.data))
        return Response(s.CustomResultSerializer(_custom_body(output)).data)


class BuilderExportView(APIView):
    permission_classes = [
        *AUTH,
        HasPermission.for_("reporting.builder.use"),
        HasPermission.for_("reporting.export"),
    ]

    @extend_schema(
        request=s.BuilderExportSerializer,
        responses={(200, "application/octet-stream"): OpenApiResponse(OpenApiTypes.BINARY)},
    )
    def post(self, request: Request) -> HttpResponse:
        """Download an unsaved report definition as CSV, Excel or PDF (audited)."""
        payload = s.BuilderExportSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        definition = s.definition_input(dict(request.data).get("definition"))
        return _file(
            *services.export_custom(
                request.user,
                definition,
                payload.validated_data["file_format"],
                name=payload.validated_data["name"],
            )
        )


class CustomReportViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Saved custom reports: your own and those shared with you (``?dataset=``). Only the
    owner changes or deletes one; everyone runs it with their own data scope."""

    model = CustomReport
    serializer_class = s.CustomReportSerializer
    permission_classes = [*AUTH, HasPermission.for_("reporting.builder.use")]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_tenant_queryset(self) -> Any:
        qs = selectors.custom_reports(self.request.user).select_related("owner")
        dataset = self.request.query_params.get("dataset")
        return qs.filter(dataset=dataset) if dataset else qs

    @extend_schema(parameters=[OpenApiParameter("dataset", str, required=False)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def _write(self, request: Request, report: CustomReport | None) -> CustomReport:
        payload = s.CustomReportWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        return services.save_custom_report(
            request.user,
            name=d["name"],
            description=d["description"],
            definition=s.definition_input(dict(request.data).get("definition")),
            shared=d["shared"],
            report=report,
        )

    @extend_schema(
        request=s.CustomReportWriteSerializer,
        responses={201: s.CustomReportSerializer},
        examples=[
            OpenApiExample(
                "Save",
                request_only=True,
                value={"name": "Lesson revenue by service", "definition": BUILDER_EXAMPLE},
            )
        ],
    )
    def create(self, request: Request) -> Response:
        report = self._write(request, None)
        body = s.CustomReportSerializer(report, context={"request": request}).data
        return Response(body, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.CustomReportWriteSerializer, responses=s.CustomReportSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        report = self._write(request, self.get_object())
        return Response(s.CustomReportSerializer(report, context={"request": request}).data)

    def perform_destroy(self, instance: CustomReport) -> None:
        services.delete_custom_report(self.request.user, instance)

    @extend_schema(responses=s.CustomResultSerializer)
    @action(detail=True, methods=["get"], url_path="run")
    def run_report(self, request: Request, pk: Any = None) -> Response:
        """Run the saved report now, with the viewer's own data scope."""
        from .. import builder

        output = builder.run(request.user, self.get_object().definition)
        return Response(s.CustomResultSerializer(_custom_body(output)).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("file_format", str, enum=["csv", "xlsx", "pdf"], required=True)
        ],
        responses={(200, "application/octet-stream"): OpenApiResponse(OpenApiTypes.BINARY)},
    )
    @action(
        detail=True,
        methods=["get"],
        permission_classes=[
            *AUTH,
            HasPermission.for_("reporting.builder.use"),
            HasPermission.for_("reporting.export"),
        ],
    )
    def export(self, request: Request, pk: Any = None) -> HttpResponse:
        report = self.get_object()
        return _file(
            *services.export_custom(
                request.user,
                report.definition,
                request.query_params.get("file_format", "csv"),
                name=report.name,
                key=f"custom:{report.pk}",
            )
        )
