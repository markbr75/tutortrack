"""Payments API (E11 §5): providers, saved methods, payments, refunds, the public pay and
setup pages, and provider webhooks."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.billing.models import Invoice, PaymentRequest
from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import NotFound
from tutortrack.core.money import Money
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, scope_queryset
from tutortrack.people.models import Client
from tutortrack.tenancy.settings_service import get_setting

from .. import pdf, services
from ..models import (
    AutoPayConsent,
    Dispute,
    Payment,
    PaymentMethod,
    ProviderAccount,
    ProviderPayout,
)
from ..providers import ProviderError
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def _client_ip(request: Request) -> str | None:
    return request.META.get("REMOTE_ADDR")


# --- providers (T01/T02) ------------------------------------------------------------------------


class ProviderAccountViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Connected payment accounts (Settings → Payments)."""

    model = ProviderAccount
    serializer_class = s.ProviderAccountSerializer
    pagination_class = None
    permission_classes = perms({"GET": "payments.payment.view", "POST": "payments.provider.manage"})

    def get_tenant_queryset(self) -> QuerySet[ProviderAccount]:
        return ProviderAccount.objects.exclude(status=ProviderAccount.Status.DISCONNECTED)

    @extend_schema(request=s.ConnectSerializer, responses=s.OnboardingSerializer)
    @action(detail=False, methods=["post"], url_path="stripe/connect")
    def connect(self, request: Request) -> Response:
        """Start or resume Stripe onboarding; open the returned ``url``."""
        payload = s.ConnectSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = services.connect_stripe(user=request.user, **payload.validated_data)
        return Response(
            {"account": s.ProviderAccountSerializer(result.account).data, "url": result.url}
        )

    @extend_schema(request=None, responses=s.ProviderAccountSerializer)
    @action(detail=True, methods=["post"])
    def refresh(self, request: Request, pk: Any = None) -> Response:
        return Response(self.get_serializer(services.refresh_account(self.get_object())).data)

    @extend_schema(request=None, responses=s.ProviderAccountSerializer)
    @action(detail=True, methods=["post"])
    def disconnect(self, request: Request, pk: Any = None) -> Response:
        return Response(
            self.get_serializer(services.disconnect(self.get_object(), user=request.user)).data
        )


# --- saved methods and auto-pay (T03) -----------------------------------------------------------


def _client(request: Request, client_id: Any) -> Client:
    qs = scope_queryset(request.user, Client.objects.all(), "people.client.view")
    return get_object_or_404(qs, pk=client_id)


def _methods_out(client: Client) -> dict[str, Any]:
    consent = AutoPayConsent.objects.filter(client=client, withdrawn_at__isnull=True).first()
    methods = PaymentMethod.objects.filter(client=client, status=PaymentMethod.Status.ACTIVE)
    return {
        "auto_pay": client.auto_pay,
        "consent_given_at": consent.given_at if consent else None,
        "methods": s.PaymentMethodSerializer(methods, many=True).data,
    }


class ClientMethodsView(APIView):
    permission_classes = perms({"GET": "payments.payment.view"})

    @extend_schema(responses=s.ClientMethodsSerializer)
    def get(self, request: Request, client_id: Any) -> Response:
        return Response(_methods_out(_client(request, client_id)))


class ClientSetupLinkView(APIView):
    """A link the client opens to save a card or mandate (and opt in to auto-pay)."""

    permission_classes = perms({"POST": "payments.autopay.manage"})

    @extend_schema(request=None, responses={201: s.SetupLinkOutSerializer})
    def post(self, request: Request, client_id: Any) -> Response:
        url = services.create_setup_link(_client(request, client_id), user=request.user)
        return Response({"url": url}, status=status.HTTP_201_CREATED)


class ClientAutoPayView(APIView):
    permission_classes = perms({"POST": "payments.autopay.manage"})

    @extend_schema(request=s.AutoPaySerializer, responses=s.ClientMethodsSerializer)
    def post(self, request: Request, client_id: Any) -> Response:
        payload = s.AutoPaySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        client = services.set_autopay(
            _client(request, client_id), payload.validated_data["enabled"], user=request.user
        )
        return Response(_methods_out(client))


