"""Client billing API (E10 §5). Financial POSTs honour ``Idempotency-Key``."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.money import Money
from tutortrack.core.permissions import (
    HasMethodPermission,
    HasOrganisation,
    scope_queryset,
)
from tutortrack.core.time import now
from tutortrack.people.models import Client
from tutortrack.tenancy.models import Organisation

from .. import ledger, pdf, selectors, services
from ..models import Charge, ClientLedgerEntry, CreditNote, Invoice, InvoiceRun, PaymentRequest
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def _pdf(content: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


# --- charges ------------------------------------------------------------------------------------


class ChargeFilter(filters.FilterSet):
    client = filters.UUIDFilter()
    student = filters.UUIDFilter()
    job = filters.UUIDFilter()
    lesson = filters.UUIDFilter()
    status = filters.MultipleChoiceFilter(choices=Charge.Status.choices)
    kind = filters.MultipleChoiceFilter(choices=Charge.Kind.choices)

    class Meta:
        model = Charge
        fields: list[str] = []


class ChargeViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Charges awaiting (or on) invoices. ``POST`` adds a one-off charge or (negative)
    discount."""

    model = Charge
    serializer_class = s.ChargeSerializer
    filterset_class = ChargeFilter
    permission_classes = perms({"GET": "billing.charge.view", "POST": "billing.charge.create"})

    def get_tenant_queryset(self) -> QuerySet[Charge]:
        qs = scope_queryset(self.request.user, Charge.objects.all(), "billing.charge.view")
        return qs.select_related("client", "student", "invoice")

    @extend_schema(request=s.AdHocChargeSerializer, responses={201: s.ChargeSerializer})
    def create(self, request: Request) -> Response:
        payload = s.AdHocChargeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        charge = services.create_ad_hoc_charge(user=request.user, **payload.validated_data)
        return Response(self.get_serializer(charge).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=s.ChargeSerializer)
    @action(
        detail=True, methods=["post"], permission_classes=perms({"POST": "billing.charge.void"})
    )
    def void(self, request: Request, pk: Any = None) -> Response:
        from django.db import transaction

        with transaction.atomic():
            charge = services.void_charge(self.get_object(), reason="manual")
        return Response(self.get_serializer(charge).data)


# --- invoices -----------------------------------------------------------------------------------


class InvoiceFilter(filters.FilterSet):
    client = filters.UUIDFilter()
    status = filters.MultipleChoiceFilter(choices=Invoice.Status.choices)
    overdue = filters.BooleanFilter(method="filter_overdue", label="Open and past due")
    run = filters.UUIDFilter(field_name="invoice_run")
    issued_from = filters.DateFilter(field_name="issue_date", lookup_expr="gte")
    issued_to = filters.DateFilter(field_name="issue_date", lookup_expr="lte")

    class Meta:
        model = Invoice
        fields: list[str] = []

    def filter_overdue(self, queryset: QuerySet[Invoice], name: str, value: bool) -> Any:
        if value:
            return queryset.filter(status__in=Invoice.OPEN, due_date__lt=services.org_today())
        return queryset


class InvoiceViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Invoices (FR-10-3/4). Drafts can be edited; issued invoices are immutable and are
    corrected with credit notes."""

    model = Invoice
    serializer_class = s.InvoiceSerializer
    filterset_class = InvoiceFilter
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_classes = perms(
        {
            "GET": "billing.invoice.view",
            "POST": "billing.invoice.create",
            "PATCH": "billing.invoice.create",
            "DELETE": "billing.invoice.create",
        }
    )

    def get_tenant_queryset(self) -> QuerySet[Invoice]:
        qs = selectors.invoices(self.request.user)
        if self.action != "list":
            qs = qs.prefetch_related("lines", "credit_notes__lines")
        return qs

    def get_serializer_class(self) -> Any:
        return s.InvoiceSerializer if self.action == "list" else s.InvoiceDetailSerializer

    def _out(self, invoice: Invoice) -> Response:
        return Response(
            s.InvoiceDetailSerializer(self.get_tenant_queryset().get(pk=invoice.pk)).data
        )

    @extend_schema(request=s.InvoiceCreateSerializer, responses={201: s.InvoiceDetailSerializer})
    def create(self, request: Request) -> Response:
        """A draft now from the client's uninvoiced charges."""
        payload = s.InvoiceCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        invoice = services.create_draft(
            payload.validated_data["client"], until=payload.validated_data["until"]
        )
        response = self._out(invoice)
        response.status_code = status.HTTP_201_CREATED
        return response

    @extend_schema(request=s.InvoiceUpdateSerializer, responses=s.InvoiceDetailSerializer)
    def partial_update(self, request: Request, pk: Any = None) -> Response:
        payload = s.InvoiceUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        return self._out(services.update_draft(self.get_object(), **payload.validated_data))

    def destroy(self, request: Request, pk: Any = None) -> Response:
        services.delete_draft(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=s.AddLineSerializer, responses=s.InvoiceDetailSerializer)
    @action(detail=True, methods=["post"], url_path="add-line")
    def add_line(self, request: Request, pk: Any = None) -> Response:
        payload = s.AddLineSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._out(
            services.add_line(self.get_object(), user=request.user, **payload.validated_data)
        )

    @extend_schema(request=s.RemoveLineSerializer, responses=s.InvoiceDetailSerializer)
    @action(detail=True, methods=["post"], url_path="remove-line")
    def remove_line(self, request: Request, pk: Any = None) -> Response:
        payload = s.RemoveLineSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        invoice = self.get_object()
        line = get_object_or_404(invoice.lines.all(), pk=payload.validated_data["line"])
        return self._out(services.remove_line(invoice, line))

    @extend_schema(request=None, responses=s.InvoiceDetailSerializer)
    @action(
        detail=True, methods=["post"], permission_classes=perms({"POST": "billing.invoice.issue"})
    )
    def issue(self, request: Request, pk: Any = None) -> Response:
        return self._out(services.issue_invoice(self.get_object(), user=request.user))

    @extend_schema(request=None, responses=s.InvoiceDetailSerializer)
    @action(
        detail=True, methods=["post"], permission_classes=perms({"POST": "billing.invoice.issue"})
    )
    def send(self, request: Request, pk: Any = None) -> Response:
        """Email the invoice (with its PDF) to the billing contact now."""
        from .. import tasks

        invoice = self.get_object()
        if invoice.status in {Invoice.Status.DRAFT, Invoice.Status.VOID}:
            raise ValidationError({"status": ["Issue the invoice before sending it."]})
        sent = tasks.send_invoice_email(
            organisation_id=str(invoice.organisation_id), invoice_id=str(invoice.pk), resend=True
        )
        if not sent:
            raise ValidationError({"email": ["The client has no billing email address."]})
        return self._out(invoice)

    @extend_schema(request=s.BillingReasonSerializer, responses=s.InvoiceDetailSerializer)
    @action(
        detail=True, methods=["post"], permission_classes=perms({"POST": "billing.invoice.void"})
    )
    def void(self, request: Request, pk: Any = None) -> Response:
        payload = s.BillingReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._out(
            services.void_invoice(
                self.get_object(), reason=payload.validated_data["reason"], user=request.user
            )
        )

    @extend_schema(request=s.BillingReasonSerializer, responses=s.InvoiceDetailSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="write-off",
        permission_classes=perms({"POST": "billing.invoice.write_off"}),
    )
    def write_off(self, request: Request, pk: Any = None) -> Response:
        payload = s.BillingReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._out(
            services.write_off(
                self.get_object(), reason=payload.validated_data["reason"], user=request.user
            )
        )

    @extend_schema(request=s.CreditNoteRequestSerializer, responses={201: s.CreditNoteSerializer})
    @action(
        detail=True,
        methods=["post"],
        url_path="credit-note",
        permission_classes=perms({"POST": "billing.credit_note.issue"}),
    )
    def credit_note(self, request: Request, pk: Any = None) -> Response:
        payload = s.CreditNoteRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        invoice = self.get_object()
        data = payload.validated_data
        lines = None
        if data.get("lines"):
            by_id = {str(line.pk): line for line in invoice.lines.all()}
            lines = []
            for row in data["lines"]:
                line = by_id.get(str(row["line"]))
                if line is None:
                    raise ValidationError({"lines": ["That line isn't on this invoice."]})
                lines.append({"line": line, "amount": Money(row["amount"], invoice.currency)})
        note = services.create_credit_note(
            invoice,
            reason=data["reason"],
            application=data["application"],
            lines=lines,
            user=request.user,
        )
        return Response(s.CreditNoteSerializer(note).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.ApplyCreditSerializer, responses=s.AppliedSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="apply-credit",
        permission_classes=perms({"POST": "billing.credit_note.issue"}),
    )
    def apply_credit(self, request: Request, pk: Any = None) -> Response:
        payload = s.ApplyCreditSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        invoice = self.get_object()
        amount = payload.validated_data.get("amount")
        applied = services.apply_credit(
            invoice,
            amount=Money(amount, invoice.currency) if amount is not None else None,
            user=request.user,
        )
        invoice.refresh_from_db()
        return Response(s.AppliedSerializer({"applied": applied, "invoice": invoice}).data)

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def pdf(self, request: Request, pk: Any = None) -> HttpResponse:
        invoice = self.get_object()
        name = invoice.number or f"draft-{invoice.pk}"
        return _pdf(pdf.invoice_pdf(invoice), f"{name}.pdf")


class CreditNoteViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    model = CreditNote
    serializer_class = s.CreditNoteSerializer
    permission_classes = perms({"GET": "billing.invoice.view"})
    filterset_fields: list[str] = []

    def get_tenant_queryset(self) -> QuerySet[CreditNote]:
        qs = scope_queryset(self.request.user, CreditNote.objects.all(), "billing.invoice.view")
        client = self.request.query_params.get("client")
        if client:
            qs = qs.filter(client_id=client)
        return qs.select_related("invoice").prefetch_related("lines")


# --- invoice runs -------------------------------------------------------------------------------


class InvoiceRunViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Invoice runs (FR-10-3, TW1). ``POST`` starts one (idempotent per branch, period and
    mode); ``approve`` issues the drafts without waiting for the review period."""

    model = InvoiceRun
    serializer_class = s.InvoiceRunSerializer
    permission_classes = perms({"GET": "billing.invoice.view", "POST": "billing.invoice.create"})

    def get_tenant_queryset(self) -> QuerySet[InvoiceRun]:
        return scope_queryset(self.request.user, InvoiceRun.objects.all(), "billing.invoice.view")

    @extend_schema(
        request=s.InvoiceRunCreateSerializer,
        responses={201: s.InvoiceRunSerializer, 200: s.InvoiceRunSerializer},
    )
    def create(self, request: Request) -> Response:
        payload = s.InvoiceRunCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        run, created = services.create_run(user=request.user, **payload.validated_data)
        return Response(
            self.get_serializer(run).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(request=s.InvoiceRunCreateSerializer, responses=s.RunPreviewSerializer)
    @action(detail=False, methods=["post"])
    def preview(self, request: Request) -> Response:
        """How many clients and charges a run would invoice (nothing is created)."""
        payload = s.InvoiceRunCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        charges = Charge.objects.filter(
            status=Charge.Status.UNINVOICED,
            invoice__isnull=True,
            date__lte=data["period_end"],
        )
        if data.get("branch"):
            charges = charges.filter(branch=data["branch"])
        if data.get("client"):
            charges = charges.filter(client=data["client"])
        totals: dict[str, Decimal] = {}
        for currency, gross in charges.values_list("currency", "gross_amount"):
            totals[currency] = totals.get(currency, Decimal(0)) + gross
        return Response(
            {
                "clients": charges.values("client_id").distinct().count(),
                "charges": charges.count(),
                "totals": {k: str(v) for k, v in totals.items()},
            }
        )

    @extend_schema(request=None, responses=s.InvoiceRunSerializer)
    @action(
        detail=True, methods=["post"], permission_classes=perms({"POST": "billing.invoice.issue"})
    )
    def approve(self, request: Request, pk: Any = None) -> Response:
        return Response(
            self.get_serializer(services.approve_run(self.get_object(), user=request.user)).data
        )


# --- payment requests ---------------------------------------------------------------------------


class PaymentRequestFilter(filters.FilterSet):
    client = filters.UUIDFilter()
    status = filters.MultipleChoiceFilter(choices=PaymentRequest.Status.choices)

    class Meta:
        model = PaymentRequest
        fields: list[str] = []


class PaymentRequestViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Payment requests (FR-10-6): top-ups for prepaid credit. Not tax invoices."""

    model = PaymentRequest
    serializer_class = s.PaymentRequestSerializer
    filterset_class = PaymentRequestFilter
    permission_classes = perms(
        {"GET": "billing.payment_request.view", "POST": "billing.payment_request.manage"}
    )

    def get_tenant_queryset(self) -> QuerySet[PaymentRequest]:
        return scope_queryset(
            self.request.user, PaymentRequest.objects.all(), "billing.payment_request.view"
        ).select_related("client")

    @extend_schema(
        request=s.PaymentRequestCreateSerializer, responses={201: s.PaymentRequestSerializer}
    )
    def create(self, request: Request) -> Response:
        payload = s.PaymentRequestCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        created = services.create_payment_request(user=request.user, **payload.validated_data)
        return Response(self.get_serializer(created).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.BulkRequestSerializer, responses={201: s.BulkRequestResultSerializer})
    @action(detail=False, methods=["post"])
    def bulk(self, request: Request) -> Response:
        payload = s.BulkRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        clients = scope_queryset(request.user, Client.objects.all(), "people.client.view")
        ids = data.pop("clients", None)
        clients = (
            clients.filter(pk__in=ids)
            if ids
            else clients.filter(status=Client.Status.ACTIVE, jobs__billing_method="prepaid_credit")
        ).distinct()
        created = services.bulk_payment_requests(list(clients), user=request.user, **data)
        return Response(
            {"created": self.get_serializer(created, many=True).data},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=None, responses=s.PaymentRequestSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        return Response(
            self.get_serializer(
                services.cancel_payment_request(self.get_object(), user=request.user)
            ).data
        )


# --- client billing views -----------------------------------------------------------------------


def _client(request: Request, client_id: Any) -> Client:
    qs = scope_queryset(request.user, Client.objects.all(), "people.client.view")
    return get_object_or_404(qs, pk=client_id)


def _currency(request: Request, client: Client) -> str:
    return (request.query_params.get("currency") or client.currency).upper()


class ClientBalanceView(APIView):
    permission_classes = perms({"GET": "billing.invoice.view"})

    @extend_schema(responses=s.BalancesSerializer, parameters=[OpenApiParameter("currency", str)])
    def get(self, request: Request, client_id: Any) -> Response:
        client = _client(request, client_id)
        return Response(
            s.BalancesSerializer(ledger.balances(client, _currency(request, client))).data
        )


class ClientLedgerView(APIView):
    """The client's ledger entries, newest first (append-only)."""

    permission_classes = perms({"GET": "billing.ledger.view", "POST": "billing.ledger.adjust"})

    @extend_schema(
        responses=s.LedgerEntrySerializer(many=True),
        parameters=[OpenApiParameter("currency", str)],
    )
    def get(self, request: Request, client_id: Any) -> Response:
        client = _client(request, client_id)
        rows = ClientLedgerEntry.objects.filter(
            client=client, currency=_currency(request, client)
        ).order_by("-occurred_at", "-created_at")[:500]
        return Response(s.LedgerEntrySerializer(rows, many=True).data)

    @extend_schema(request=s.LedgerAdjustSerializer, responses={201: s.LedgerEntrySerializer})
    def post(self, request: Request, client_id: Any) -> Response:
        client = _client(request, client_id)
        payload = s.LedgerAdjustSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        entry = services.adjust_ledger(client, user=request.user, **payload.validated_data)
        return Response(s.LedgerEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


class ClientStatementView(APIView):
    permission_classes = perms({"GET": "billing.ledger.view"})

    @extend_schema(
        responses={200: s.StatementSerializer, (200, "application/pdf"): OpenApiTypes.BINARY},
        parameters=[
            OpenApiParameter("from", OpenApiTypes.DATE),
            OpenApiParameter("to", OpenApiTypes.DATE),
            OpenApiParameter("currency", str),
            OpenApiParameter("pdf", bool, description="Download as PDF instead of JSON"),
        ],
    )
    def get(self, request: Request, client_id: Any) -> Any:
        client = _client(request, client_id)
        end = parse_date(request.query_params.get("to") or "") or now().date()
        start = parse_date(request.query_params.get("from") or "") or end - timedelta(days=30)
        if start > end:
            raise ValidationError({"from": ["The start is after the end."]})
        org = Organisation.objects.get(pk=client.organisation_id)
        data = selectors.statement(client, _currency(request, client), start, end, org.timezone)
        if request.query_params.get("pdf") in {"1", "true"}:
            return _pdf(pdf.statement_pdf(client, data), f"statement-{end}.pdf")
        return Response(s.StatementSerializer(data).data)


class AgeingView(APIView):
    """Open invoices by client in ageing buckets (the overdue report)."""

    permission_classes = perms({"GET": "billing.invoice.view"})

    @extend_schema(
        responses=s.AgeingRowSerializer(many=True), parameters=[OpenApiParameter("currency", str)]
    )
    def get(self, request: Request) -> Response:
        from tutortrack.core.context import require_organisation_id

        org = Organisation.objects.get(pk=require_organisation_id())
        currency = (request.query_params.get("currency") or org.default_currency).upper()
        return Response(
            s.AgeingRowSerializer(selectors.ageing_report(request.user, currency), many=True).data
        )
