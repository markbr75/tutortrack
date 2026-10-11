"""Accounting integrations API (E23): ledger connections and their options, mappings,
switching sync on, backfills, the sync dashboard (records, retry, skip) and GL exports.

Connecting itself uses the integration framework (``/integrations/oauth/start`` with
``provider=xero|quickbooks`` and ``level=organisation``)."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core import audit
from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.context import require_organisation_id
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, HasPermission
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import ProviderError

from .. import builders, exports, mappings, selectors, services
from ..models import (
    AccountingConnection,
    AccountMapping,
    ExternalRecordLink,
    TaxMapping,
    TrackingMapping,
)
from ..providers import PROVIDERS
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]
VIEW = "integrations.accounting.view"
MANAGE = "integrations.accounting.manage"
EXPORT = "integrations.accounting.export"
READ_MANAGE = HasMethodPermission.for_({"GET": VIEW, "*": MANAGE})


def _provider_error(exc: ProviderError) -> BusinessRuleViolation:
    from ..errors import explain

    return BusinessRuleViolation(explain("", exc).message)


class AccountingConnectionViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Ledger connections (Xero, QuickBooks Online) with sync options, health, mapping
    problems and the sync dashboard's counts. ``PATCH`` changes the options: ``mode``
    (individual records or a daily summary journal), ``start_date`` (nothing earlier
    syncs), ``sync_bills``, ``attach_pdf`` and ``lock_behaviour``."""

    model = AccountingConnection
    serializer_class = s.AccountingConnectionSerializer
    permission_classes = [*AUTH, READ_MANAGE]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> Any:
        return selectors.connections(self.request.user)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.update_options(
            serializer.instance, **serializer.validated_data
        )

    @extend_schema(
        request=s.AdoptConnectionSerializer,
        responses={201: s.AccountingConnectionSerializer},
    )
    def create(self, request: Request) -> Response:
        """Set up the accounting side of a just-connected Xero/QuickBooks account
        (idempotent; the ``integration.connected`` event does the same)."""
        payload = s.AdoptConnectionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        connection = get_object_or_404(
            IntegrationConnection.objects.filter(provider__in=PROVIDERS, user__isnull=True).exclude(
                status=IntegrationConnection.Status.DISCONNECTED
            ),
            pk=payload.validated_data["connection"],
        )
        conn = services.on_connected(connection.pk)
        return Response(s.AccountingConnectionSerializer(conn).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=s.AccountingConnectionSerializer)
    @action(detail=True, methods=["post"])
    def refresh(self, request: Request, pk: str) -> Response:
        """Fetch the chart of accounts, tax codes, tracking categories and lock date."""
        try:
            conn = services.refresh_chart(self.get_object())
        except ProviderError as exc:
            raise _provider_error(exc) from exc
        return Response(s.AccountingConnectionSerializer(conn).data)

    @extend_schema(responses=s.ChartSerializer)
    @action(detail=True, methods=["get"], pagination_class=None)
    def chart(self, request: Request, pk: str) -> Response:
        """The ledger's accounts, tax codes and tracking categories as last fetched."""
        conn: AccountingConnection = self.get_object()
        chart = conn.chart or {}
        return Response(
            s.ChartSerializer(
                {
                    "accounts": chart.get("accounts", []),
                    "tax_codes": chart.get("tax_codes", []),
                    "tracking": chart.get("tracking", []),
                }
            ).data
        )

    @extend_schema(
        request=s.EnableSerializer,
        responses=s.AccountingConnectionSerializer,
        examples=[OpenApiExample("With history", value={"backfill_from": "2026-04-01"})],
    )
    @action(detail=True, methods=["post"])
    def enable(self, request: Request, pk: str) -> Response:
        """Switch sync on (the mappings must be complete). ``backfill_from`` also syncs
        history from that date, in paced batches."""
        payload = s.EnableSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        conn = services.enable(
            self.get_object(), backfill_from=payload.validated_data.get("backfill_from")
        )
        return Response(s.AccountingConnectionSerializer(conn).data)

    @extend_schema(request=None, responses=s.AccountingConnectionSerializer)
    @action(detail=True, methods=["post"])
    def disable(self, request: Request, pk: str) -> Response:
        """Switch sync off. Nothing already in the ledger changes."""
        return Response(s.AccountingConnectionSerializer(services.disable(self.get_object())).data)

    @extend_schema(request=s.BackfillSerializer, responses=s.AccountingConnectionSerializer)
    @action(detail=True, methods=["post"])
    def backfill(self, request: Request, pk: str) -> Response:
        """Sync history from ``since`` (resumable; records already synced are skipped)."""
        payload = s.BackfillSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        conn = self.get_object()
        services.start_backfill(conn, payload.validated_data["since"])
        conn.refresh_from_db()
        return Response(s.AccountingConnectionSerializer(conn).data)

    @extend_schema(request=None, responses=s.AccountingConnectionSerializer)
    @action(detail=True, methods=["post"], url_path="cancel-backfill")
    def cancel_backfill(self, request: Request, pk: str) -> Response:
        conn = services.cancel_backfill(self.get_object())
        return Response(s.AccountingConnectionSerializer(conn).data)

    @extend_schema(request=None, responses=s.AccountingConnectionSerializer)
    @action(detail=True, methods=["post"])
    def disconnect(self, request: Request, pk: str) -> Response:
        """Revoke our access at the provider; sync stops. The ledger keeps its records."""
        conn = services.disconnect(self.get_object())
        return Response(s.AccountingConnectionSerializer(conn).data)