class PaymentMethodViewSet(
    TenantScopedViewMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    model = PaymentMethod
    serializer_class = s.PaymentMethodSerializer
    permission_classes = perms(
        {"POST": "payments.autopay.manage", "DELETE": "payments.autopay.manage"}
    )

    def get_tenant_queryset(self) -> QuerySet[PaymentMethod]:
        return PaymentMethod.objects.filter(status=PaymentMethod.Status.ACTIVE)

    def perform_destroy(self, instance: PaymentMethod) -> None:
        services.remove_method(instance, user=self.request.user)

    @extend_schema(request=None, responses=s.PaymentMethodSerializer)
    @action(detail=True, methods=["post"], url_path="default")
    def make_default(self, request: Request, pk: Any = None) -> Response:
        return Response(self.get_serializer(services.set_default_method(self.get_object())).data)


# --- payments (T04/T07/T09) ---------------------------------------------------------------------


class PaymentFilter(filters.FilterSet):
    client = filters.UUIDFilter()
    status = filters.MultipleChoiceFilter(choices=Payment.Status.choices)
    method = filters.MultipleChoiceFilter(choices=Payment.Method.choices)

    class Meta:
        model = Payment
        fields: list[str] = []


def _allocations(
    rows: list[dict[str, Any]] | None, currency: str
) -> list[tuple[Invoice, Money]] | None:
    if rows is None:
        return None
    return [(row["invoice"], Money(row["amount"], currency)) for row in rows]


class PaymentViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Payments (FR-11-4..7). ``POST`` records a manual payment (bank transfer, cash,
    cheque, other) and allocates it, oldest invoices first unless told otherwise."""

    model = Payment
    serializer_class = s.PaymentSerializer
    filterset_class = PaymentFilter
    permission_classes = perms({"GET": "payments.payment.view", "POST": "payments.payment.record"})

    def get_tenant_queryset(self) -> QuerySet[Payment]:
        qs = scope_queryset(self.request.user, Payment.objects.all(), "payments.payment.view")
        return qs.select_related("client").prefetch_related("allocations__invoice", "refunds")

    @extend_schema(request=s.RecordPaymentSerializer, responses={201: s.PaymentSerializer})
    def create(self, request: Request) -> Response:
        payload = s.RecordPaymentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        amount = data.pop("amount")
        payment = services.record_manual_payment(
            amount=amount,
            allocations=_allocations(data.pop("allocations", None), amount.currency),
            user=request.user,
            **data,
        )
        return Response(
            self.get_serializer(self.get_tenant_queryset().get(pk=payment.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=s.AllocateSerializer, responses=s.PaymentSerializer)
    @action(
        detail=True,
        methods=["post"],
        permission_classes=perms({"POST": "payments.payment.allocate"}),
    )
    def allocate(self, request: Request, pk: Any = None) -> Response:
        """Replace the payment's allocations (re-allocation is audited)."""
        payment = self.get_object()
        payload = s.AllocateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.reallocate(
            payment,
            _allocations(payload.validated_data["allocations"], payment.currency) or [],
            user=request.user,
        )
        return Response(self.get_serializer(self.get_tenant_queryset().get(pk=payment.pk)).data)

    @extend_schema(request=s.RefundRequestSerializer, responses={201: s.RefundSerializer})
    @action(
        detail=True, methods=["post"], permission_classes=perms({"POST": "payments.payment.refund"})
    )
    def refund(self, request: Request, pk: Any = None) -> Response:
        payment = self.get_object()
        payload = s.RefundRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        refund = services.refund_payment(
            payment,
            amount=Money(data["amount"], payment.currency) if data.get("amount") else None,
            reason=data["reason"],
            credit_note=data["credit_note"],
            user=request.user,
        )
        return Response(s.RefundSerializer(refund).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def receipt(self, request: Request, pk: Any = None) -> HttpResponse:
        payment = self.get_object()
        response = HttpResponse(pdf.receipt_pdf(payment), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="receipt-{payment.pk}.pdf"'
        return response


class InvoiceCollectView(APIView):
    """Charge the client's default method for this invoice now (FR-11-3). 409
    ``collection_in_progress`` while another attempt is in flight."""

    permission_classes = perms({"POST": "payments.payment.record"})

    @extend_schema(request=None, responses={202: None})
    def post(self, request: Request, invoice_id: Any) -> Response:
        qs = scope_queryset(request.user, Invoice.objects.all(), "billing.invoice.view")
        services.start_collection(get_object_or_404(qs.select_related("client"), pk=invoice_id))
        return Response(status=status.HTTP_202_ACCEPTED)


class DisputeViewSet(TenantScopedViewMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    model = Dispute
    serializer_class = s.DisputeSerializer
    permission_classes = perms({"GET": "payments.payment.view"})

    def get_tenant_queryset(self) -> QuerySet[Dispute]:
        return Dispute.objects.all()


class PayoutViewSet(TenantScopedViewMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Provider payouts (FR-11-10): what reached the bank, for reconciliation (E23)."""

    model = ProviderPayout
    serializer_class = s.PayoutSerializer
    permission_classes = perms({"GET": "payments.payment.view"})

    def get_tenant_queryset(self) -> QuerySet[ProviderPayout]:
        return ProviderPayout.objects.all()


# --- public pay page (T05) ----------------------------------------------------------------------


def _target(token: str) -> Invoice | PaymentRequest:
    target = services.pay_target(token)
    if target is None:
        raise NotFound()
    return target


def _page(target: Invoice | PaymentRequest) -> dict[str, Any]:
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=target.organisation_id)
    account = services.account_for(target.branch_id)
    invoice = isinstance(target, Invoice)
    if isinstance(target, Invoice):
        lines = [
            {"description": line.description, "amount": line.gross} for line in target.lines.all()
        ]
        total = target.total
    else:
        lines = [{"description": target.description, "amount": target.amount}]
        total = target.amount
    return {
        "kind": "invoice" if invoice else "payment_request",
        "organisation": org.name,
        "number": target.number,
        "client_name": target.client.display_name,
        "status": target.status,
        "due_date": target.due_date,
        "total": total,
        "amount_due": services.amount_due(target),
        "lines": lines,
        "allow_partial": bool(get_setting("payments.allow_partial")),
        "can_pay_online": bool(account and account.status == ProviderAccount.Status.ACTIVE),
        "has_pdf": invoice,
    }


class PublicPayView(APIView):
    """The hosted pay page for an invoice or payment request (link from the email)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(responses=s.PayPageSerializer)
    def get(self, request: Request, token: str) -> Response:
        return Response(s.PayPageSerializer(_page(_target(token))).data)


class PublicPayIntentView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(request=s.PayIntentRequestSerializer, responses=s.PayIntentSerializer)
    def post(self, request: Request, token: str) -> Response:
        target = _target(token)
        payload = s.PayIntentRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        amount = payload.validated_data.get("amount")
        out = services.create_pay_intent(
            target,
            amount=Money(amount, target.currency) if amount else None,
            save_method=payload.validated_data["save_method"],
        )
        return Response(s.PayIntentSerializer(out).data)


class PublicPayConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(request=s.ConfirmSerializer, responses=s.ConfirmResultSerializer)
    def post(self, request: Request, token: str) -> Response:
        payload = s.ConfirmSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = services.confirm_pay_intent(_target(token), payload.validated_data["intent"])
        return Response({"status": result})


class PublicPayPdfView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    def get(self, request: Request, token: str) -> HttpResponse:
        from tutortrack.billing import pdf as billing_pdf

        target = _target(token)
        if not isinstance(target, Invoice):
            raise NotFound()
        response = HttpResponse(billing_pdf.invoice_pdf(target), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{target.number}.pdf"'
        return response


class PublicSetupView(APIView):
    """Save a payment method from a setup link (and, if the client agrees, turn on
    auto-pay with their recorded consent)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    def _link(self, token: str) -> Any:
        link = services.setup_link(token)
        if link is None:
            raise NotFound()
        return link

    @extend_schema(responses=s.SetupPageSerializer)
    def get(self, request: Request, token: str) -> Response:
        from tutortrack.tenancy.models import Organisation

        link = self._link(token)
        org = Organisation.objects.get(pk=link.organisation_id)
        data = services.start_setup(link.client)
        return Response(
            s.SetupPageSerializer(
                {"organisation": org.name, "client_name": link.client.display_name, **data}
            ).data
        )

    @extend_schema(request=s.SetupCompleteSerializer, responses=s.SetupDoneSerializer)
    def post(self, request: Request, token: str) -> Response:
        link = self._link(token)
        payload = s.SetupCompleteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        method = services.complete_setup(
            link,
            payload.validated_data["intent"],
            autopay=payload.validated_data["autopay"],
            ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        link.client.refresh_from_db()
        return Response(
            {"method": s.PaymentMethodSerializer(method).data, "auto_pay": link.client.auto_pay}
        )


# --- webhooks -----------------------------------------------------------------------------------


@csrf_exempt
def stripe_webhook(request: HttpRequest) -> HttpResponse:
    """``POST /webhooks/stripe`` (Connect events). Verified, stored, processed async."""
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        services.ingest_webhook("stripe", request.body, request.headers.get("Stripe-Signature", ""))
    except ProviderError:
        return HttpResponse(status=400)
    return HttpResponse(status=200)
