"""Payroll API (E12 §4)."""

from __future__ import annotations

from typing import Any

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, has_perm
from tutortrack.people.models import TutorProfile

from .. import selectors, services, travel
from ..models import Expense, ExpenseCategory, PayItem, PayrollOriginator, PayRun, PayStatement
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def _tutor(pk: Any) -> TutorProfile:
    return get_object_or_404(TutorProfile.objects.all(), pk=pk)


def _my_tutor(request: Request) -> TutorProfile:
    tutor = selectors.tutor_for_user(request.user)
    if tutor is None:
        raise NotFound("You're not a tutor here.")
    return tutor


# --- pay profiles (T01) ---------------------------------------------------------------------


class PayProfileView(APIView):
    """``/tutors/{id}/pay-profile``: method, payout details and VAT (FR-12-2). Bank details
    are masked unless ``?full=true`` and the user may see them (audited)."""

    permission_classes = perms({"GET": "payroll.view", "PATCH": "payroll.profile.manage",
                                "PUT": "payroll.profile.manage"})  # fmt: skip

    def _out(self, request: Request, tutor: TutorProfile) -> Response:
        full = request.query_params.get("full") == "true"
        if full and not has_perm(request.user, "payroll.bank_details.view"):
            raise PermissionDenied()
        profile = services.profile_for(tutor)
        return Response(s.PayProfileSerializer(profile, context={"full_bank": full}).data)

    @extend_schema(parameters=[OpenApiParameter("full", bool)], responses=s.PayProfileSerializer)
    def get(self, request: Request, pk: str) -> Response:
        return self._out(request, _tutor(pk))

    @extend_schema(request=s.PayProfileUpdateSerializer, responses=s.PayProfileSerializer)
    def patch(self, request: Request, pk: str) -> Response:
        tutor = _tutor(pk)
        payload = s.PayProfileUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        services.update_profile(tutor, **payload.validated_data)
        return self._out(request, tutor)

    @extend_schema(request=s.BankDetailsSerializer, responses=s.PayProfileSerializer)
    def put(self, request: Request, pk: str) -> Response:
        """Replace the bank details."""
        tutor = _tutor(pk)
        payload = s.BankDetailsSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.update_profile(tutor, bank=payload.validated_data)
        return self._out(request, tutor)


class MyPayProfileView(APIView):
    """The tutor's own pay details (tutor portal)."""

    permission_classes = AUTH

    @extend_schema(responses=s.PayProfileSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.PayProfileSerializer(services.profile_for(_my_tutor(request))).data)

    @extend_schema(request=s.BankDetailsSerializer, responses=s.PayProfileSerializer)
    def put(self, request: Request) -> Response:
        payload = s.BankDetailsSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        profile = services.update_profile(_my_tutor(request), bank=payload.validated_data)
        return Response(s.PayProfileSerializer(profile).data)


class AgreeSelfBillingView(APIView):
    permission_classes = AUTH

    @extend_schema(request=None, responses=s.PayProfileSerializer)
    def post(self, request: Request) -> Response:
        profile = services.agree_self_billing(_my_tutor(request))
        return Response(s.PayProfileSerializer(profile).data)


class StripeOnboardingView(APIView):
    """Start (or resume) Stripe Express onboarding for payouts (FR-12-7)."""

    permission_classes = AUTH

    @extend_schema(request=None, responses=s.OnboardingLinkSerializer)
    def post(self, request: Request) -> Response:
        tutor = _my_tutor(request)
        base = request.organisation.base_url  # type: ignore[attr-defined]
        url = services.stripe_onboarding_link(tutor, return_url=f"{base}/portal/tutor/earnings")
        return Response({"url": url})


class OriginatorView(APIView):
    """The account the organisation pays tutors from (bank files)."""

    permission_classes = perms({"GET": "payroll.view", "PUT": "payroll.payrun.pay"})

    @extend_schema(responses=s.OriginatorOutSerializer)
    def get(self, request: Request) -> Response:
        originator = PayrollOriginator.objects.first()
        return Response({"name": originator.name if originator else "",
                         "bank_hint": originator.bank_hint if originator else "",
                         "configured": originator is not None})  # fmt: skip

    @extend_schema(request=s.OriginatorSerializer, responses=s.OriginatorOutSerializer)
    def put(self, request: Request) -> Response:
        payload = s.OriginatorSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        keys = ("company_id", "immediate_destination", "destination_name", "apca_id")
        extra = {k: data.pop(k) for k in keys if data.get(k)}
        if data.get("bank_short_name"):
            extra["bank"] = data.pop("bank_short_name")
        originator = services.save_originator(name=data["name"], bank=data["bank"], extra=extra)
        return Response({"name": originator.name, "bank_hint": originator.bank_hint,
                         "configured": True})  # fmt: skip