def _keys() -> dict[str, list[dict[str, str]]]:
    from tutortrack.catalogue.models import Category, Product
    from tutortrack.payments.models import Payment
    from tutortrack.payroll.models import ExpenseCategory

    revenue = [
        {"key": f"service_category:{c.pk}", "name": c.name} for c in Category.objects.all()
    ] + [
        {"key": f"product_category:{value}", "name": str(label)}
        for value, label in Product.Category.choices
    ]
    clearing = [{"key": "provider:stripe", "name": "Stripe"}] + [
        {"key": f"method:{value}", "name": str(label)} for value, label in Payment.Method.choices
    ]
    expense = [
        {"key": f"expense_category:{c.pk}", "name": c.name}
        for c in ExpenseCategory.objects.filter(active=True)
    ]
    from tutortrack.catalogue.models import TaxRate
    from tutortrack.tenancy.models import Branch

    return {
        "revenue_keys": revenue,
        "clearing_keys": clearing,
        "expense_keys": expense,
        "tax_rates": [
            {"key": str(r.pk), "name": str(r)} for r in TaxRate.objects.filter(active=True)
        ],
        "branches": [
            {"key": str(b.pk), "name": b.name} for b in Branch.objects.filter(archived_at=None)
        ],
    }


def _mapping_set(provider: str) -> dict[str, Any]:
    conn = (
        AccountingConnection.objects.filter(provider=provider).order_by("-created_at").first()
        if provider != mappings.EXPORT
        else None
    )
    required = set(mappings.required_kinds(conn))
    return {
        "provider": provider,
        "accounts": list(
            AccountMapping.objects.filter(provider=provider).values(
                "kind", "key", "external_id", "code", "name"
            )
        ),
        "taxes": [
            {"tax_rate": m.tax_rate_id, "external_id": m.external_id, "name": m.name}
            for m in TaxMapping.objects.filter(provider=provider)
        ],
        "tracking": [
            {
                "branch": m.branch_id,
                "category_id": m.category_id,
                "option_id": m.option_id,
                "name": m.name,
            }
            for m in TrackingMapping.objects.filter(provider=provider)
        ],
        "kinds": [
            {"kind": kind, "name": str(label), "is_required": kind in required}
            for kind, label in mappings.KINDS.items()
        ],
        **_keys(),
        "problems": mappings.problems(provider, conn),
    }


