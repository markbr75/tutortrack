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
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
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
    BankStatementImport,
    BankTransaction,
    Dispute,
    Payment,
    PaymentGroup,
    PaymentMethod,
    ProviderAccount,
    ProviderMigration,
    ProviderPayout,
    ReconciliationMatch,
)
from ..providers import ProviderError
from ..surcharges import surcharge_percent
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

    @extend_schema(request=s.ConnectSerializer, responses=s.OnboardingSerializer)
    @action(detail=False, methods=["post"], url_path=r"(?P<provider>gocardless|paypal)/connect")
    def connect_partner(self, request: Request, provider: str) -> Response:
        """Start connecting GoCardless (partner OAuth) or PayPal (partner referral); open
        the returned ``url``. The provider sends the admin back to Settings → Payments with
        ``state`` and ``code`` (PayPal: ``merchantIdInPayPal``) for ``complete``."""
        payload = s.ConnectSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = services.connect_partner(
            provider, branch=payload.validated_data.get("branch"), user=request.user
        )
        return Response(
            {"account": s.ProviderAccountSerializer(result.account).data, "url": result.url}
        )

    @extend_schema(request=s.PartnerCompleteSerializer, responses=s.ProviderAccountSerializer)
    @action(detail=False, methods=["post"], url_path=r"(?P<provider>gocardless|paypal)/complete")
    def complete_partner(self, request: Request, provider: str) -> Response:
        payload = s.PartnerCompleteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        account = services.complete_partner(provider, user=request.user, **payload.validated_data)
        return Response(s.ProviderAccountSerializer(account).data)

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

    @extend_schema(
        request=s.BulkPaymentSerializer,
        responses={201: s.PaymentSerializer(many=True)},
        examples=[
            OpenApiExample(
                "Two bank transfers",
                request_only=True,
                value={
                    "rows": [
                        {
                            "client": "8b0d6c1e-2f4e-4c1a-9d7e-2a6b1f0c3d4e",
                            "amount": {"amount": "120.00", "currency": "GBP"},
                            "method": "bank_transfer",
                            "reference": "PATEL OCT",
                        },
                        {
                            "client": "5c2f8a3b-7e1d-4b6a-8c9f-0d1e2f3a4b5c",
                            "amount": {"amount": "45.00", "currency": "GBP"},
                            "method": "cash",
                        },
                    ]
                },
            )
        ],
    )
    @action(detail=False, methods=["post"], pagination_class=None)
    def bulk(self, request: Request) -> Response:
        """Record many manual payments at once (FR-11-5 bulk entry grid, gap G3). Each pays
        that client's oldest invoices first. All or nothing; send ``Idempotency-Key``."""
        payload = s.BulkPaymentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        payments = services.record_bulk_payments(
            [dict(row) for row in payload.validated_data["rows"]], user=request.user
        )
        rows = self.get_tenant_queryset().filter(pk__in=[p.pk for p in payments])
        return Response(self.get_serializer(rows, many=True).data, status=status.HTTP_201_CREATED)

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
    providers = services.pay_providers(target.branch_id)
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
        "can_pay_online": bool(providers),
        "has_pdf": invoice,
        "providers": providers,
        "card_surcharge_percent": (
            str(surcharge_percent(target.branch_id).normalize())
            if invoice and "stripe" in providers
            else "0"
        ),
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
            provider=payload.validated_data["provider"],
        )
        return Response(s.PayIntentSerializer(out).data)


class PublicPayConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(request=s.ConfirmSerializer, responses=s.ConfirmResultSerializer)
    def post(self, request: Request, token: str) -> Response:
        payload = s.ConfirmSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = services.confirm_pay_intent(
            _target(token),
            payload.validated_data["intent"],
            provider=payload.validated_data["provider"],
        )
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

    @extend_schema(
        responses=s.SetupPageSerializer,
        parameters=[OpenApiParameter("provider", str, description="stripe or gocardless")],
    )
    def get(self, request: Request, token: str) -> Response:
        from tutortrack.tenancy.models import Organisation

        link = self._link(token)
        org = Organisation.objects.get(pk=link.organisation_id)
        provider = link.provider or request.query_params.get("provider", "")
        data = services.start_setup(
            link.client,
            provider=provider,
            return_url=services.tenant_url(f"/pay/setup/{token}?provider=gocardless"),
        )
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
            provider=payload.validated_data["provider"],
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


