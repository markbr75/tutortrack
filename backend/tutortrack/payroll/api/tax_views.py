"""Payroll Phase 3 API (E12-T12): tutors' US tax identity, 1099-NEC totals, finalised
filings and their CSV export, the tutor's own tax summary, and the Wise webhook."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.permissions import scope_queryset
from tutortrack.core.time import now

from .. import services, tax_forms, wise_payouts
from ..models import TaxFormFiling
from . import serializers as s
from .views import AUTH, _my_tutor, _tutor, perms


def _year(value: Any) -> int:
    try:
        year = int(value)
    except (TypeError, ValueError):
        year = now().year - 1
    return min(max(year, 2000), now().year)


class TaxIdentityView(APIView):
    """``/tutors/{id}/tax-identity``: the tutor's SSN, ITIN or EIN for 1099-NEC forms. Stored
    encrypted; masked unless ``?full=true`` with ``payroll.tax.view`` (audited)."""

    permission_classes = perms({"GET": "payroll.view", "PUT": "payroll.profile.manage"})

    @extend_schema(
        parameters=[OpenApiParameter("full", bool)], responses=s.TaxIdentityOutSerializer
    )
    def get(self, request: Request, pk: str) -> Response:
        profile = services.profile_for(_tutor(pk))
        full = request.query_params.get("full") == "true"
        return Response(tax_forms.tax_identity(profile, user=request.user, full=full))

    @extend_schema(
        request=s.TaxIdentitySerializer,
        responses=s.TaxIdentityOutSerializer,
        examples=[OpenApiExample("SSN", value={"tin_type": "ssn", "tin": "123-45-6789"})],
    )
    def put(self, request: Request, pk: str) -> Response:
        payload = s.TaxIdentitySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        profile = tax_forms.set_tax_identity(_tutor(pk), **payload.validated_data)
        return Response(tax_forms.tax_identity(profile, user=request.user, full=False))


class MyTaxIdentityView(APIView):
    """The tutor's own tax id (tutor portal): write-only, shown masked."""

    permission_classes = AUTH

    @extend_schema(responses=s.TaxIdentityOutSerializer)
    def get(self, request: Request) -> Response:
        profile = services.profile_for(_my_tutor(request))
        return Response(tax_forms.tax_identity(profile, user=request.user, full=False))

    @extend_schema(request=s.TaxIdentitySerializer, responses=s.TaxIdentityOutSerializer)
    def put(self, request: Request) -> Response:
        payload = s.TaxIdentitySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        profile = tax_forms.set_tax_identity(_my_tutor(request), **payload.validated_data)
        return Response(tax_forms.tax_identity(profile, user=request.user, full=False))


class Form1099View(APIView):
    """``GET /payroll/tax-years/{year}/1099``: box 1 per contractor tutor paid in USD."""

    permission_classes = perms({"GET": "payroll.view"})

    @extend_schema(responses=s.Form1099SummarySerializer)
    def get(self, request: Request, year: int) -> Response:
        return Response(s.Form1099SummarySerializer(tax_forms.summary(_year(year))).data)


class Form1099FinaliseView(APIView):
    """``POST /payroll/tax-years/{year}/1099/finalise``: freeze the figures (immutable
    filings; changed figures are filed as corrections). Send ``Idempotency-Key``."""

    permission_classes = perms({"POST": "payroll.tax.manage"})

    @extend_schema(request=None, responses={201: s.TaxFormFilingSerializer(many=True)})
    def post(self, request: Request, year: int) -> Response:
        filings = tax_forms.finalise(_year(year), user=request.user)
        return Response(
            s.TaxFormFilingSerializer(filings, many=True).data, status=status.HTTP_201_CREATED
        )


class Form1099ExportView(APIView):
    """``GET /payroll/tax-years/{year}/1099/export``: the IRIS-style CSV; ``full_tin=true``
    needs ``payroll.tax.view`` and is audited."""

    permission_classes = perms({"GET": "payroll.view"})

    @extend_schema(
        parameters=[OpenApiParameter("full_tin", bool)],
        responses={(200, "text/csv"): OpenApiTypes.BINARY},
    )
    def get(self, request: Request, year: int) -> HttpResponse:
        full = request.query_params.get("full_tin") == "true"
        filename, content = tax_forms.export_csv(_year(year), user=request.user, full_tin=full)
        response = HttpResponse(content, content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-store"
        return response


class TaxFormFilingViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Finalised 1099-NEC filings (immutable); tutors see their own."""

    model = TaxFormFiling
    serializer_class = s.TaxFormFilingSerializer
    permission_classes = perms({"GET": "payroll.view"})

    def get_tenant_queryset(self) -> Any:
        qs = TaxFormFiling.objects.select_related("tutor")
        year = self.request.query_params.get("tax_year")
        if year and year.isdigit():
            qs = qs.filter(tax_year=int(year))
        return scope_queryset(self.request.user, qs, "payroll.view")

    @extend_schema(parameters=[OpenApiParameter("tax_year", int)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)


class MyTaxSummaryView(APIView):
    """``GET /me/tax-summary?year=``: what the tutor was paid in a US tax year."""

    permission_classes = AUTH

    @extend_schema(parameters=[OpenApiParameter("year", int)], responses=s.MyTaxSummarySerializer)
    def get(self, request: Request) -> Response:
        tutor = _my_tutor(request)
        return Response(tax_forms.tutor_summary(tutor, _year(request.query_params.get("year"))))


@csrf_exempt
def wise_webhook(request: HttpRequest) -> HttpResponse:
    """``POST /webhooks/wise``: transfer state changes, RSA-signed by Wise."""
    if request.method != "POST":
        return HttpResponse(status=405)
    ok = wise_payouts.handle_webhook(request.body, request.headers.get("X-Signature-SHA256", ""))
    return HttpResponse(status=200 if ok else 400)