class MappingSetView(APIView):
    permission_classes = [*AUTH, READ_MANAGE]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "provider", str, OpenApiParameter.PATH, enum=[*PROVIDERS, mappings.EXPORT]
            )
        ],
        responses=s.MappingSetSerializer,
    )
    def get(self, request: Request, provider: str) -> Response:
        """A mapping set (a provider's, or ``export`` for GL files) and what is missing."""
        if provider not in (*PROVIDERS, mappings.EXPORT):
            raise BusinessRuleViolation("Unknown mapping set.")
        return Response(s.MappingSetSerializer(_mapping_set(provider)).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "provider", str, OpenApiParameter.PATH, enum=[*PROVIDERS, mappings.EXPORT]
            )
        ],
        request=s.MappingSetSerializer,
        responses=s.MappingSetSerializer,
        examples=[
            OpenApiExample(
                "Xero",
                value={
                    "accounts": [
                        {"kind": "revenue", "key": "default", "external_id": "acc-200"},
                        {"kind": "clearing", "key": "provider:stripe", "external_id": "acc-091"},
                    ],
                    "taxes": [{"tax_rate": None, "external_id": "NONE"}],
                    "tracking": [],
                },
                request_only=True,
            )
        ],
    )
    def put(self, request: Request, provider: str) -> Response:
        """Replace the mapping set (accounts per kind and key, tax codes per tax rate,
        tracking options per branch)."""
        payload = s.MappingSetSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        conn = (
            AccountingConnection.objects.filter(provider=provider).order_by("-created_at").first()
        )
        services.save_mappings(
            provider,
            accounts=[dict(r) for r in data["accounts"]],
            taxes=[dict(r) for r in data["taxes"]],
            tracking=[dict(r) for r in data["tracking"]],
            conn=conn,
        )
        return Response(s.MappingSetSerializer(_mapping_set(provider)).data)


class ExternalRecordViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """The sync dashboard: each record's status in the ledger (``pending``, ``synced``,
    ``error`` with a readable reason, ``skipped``). Filter with ``status``,
    ``object_type`` and ``object_id`` (comma-separated, for sync badges)."""

    model = ExternalRecordLink
    permission_classes = [*AUTH, READ_MANAGE]

    def get_serializer_class(self) -> Any:
        if self.action == "retrieve":
            return s.ExternalRecordDetailSerializer
        return s.ExternalRecordLinkSerializer

    def get_tenant_queryset(self) -> Any:
        qs = selectors.records(self.request.user).order_by("-updated_at")
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("object_type"):
            qs = qs.filter(object_type=params["object_type"])
        if params.get("object_id"):
            qs = qs.filter(object_id__in=params["object_id"].split(",")[:200])
        if params.get("connection"):
            qs = qs.filter(connection__pk=params["connection"])
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, required=False, enum=ExternalRecordLink.Status.values),
            OpenApiParameter("object_type", str, required=False, enum=list(builders.OBJECT_TYPES)),
            OpenApiParameter("object_id", str, required=False, description="Comma-separated"),
            OpenApiParameter("connection", str, required=False),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses=s.ExternalRecordLinkSerializer)
    @action(detail=True, methods=["post"])
    def retry(self, request: Request, pk: str) -> Response:
        """Try again, e.g. after fixing a mapping ("re-map and retry") or reconnecting."""
        link = services.retry(self.get_object())
        return Response(s.ExternalRecordLinkSerializer(link).data)

    @extend_schema(request=s.SkipSerializer, responses=s.ExternalRecordLinkSerializer)
    @action(detail=True, methods=["post"])
    def skip(self, request: Request, pk: str) -> Response:
        """Leave this record out of the ledger (e.g. it was entered there by hand)."""
        payload = s.SkipSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        link = services.skip(self.get_object(), reason=payload.validated_data["reason"])
        return Response(s.ExternalRecordLinkSerializer(link).data)

    @extend_schema(request=None, responses=s.RetryResultSerializer)
    @action(detail=False, methods=["post"], url_path="retry-failed")
    def retry_failed(self, request: Request) -> Response:
        """Retry every record in error (up to 200)."""
        return Response({"retried": services.retry_failed()})


class ExportView(APIView):
    permission_classes = [*AUTH, HasPermission.for_(EXPORT)]

    @extend_schema(
        parameters=[s.ExportQuerySerializer],
        responses={(200, "application/octet-stream"): OpenApiResponse(OpenApiTypes.BINARY)},
    )
    def get(self, request: Request) -> HttpResponse:
        """A general ledger export for the period: generic CSV journal, Sage 50, MYOB or
        QuickBooks Desktop (IIF). Audited as an export."""
        from tutortrack.tenancy.models import Organisation

        query = s.ExportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        org = Organisation.objects.get(pk=require_organisation_id())
        start: date = data["start"]
        end: date = data["end"]
        name, content_type, content = exports.export(
            data["file_format"],
            provider=data["mapping_set"],
            start=start,
            end=end,
            tz=org.timezone,
        )
        audit.record(
            org,
            "gl_export",
            {"format": data["file_format"], "start": str(start), "end": str(end)},
        )
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response