@csrf_exempt
def gocardless_webhook(request: HttpRequest) -> HttpResponse:
    """``POST /webhooks/gocardless``: a signed batch of events (HMAC ``Webhook-Signature``),
    stored and processed async. GoCardless expects 498 for a bad signature."""
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        services.ingest_partner_webhooks("gocardless", request.body, dict(request.headers))
    except ProviderError:
        return HttpResponse(status=498)
    return HttpResponse(status=200)


@csrf_exempt
def paypal_webhook(request: HttpRequest) -> HttpResponse:
    """``POST /webhooks/paypal``: verified with PayPal, stored and processed async."""
    if request.method != "POST":
        return HttpResponse(status=405)
    headers = {k.upper(): v for k, v in request.headers.items()}
    try:
        services.ingest_partner_webhooks("paypal", request.body, headers)
    except ProviderError:
        return HttpResponse(status=400)
    return HttpResponse(status=200)


# --- Phase 2: split payments, bank reconciliation, provider migration --------------------------


class SplitPaymentView(APIView):
    """Record one receipt split across several clients (FR-11-6), e.g. a school paying for
    many students. Each share becomes that client's payment."""

    permission_classes = perms({"POST": "payments.payment.record"})

    @extend_schema(request=s.SplitPaymentSerializer, responses={201: s.PaymentGroupSerializer})
    def post(self, request: Request) -> Response:
        payload = s.SplitPaymentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        amount = data.pop("amount")
        parts = [
            {
                "client": part["client"],
                "amount": Money(part["amount"], amount.currency),
                "allocations": _allocations(part.get("allocations"), amount.currency),
            }
            for part in data.pop("parts")
        ]
        group = services.record_split_payment(amount=amount, parts=parts, user=request.user, **data)
        group = PaymentGroup.objects.prefetch_related(
            "payments__allocations", "payments__refunds", "payments__client"
        ).get(pk=group.pk)
        return Response(s.PaymentGroupSerializer(group).data, status=status.HTTP_201_CREATED)


class BankImportViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Bank statement imports (FR-11-5): ``POST`` a CSV, OFX or CAMT.053 file; new lines
    join the reconciliation queue with suggested matches."""

    model = BankStatementImport
    serializer_class = s.BankImportSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = perms({"GET": "payments.reconcile", "POST": "payments.reconcile"})

    def get_tenant_queryset(self) -> QuerySet[BankStatementImport]:
        return BankStatementImport.objects.all()

    @extend_schema(
        request={"multipart/form-data": s.BankUploadSerializer},
        responses={201: s.BankImportSerializer},
    )
    def create(self, request: Request) -> Response:
        from rest_framework.exceptions import ValidationError

        from .. import bank, statements

        payload = s.BankUploadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        upload = payload.validated_data["file"]
        if upload.size > 10 * 1024 * 1024:
            raise ValidationError({"file": ["Statements can be at most 10 MB."]})
        content = upload.read()
        source = payload.validated_data["file_type"] or statements.detect(upload.name, content)
        try:
            parsed = statements.parse(
                source, content, month_first=payload.validated_data["month_first"]
            )
        except statements.StatementError as exc:
            raise ValidationError({"file": [str(exc)]}) from exc
        statement = bank.import_rows(
            parsed,
            source=source,
            filename=upload.name,
            currency=payload.validated_data["currency"],
            user=request.user,
        )
        return Response(self.get_serializer(statement).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=s.BankSyncResultSerializer)
    @action(detail=False, methods=["post"])
    def sync(self, request: Request) -> Response:
        """Pull new transactions from every connected Open Banking feed now."""
        from tutortrack.integrations.models import IntegrationConnection

        from .. import bank
        from ..bank_feeds import PROVIDER

        out = []
        for connection in IntegrationConnection.objects.filter(
            provider=PROVIDER, user__isnull=True
        ).exclude(status="disconnected"):
            statement = bank.sync_feed(connection.pk, user=request.user)
            if statement is not None:
                out.append(statement)
        return Response({"imports": s.BankImportSerializer(out, many=True).data})


class BankTransactionFilter(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=BankTransaction.Status.choices)
    statement = filters.UUIDFilter()

    class Meta:
        model = BankTransaction
        fields: list[str] = []


class BankTransactionViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """The reconciliation queue: bank lines with suggested matches to confirm or ignore."""

    model = BankTransaction
    serializer_class = s.BankTransactionSerializer
    filterset_class = BankTransactionFilter
    permission_classes = perms({"GET": "payments.reconcile", "POST": "payments.reconcile"})

    def get_tenant_queryset(self) -> QuerySet[BankTransaction]:
        return BankTransaction.objects.prefetch_related("matches__invoice", "matches__client")

    def _out(self, txn: BankTransaction) -> Response:
        return Response(self.get_serializer(self.get_tenant_queryset().get(pk=txn.pk)).data)

    @extend_schema(request=s.ConfirmMatchSerializer, responses=s.BankTransactionSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request: Request, pk: Any = None) -> Response:
        """Confirm a suggested ``match``, or name the ``client`` (and ``invoice``)."""
        from .. import bank

        txn = self.get_object()
        payload = s.ConfirmMatchSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        match = None
        if data.get("match"):
            match = get_object_or_404(ReconciliationMatch.objects.all(), pk=data["match"])
        txn = bank.confirm(
            txn, match, client=data.get("client"), invoice=data.get("invoice"), user=request.user
        )
        return self._out(txn)

    @extend_schema(request=s.SplitMatchSerializer, responses=s.BankTransactionSerializer)
    @action(detail=True, methods=["post"])
    def split(self, request: Request, pk: Any = None) -> Response:
        """One bank receipt for several clients (a split payment)."""
        from .. import bank

        txn = self.get_object()
        payload = s.SplitMatchSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        parts = [
            {
                "client": part["client"],
                "amount": Money(part["amount"], txn.currency),
                "allocations": _allocations(part.get("allocations"), txn.currency),
            }
            for part in payload.validated_data["parts"]
        ]
        txn = bank.confirm_split(
            txn, parts, payer_name=payload.validated_data["payer_name"], user=request.user
        )
        return self._out(txn)

    @extend_schema(request=None, responses=s.BankTransactionSerializer)
    @action(detail=True, methods=["post"])
    def ignore(self, request: Request, pk: Any = None) -> Response:
        from .. import bank

        return self._out(bank.ignore(self.get_object(), user=request.user))

    @extend_schema(request=None, responses=s.BankTransactionSerializer)
    @action(detail=True, methods=["post"])
    def reopen(self, request: Request, pk: Any = None) -> Response:
        from .. import bank

        return self._out(bank.reopen(self.get_object(), user=request.user))


class ClientMigrationView(APIView):
    """Move a client to another provider (FR-11-2): they get a setup link; the new method
    becomes the default and the old one is cancelled once nothing is being collected."""

    permission_classes = perms({"POST": "payments.autopay.manage"})

    @extend_schema(
        request=s.MigrationRequestSerializer, responses={201: s.ProviderMigrationSerializer}
    )
    def post(self, request: Request, client_id: Any) -> Response:
        from .. import provider_migration

        payload = s.MigrationRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        migration = provider_migration.start_migration(
            _client(request, client_id),
            to_provider=payload.validated_data["to_provider"],
            user=request.user,
        )
        return Response(
            s.ProviderMigrationSerializer(migration).data, status=status.HTTP_201_CREATED
        )


class ProviderMigrationFilter(filters.FilterSet):
    client = filters.UUIDFilter()
    status = filters.MultipleChoiceFilter(choices=ProviderMigration.Status.choices)

    class Meta:
        model = ProviderMigration
        fields: list[str] = []


class ProviderMigrationViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Clients being moved between payment providers."""

    model = ProviderMigration
    serializer_class = s.ProviderMigrationSerializer
    filterset_class = ProviderMigrationFilter
    permission_classes = perms({"GET": "payments.payment.view", "POST": "payments.autopay.manage"})

    def get_tenant_queryset(self) -> QuerySet[ProviderMigration]:
        return ProviderMigration.objects.select_related("client")

    @extend_schema(request=None, responses=s.ProviderMigrationSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        from .. import provider_migration

        migration = provider_migration.cancel_migration(self.get_object(), user=request.user)
        return Response(self.get_serializer(migration).data)
