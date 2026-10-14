"""Xero Payroll API (E23-T10): connection state, employee links, the earnings rate, and the
timesheet syncs of approved pay runs."""

from __future__ import annotations

from typing import Any

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.context import require_organisation_id
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.permissions import HasMethodPermission
from tutortrack.integrations.providers import ProviderError
from tutortrack.people.models import TutorProfile

from .. import payroll_sync
from ..models import PayrollTimesheetSync
from .views import AUTH

PERMS: list[Any] = [
    *AUTH,
    HasMethodPermission.for_(
        {
            "GET": "integrations.accounting.view",
            "POST": "integrations.accounting.manage",
            "PUT": "integrations.accounting.manage",
        }
    ),
]


class PayrollTimesheetSyncSerializer(serializers.ModelSerializer):
    pay_run_number = serializers.CharField(source="pay_run.number", read_only=True)

    class Meta:
        model = PayrollTimesheetSync
        fields = [
            "id",
            "pay_run",
            "pay_run_number",
            "provider",
            "status",
            "results",
            "attempts",
            "error",
            "synced_at",
            "created_at",
        ]
        read_only_fields = fields


class EmployeeLinkSerializer(serializers.Serializer):
    tutor = serializers.UUIDField()
    tutor_name = serializers.CharField()
    employee_id = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    matched_by = serializers.CharField()


class UnlinkedTutorSerializer(serializers.Serializer):
    tutor = serializers.UUIDField()
    tutor_name = serializers.CharField()


class EarningsRateRefSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField(allow_blank=True)


class XeroPayrollStatusSerializer(serializers.Serializer):
    connected = serializers.BooleanField()
    connection_id = serializers.UUIDField(allow_null=True)
    account_name = serializers.CharField(allow_blank=True)
    earnings_rate = EarningsRateRefSerializer(allow_null=True)
    links = EmployeeLinkSerializer(many=True)
    unlinked = UnlinkedTutorSerializer(many=True)
    syncs = PayrollTimesheetSyncSerializer(many=True)


class XeroEmployeeSerializer(serializers.Serializer):
    id = serializers.CharField()
    email = serializers.CharField(allow_blank=True)
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)


class XeroEarningsRateSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    kind = serializers.CharField(allow_blank=True)


class LinkEmployeeSerializer(serializers.Serializer):
    tutor = serializers.UUIDField()
    employee_id = serializers.CharField(max_length=100)


class SyncRequestSerializer(serializers.Serializer):
    pay_run = serializers.UUIDField()


def _guard(call: Any) -> Any:
    try:
        return call()
    except ProviderError as exc:
        raise BusinessRuleViolation(str(exc)) from exc


class XeroPayrollView(APIView):
    """``GET /accounting/xero-payroll``: connection, employee links and recent syncs."""

    permission_classes = PERMS

    @extend_schema(responses=XeroPayrollStatusSerializer)
    def get(self, request: Request) -> Response:
        return Response(XeroPayrollStatusSerializer(payroll_sync.status()).data)


class XeroPayrollMatchView(APIView):
    """``POST /accounting/xero-payroll/match``: link employed tutors by email."""

    permission_classes = PERMS

    @extend_schema(request=None, responses=XeroPayrollStatusSerializer)
    def post(self, request: Request) -> Response:
        _guard(payroll_sync.match_employees)
        return Response(XeroPayrollStatusSerializer(payroll_sync.status()).data)


class XeroPayrollLinkView(APIView):
    """``PUT /accounting/xero-payroll/links``: link a tutor to a Xero employee by hand."""

    permission_classes = PERMS

    @extend_schema(request=LinkEmployeeSerializer, responses=XeroPayrollStatusSerializer)
    def put(self, request: Request) -> Response:
        payload = LinkEmployeeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tutor = get_object_or_404(TutorProfile.objects.all(), pk=payload.validated_data["tutor"])
        _guard(lambda: payroll_sync.link_employee(tutor, payload.validated_data["employee_id"]))
        return Response(XeroPayrollStatusSerializer(payroll_sync.status()).data)


class XeroPayrollEmployeesView(APIView):
    """``GET /accounting/xero-payroll/employees``: employees in Xero Payroll."""

    permission_classes = PERMS

    @extend_schema(responses=XeroEmployeeSerializer(many=True))
    def get(self, request: Request) -> Response:
        employees = _guard(lambda: payroll_sync._client().employees(payroll_sync._creds()))
        return Response(XeroEmployeeSerializer(employees, many=True).data)


class XeroPayrollEarningsRateView(APIView):
    """``GET`` the earnings rates; ``PUT`` the one tutors' hours are paid at."""

    permission_classes = PERMS

    @extend_schema(responses=XeroEarningsRateSerializer(many=True))
    def get(self, request: Request) -> Response:
        rates = _guard(lambda: payroll_sync._client().earnings_rates(payroll_sync._creds()))
        return Response(XeroEarningsRateSerializer(rates, many=True).data)

    @extend_schema(request=EarningsRateRefSerializer, responses=XeroPayrollStatusSerializer)
    def put(self, request: Request) -> Response:
        payload = EarningsRateRefSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        payroll_sync.set_earnings_rate(
            payload.validated_data["id"], payload.validated_data.get("name", "")
        )
        return Response(XeroPayrollStatusSerializer(payroll_sync.status()).data)


class XeroPayrollSyncView(APIView):
    """``POST /accounting/xero-payroll/sync``: (re)send an approved pay run's timesheets.
    Idempotent per tutor; send ``Idempotency-Key``."""

    permission_classes = PERMS

    @extend_schema(
        request=SyncRequestSerializer,
        responses={202: None},
        examples=[
            OpenApiExample("Retry", value={"pay_run": "5d0c2c1e-4a8d-4b8c-9a55-0f5e1d0a4c11"})
        ],
    )
    def post(self, request: Request) -> Response:
        from tutortrack.core.workflows import start
        from tutortrack.payroll.models import PayRun

        from ..payroll_processes import (
            PayrollSyncInput,
            XeroPayrollSyncWorkflow,
            payroll_sync_workflow_id,
        )

        payload = SyncRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        run = get_object_or_404(PayRun.objects.all(), pk=payload.validated_data["pay_run"])
        if run.status not in (
            PayRun.Status.APPROVED,
            PayRun.Status.PAYING,
            PayRun.Status.PAID,
            PayRun.Status.PARTIALLY_FAILED,
        ):
            raise BusinessRuleViolation("Approve the pay run first.")
        if payroll_sync.connection() is None:
            raise BusinessRuleViolation("Connect Xero Payroll first.")
        existing = PayrollTimesheetSync.objects.filter(pay_run=run).first()
        attempt = (existing.attempts if existing else 0) + 1
        org = require_organisation_id()
        start(
            XeroPayrollSyncWorkflow,
            PayrollSyncInput(organisation_id=str(org), pay_run_id=str(run.pk)),
            id=payroll_sync_workflow_id(org, run.pk, f"manual{attempt}"),
            subject=("pay_run", str(run.pk)),
        )
        return Response(status=status.HTTP_202_ACCEPTED)


class PayrollTimesheetSyncViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """``/accounting/xero-payroll/syncs``: timesheet syncs per pay run."""

    model = PayrollTimesheetSync
    serializer_class = PayrollTimesheetSyncSerializer
    permission_classes = PERMS

    def get_tenant_queryset(self) -> Any:
        return PayrollTimesheetSync.objects.select_related("pay_run")