# --- pay items (T02, T03) -------------------------------------------------------------------


class PayItemViewSet(TenantScopedViewMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    model = PayItem
    serializer_class = s.PayItemSerializer
    permission_classes = perms({"GET": "payroll.view", "POST": "payroll.item.manage"})

    def get_tenant_queryset(self) -> Any:
        qs = selectors.pay_items(self.request.user)
        q = self.request.query_params
        for field in ("tutor", "status", "kind", "pay_run"):
            if q.get(field):
                qs = qs.filter(**{field: q[field]})
        return qs.order_by("-date", "-id")

    @extend_schema(parameters=[OpenApiParameter(f, str) for f in ("tutor", "status", "kind",
                                                                  "pay_run")])  # fmt: skip
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.ManualItemSerializer, responses={201: s.PayItemSerializer})
    def create(self, request: Request) -> Response:
        payload = s.ManualItemSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        item = services.create_manual_item(
            tutor=_tutor(data["tutor"]), kind=data["kind"], description=data["description"],
            amount=data["amount"], day=data["date"],
        )  # fmt: skip
        return Response(s.PayItemSerializer(item).data, status=status.HTTP_201_CREATED)

    def _item(self, pk: Any) -> PayItem:
        return get_object_or_404(self.get_queryset(), pk=pk)

    @extend_schema(request=s.HoldNoteSerializer, responses=s.PayItemSerializer)
    @action(detail=True, methods=["post"])
    def hold(self, request: Request, pk: Any = None) -> Response:
        payload = s.HoldNoteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        item = services.hold(self._item(pk), note=payload.validated_data["note"])
        return Response(s.PayItemSerializer(item).data)

    @extend_schema(request=None, responses=s.PayItemSerializer)
    @action(detail=True, methods=["post"])
    def release(self, request: Request, pk: Any = None) -> Response:
        return Response(s.PayItemSerializer(services.release(self._item(pk))).data)

    @extend_schema(request=None, responses=s.PayItemSerializer)
    @action(detail=True, methods=["post"])
    def void(self, request: Request, pk: Any = None) -> Response:
        return Response(s.PayItemSerializer(services.void_item(self._item(pk))).data)


# --- expenses (T04, T05) --------------------------------------------------------------------


class ExpenseCategoryViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin,
    mixins.UpdateModelMixin, viewsets.GenericViewSet,
):  # fmt: skip
    model = ExpenseCategory
    serializer_class = s.ExpenseCategorySerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_classes = perms({"GET": "payroll.expense.submit",
                                "POST": "payroll.expense.approve",
                                "PATCH": "payroll.expense.approve"})  # fmt: skip

    def get_tenant_queryset(self) -> Any:
        qs = ExpenseCategory.objects.all()
        if not has_perm(self.request.user, "payroll.expense.approve"):
            qs = qs.filter(active=True)
        return qs


class ExpenseViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):  # fmt: skip
    model = Expense
    serializer_class = s.ExpenseSerializer
    permission_classes = perms({"GET": "payroll.expense.submit",
                                "POST": "payroll.expense.submit"})  # fmt: skip

    def get_tenant_queryset(self) -> Any:
        qs = selectors.expenses(self.request.user)
        state = self.request.query_params.get("status")
        return (qs.filter(status=state) if state else qs).order_by("-date", "-id")

    @extend_schema(parameters=[OpenApiParameter("status", str)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.ExpenseSubmitSerializer, responses={201: s.ExpenseSerializer})
    def create(self, request: Request) -> Response:
        from tutortrack.core.models import StoredFile
        from tutortrack.jobs.models import Job
        from tutortrack.people.models import Client
        from tutortrack.scheduling.models import Lesson

        payload = s.ExpenseSubmitSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        if data.get("tutor") and has_perm(request.user, "payroll.expense.approve"):
            tutor = _tutor(data["tutor"])
        else:
            tutor = _my_tutor(request)

        def find(model: Any, key: str) -> Any:
            return get_object_or_404(model.objects.all(), pk=data[key]) if data.get(key) else None

        expense = services.submit_expense(
            tutor=tutor, category=get_object_or_404(ExpenseCategory.objects.all(),
                                                    pk=data["category"]),
            day=data["date"], description=data["description"], amount=data.get("amount"),
            tax=data.get("tax"), distance=data.get("distance"),
            receipt=find(StoredFile, "receipt"), lesson=find(Lesson, "lesson"),
            job=find(Job, "job"), client=find(Client, "client"), rebillable=data.get("rebillable"),
        )  # fmt: skip
        return Response(s.ExpenseSerializer(expense).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.DecisionSerializer, responses=s.ExpenseSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: Any = None) -> Response:
        payload = s.DecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        expense = services.approve_expense(
            self.get_object(), user=request.user, comment=payload.validated_data.get("comment", "")
        )
        return Response(s.ExpenseSerializer(expense).data)

    @extend_schema(request=s.DecisionSerializer, responses=s.ExpenseSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: Any = None) -> Response:
        payload = s.DecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        expense = services.reject_expense(
            self.get_object(), user=request.user, comment=payload.validated_data.get("comment", "")
        )
        return Response(s.ExpenseSerializer(expense).data)

    @extend_schema(
        parameters=[OpenApiParameter("date", OpenApiTypes.DATE, required=True),
                    OpenApiParameter("unit", str)],
        responses=s.MileageLegSerializer(many=True),
    )  # fmt: skip
    @action(detail=False, methods=["get"], url_path="mileage-suggestions", pagination_class=None)
    def mileage_suggestions(self, request: Request) -> Response:
        """Suggested legs between the tutor's in-person lessons that day (FR-12-3)."""
        from datetime import date

        from tutortrack.tenancy.settings_service import get_setting

        try:
            day = date.fromisoformat(str(request.query_params.get("date")))
        except ValueError:
            raise BusinessRuleViolation("Give a date (YYYY-MM-DD).") from None
        unit = request.query_params.get("unit", "mi")
        from_home = bool(get_setting("payroll.mileage_from_home"))
        legs = travel.suggest_legs(_my_tutor(request), day, from_home=from_home)
        return Response(
            s.MileageLegSerializer(
                [{"origin": leg["from"], "destination": leg["to"], "lesson": leg["lesson"],
                  "distance": travel.in_unit(leg["km"], unit), "unit": unit} for leg in legs],
                many=True,
            ).data
        )  # fmt: skip


# --- pay runs (T06-T10) ---------------------------------------------------------------------


class PayRunViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):  # fmt: skip
    model = PayRun
    serializer_class = s.PayRunSerializer
    permission_classes = perms({"GET": "payroll.view", "POST": "payroll.payrun.create"})

    def get_tenant_queryset(self) -> Any:
        return selectors.pay_runs(self.request.user).order_by("-period_end", "-id")

    def get_serializer_class(self) -> Any:
        return s.PayRunDetailSerializer if self.action != "list" else s.PayRunSerializer

    def _run(self, pk: Any) -> PayRun:
        return get_object_or_404(self.get_queryset(), pk=pk)

    def _out(self, pay_run: PayRun) -> Response:
        pay_run.refresh_from_db()
        return Response(s.PayRunDetailSerializer(pay_run).data)

    def _need(self, codename: str) -> None:
        if not has_perm(self.request.user, codename):
            raise PermissionDenied()

    @extend_schema(request=s.PayRunCreateSerializer, responses={201: s.PayRunDetailSerializer})
    def create(self, request: Request) -> Response:
        from tutortrack.tenancy.models import Branch

        payload = s.PayRunCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        branch = (
            get_object_or_404(Branch.objects.all(), pk=data["branch"])
            if data.get("branch")
            else None
        )
        pay_run, _created = services.create_pay_run(
            period_start=data["period_start"], period_end=data["period_end"], branch=branch
        )
        return Response(s.PayRunDetailSerializer(pay_run).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=s.PayRunDetailSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: Any = None) -> Response:
        return self._out(services.approve(self._run(pk), user=request.user))

    @extend_schema(request=None, responses=s.PayRunDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        return self._out(services.cancel_pay_run(self._run(pk)))

    @extend_schema(request=s.RemoveItemSerializer, responses=s.PayRunDetailSerializer)
    @action(detail=True, methods=["post"], url_path="remove-item")
    def remove_item(self, request: Request, pk: Any = None) -> Response:
        payload = s.RemoveItemSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        pay_run = self._run(pk)
        item = get_object_or_404(PayItem.objects.all(), pk=payload.validated_data["item"])
        return self._out(services.remove_item(pay_run, item))

    @extend_schema(request=s.AdjustmentSerializer, responses=s.PayRunDetailSerializer)
    @action(detail=True, methods=["post"])
    def adjustments(self, request: Request, pk: Any = None) -> Response:
        payload = s.AdjustmentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        return self._out(services.add_adjustment(
            self._run(pk), tutor=_tutor(data["tutor"]), description=data["description"],
            amount=data["amount"],
        ))  # fmt: skip

    @extend_schema(request=s.MarkPaidSerializer, responses=s.PayRunDetailSerializer)
    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request: Request, pk: Any = None) -> Response:
        self._need("payroll.payrun.pay")
        payload = s.MarkPaidSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._out(services.mark_paid(
            self._run(pk), payout_ids=payload.validated_data.get("payouts"),
            reference=payload.validated_data.get("reference", ""),
        ))  # fmt: skip

    @extend_schema(request=s.BankFileRequestSerializer, responses={201: s.BankFileSerializer})
    @action(detail=True, methods=["post"], url_path="bank-files")
    def bank_files(self, request: Request, pk: Any = None) -> Response:
        self._need("payroll.payrun.pay")
        payload = s.BankFileRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        export = services.generate_bank_file(
            self._run(pk), fmt=payload.validated_data.get("format"), user=request.user
        )
        return Response(s.BankFileSerializer(export).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[OpenApiParameter("file_id", OpenApiTypes.UUID, OpenApiParameter.PATH)],
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"], url_path=r"bank-files/(?P<file_id>[^/.]+)")
    def bank_file(self, request: Request, pk: Any = None, file_id: str = "") -> HttpResponse:
        from tutortrack.core import audit

        self._need("payroll.payrun.pay")
        export = get_object_or_404(self._run(pk).bank_files.all(), pk=file_id)
        audit.record_read(export, reason="bank_file_download")
        response = HttpResponse(export.content, content_type="application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{export.filename}"'
        return response

    @extend_schema(
        parameters=[OpenApiParameter("format", str, required=True)],
        responses={(200, "text/csv"): OpenApiTypes.STR},
    )
    @action(detail=True, methods=["get"], url_path="payroll-export")
    def payroll_export(self, request: Request, pk: Any = None) -> HttpResponse:
        """Hours and amounts for the payroll provider (employed tutors, FR-12-8)."""
        filename, content = services.payroll_export(
            self._run(pk), str(request.query_params.get("format", "generic"))
        )
        response = HttpResponse(content, content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class FailPayoutView(APIView):
    """Record a bounced or rejected payout: its items go back for the next run."""

    permission_classes = perms({"POST": "payroll.payrun.pay"})

    @extend_schema(request=s.FailPayoutSerializer, responses=s.TutorPayoutSerializer)
    def post(self, request: Request, pk: str) -> Response:
        from ..models import Payout

        payload = s.FailPayoutSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        payout = get_object_or_404(Payout.objects.all(), pk=pk)
        if payout.status not in (Payout.Status.PENDING, Payout.Status.PROCESSING,
                                 Payout.Status.PAID):  # fmt: skip
            raise BusinessRuleViolation("This payout can't fail now.")
        payout = services.fail_payout(payout, reason=payload.validated_data["reason"])
        return Response(s.TutorPayoutSerializer(payout).data)


class StatementViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):  # fmt: skip
    model = PayStatement
    serializer_class = s.PayStatementSerializer
    permission_classes = perms({"GET": "payroll.view"})

    def get_tenant_queryset(self) -> Any:
        return selectors.statements(self.request.user)

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def pdf(self, request: Request, pk: Any = None) -> HttpResponse:
        statement = self.get_object()
        response = HttpResponse(services.statement_pdf(statement), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{statement.number}.pdf"'
        return response


class MyEarningsView(APIView):
    """``/me/earnings`` (FR-12-9): upcoming and held pay, payouts, statements, YTD."""

    permission_classes = AUTH

    @extend_schema(responses=s.EarningsSerializer)
    def get(self, request: Request) -> Response:
        tutor = _my_tutor(request)
        data = selectors.earnings(tutor, services.org_today())
        return Response(s.EarningsSerializer(data).data)
