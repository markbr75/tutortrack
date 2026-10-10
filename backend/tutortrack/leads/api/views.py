"""Leads API (E17 §4): pipelines, enquiries (board, move, convert, lose, trials), forms,
assignment rules, waitlist and funnel; plus the public form, enquiry and offer endpoints."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.captcha import verify_turnstile
from tutortrack.core.middleware import client_ip
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, scope_queryset

from .. import services
from ..models import AssignmentRule, Enquiry, Form, Pipeline, PipelineStage, WaitlistEntry
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


# --- pipelines ------------------------------------------------------------------------------


class PipelineViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    model = Pipeline
    serializer_class = s.PipelineSerializer
    pagination_class = None
    http_method_names = ["get", "post", "put", "head", "options"]
    permission_classes = perms(
        {
            "GET": "leads.enquiry.view",
            "POST": "leads.pipeline.manage",
            "PUT": "leads.pipeline.manage",
        }
    )

    def get_tenant_queryset(self) -> Any:
        services.default_pipeline()
        return Pipeline.objects.filter(active=True).prefetch_related("stages")

    def _save(self, request: Request, pipeline: Pipeline | None) -> Response:
        payload = s.PipelineSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        saved = services.save_pipeline(
            name=data["name"],
            stages=[dict(st) for st in data["stages"]],
            pipeline=pipeline,
            is_default=data.get("is_default", False),
        )
        return Response(
            s.PipelineSerializer(saved).data,
            status=status.HTTP_201_CREATED if pipeline is None else 200,
        )

    @extend_schema(request=s.PipelineSerializer, responses={201: s.PipelineSerializer})
    def create(self, request: Request) -> Response:
        return self._save(request, None)

    @extend_schema(request=s.PipelineSerializer, responses=s.PipelineSerializer)
    def update(self, request: Request, pk: Any = None) -> Response:
        return self._save(request, self.get_object())


# --- enquiries ------------------------------------------------------------------------------


def _user(pk: Any) -> Any:
    from tutortrack.identity.models import User

    return get_object_or_404(User.objects.all(), pk=pk) if pk else None


class EnquiryViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    model = Enquiry
    serializer_class = s.EnquirySerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_classes = perms(
        {"GET": "leads.enquiry.view", "POST": "leads.enquiry.edit", "PATCH": "leads.enquiry.edit"}
    )

    def get_tenant_queryset(self) -> Any:
        qs = scope_queryset(
            self.request.user,
            Enquiry.objects.select_related("client", "contact", "stage", "owner").prefetch_related(
                "students"
            ),
            "leads.enquiry.view",
        )
        q = self.request.query_params
        for key in ("pipeline", "stage", "status", "source", "owner"):
            if q.get(key):
                qs = qs.filter(**{key: q[key]})
        if q.get("q"):
            qs = qs.filter(title__icontains=q["q"])
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter(k, str)
            for k in ("pipeline", "stage", "status", "source", "owner", "q")
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.EnquiryCreateSerializer, responses={201: s.EnquirySerializer})
    def create(self, request: Request) -> Response:
        from tutortrack.core.permissions import has_perm

        if not has_perm(request.user, "leads.enquiry.create"):
            from tutortrack.core.exceptions import PermissionDenied

            raise PermissionDenied()
        payload = s.EnquiryCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        enquiry = services.create_enquiry(
            contact={k: d.get(k, "") for k in ("first_name", "last_name", "email", "phone")},
            students=[dict(st) for st in d.get("students", [])],
            subjects=[dict(x) for x in d.get("subjects", [])] or None,
            notes=d.get("notes", ""),
            source=d["source"],
            pipeline=get_object_or_404(Pipeline.objects.all(), pk=d["pipeline"])
            if d.get("pipeline")
            else None,
            owner=_user(d.get("owner")),
            priority=d["priority"],
            value_estimate=d.get("value_estimate"),
            expected_start=d.get("expected_start"),
        )
        return Response(s.EnquirySerializer(enquiry).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.EnquiryUpdateSerializer, responses=s.EnquirySerializer)
    def partial_update(self, request: Request, pk: Any = None) -> Response:
        payload = s.EnquiryUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        changes = dict(payload.validated_data)
        if "owner" in changes:
            changes["owner"] = _user(changes["owner"])
        if "subjects" in changes:
            changes["subjects"] = [dict(x) for x in changes["subjects"]]
        return Response(
            s.EnquirySerializer(services.update_enquiry(self.get_object(), **changes)).data
        )

    @extend_schema(
        parameters=[OpenApiParameter("pipeline", str)], responses=s.BoardColumnSerializer(many=True)
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def board(self, request: Request) -> Response:
        """Open enquiries by stage for the Kanban board (FR-17-2)."""
        pid = request.query_params.get("pipeline")
        pipeline = (
            get_object_or_404(Pipeline.objects.all(), pk=pid)
            if pid
            else services.default_pipeline()
        )
        enquiries = list(
            self.get_tenant_queryset().filter(pipeline=pipeline, status=Enquiry.Status.OPEN)
        )
        columns = [
            {"stage": stage, "enquiries": [e for e in enquiries if e.stage_id == stage.pk]}
            for stage in pipeline.stages.filter(kind=PipelineStage.Kind.OPEN).order_by("order")
        ]
        return Response(s.BoardColumnSerializer(columns, many=True).data)

    @extend_schema(request=s.MoveSerializer, responses=s.EnquirySerializer)
    @action(detail=True, methods=["post"])
    def move(self, request: Request, pk: Any = None) -> Response:
        payload = s.MoveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        stage = get_object_or_404(PipelineStage.objects.all(), pk=payload.validated_data["stage"])
        return Response(
            s.EnquirySerializer(services.move(self.get_object(), stage, user=request.user)).data
        )

    @extend_schema(request=s.LoseSerializer, responses=s.EnquirySerializer)
    @action(detail=True, methods=["post"])
    def lose(self, request: Request, pk: Any = None) -> Response:
        payload = s.LoseSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        enquiry = services.lose(self.get_object(), user=request.user, **payload.validated_data)
        return Response(s.EnquirySerializer(enquiry).data)

    @extend_schema(request=s.TrialSerializer, responses=s.EnquirySerializer)
    @action(detail=True, methods=["post"])
    def trial(self, request: Request, pk: Any = None) -> Response:
        from tutortrack.catalogue.models import Service
        from tutortrack.people.models import TutorProfile

        payload = s.TrialSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        enquiry = services.book_trial(
            self.get_object(),
            start=d["start"],
            end=d["end"],
            service=get_object_or_404(Service.objects.all(), pk=d["service"]),
            tutor=get_object_or_404(TutorProfile.objects.all(), pk=d["tutor"])
            if d.get("tutor")
            else None,
            price=d.get("price"),
            user=request.user,
        )
        return Response(s.EnquirySerializer(enquiry).data)

    @extend_schema(request=s.TrialOutcomeSerializer, responses=s.EnquirySerializer)
    @action(detail=True, methods=["post"], url_path="trial-outcome")
    def trial_outcome(self, request: Request, pk: Any = None) -> Response:
        payload = s.TrialOutcomeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        enquiry = services.record_trial_outcome(
            self.get_object(),
            outcome=payload.validated_data["outcome"],
            feedback=payload.validated_data.get("feedback", ""),
            user=request.user,
        )
        return Response(s.EnquirySerializer(enquiry).data)

    @extend_schema(request=s.ConvertSerializer, responses=s.ConvertResultSerializer)
    @action(detail=True, methods=["post"])
    def convert(self, request: Request, pk: Any = None) -> Response:
        from tutortrack.catalogue.models import Service
        from tutortrack.core.exceptions import PermissionDenied
        from tutortrack.core.permissions import has_perm
        from tutortrack.people.models import Student, TutorProfile

        if not has_perm(request.user, "leads.enquiry.convert"):
            raise PermissionDenied()
        payload = s.ConvertSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        jobs = [
            {
                "service": get_object_or_404(Service.objects.all(), pk=j["service"]),
                "tutor": get_object_or_404(TutorProfile.objects.all(), pk=j["tutor"])
                if j.get("tutor")
                else None,
                "students": list(Student.objects.filter(pk__in=j.get("students") or [])),
            }
            for j in d["jobs"]
        ]
        result = services.convert(
            self.get_object(),
            jobs=jobs,
            invite_to_portal=d["invite_to_portal"],
            payment_setup_link=d["payment_setup_link"],
            user=request.user,
        )
        return Response(
            {
                "enquiry": s.EnquirySerializer(result["enquiry"]).data,
                "job_ids": [str(j.pk) for j in result["jobs"]],
                "setup_url": result["setup_url"],
                "invited": result["invited"],
            }
        )

    @extend_schema(responses=s.StageHistorySerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def history(self, request: Request, pk: Any = None) -> Response:
        enquiry = self.get_object()
        rows = enquiry.history.select_related("from_stage", "to_stage")
        return Response(s.StageHistorySerializer(rows, many=True).data)


class AssignmentRuleViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    model = AssignmentRule
    serializer_class = s.AssignmentRuleSerializer
    pagination_class = None
    permission_classes = perms(
        dict.fromkeys(("GET", "POST", "PUT", "PATCH", "DELETE"), "leads.pipeline.manage")
    )

    def get_tenant_queryset(self) -> Any:
        return AssignmentRule.objects.all()

    def perform_create(self, serializer: Any) -> None:
        serializer.save(owners=[str(o) for o in serializer.validated_data["owners"]])

    def perform_update(self, serializer: Any) -> None:
        owners = serializer.validated_data.get("owners")
        serializer.save(**({"owners": [str(o) for o in owners]} if owners is not None else {}))


# --- forms ----------------------------------------------------------------------------------


class FormViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    model = Form
    serializer_class = s.FormSerializer
    pagination_class = None
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    permission_classes = perms(dict.fromkeys(("GET", "POST", "PUT", "PATCH"), "leads.form.manage"))

    def get_tenant_queryset(self) -> Any:
        return Form.objects.all()


def _organisation(request: Request | HttpRequest) -> Any:
    org = getattr(request, "organisation", None)
    if org is None:
        raise NotFound()
    return org


class PublicFormView(APIView):
    """``/public/forms/{slug}``: the published form's schema, and submissions (FR-17-1)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_form"

    def _form(self, request: Request, slug: str) -> Form:
        _organisation(request)
        return get_object_or_404(Form.objects.filter(published=True), slug=slug)

    @extend_schema(responses=s.PublicFormSerializer)
    def get(self, request: Request, slug: str) -> Response:
        form = self._form(request, slug)
        return Response(
            {
                "name": form.name,
                "type": form.type,
                "schema": form.schema,
                "thank_you": form.settings.get("thank_you", ""),
                "redirect_url": form.settings.get("redirect_url", ""),
                "consent_text": form.settings.get("consent_text", ""),
                "turnstile_site_key": getattr(settings, "TURNSTILE_SITE_KEY", ""),
                "organisation": _organisation(request).name,
            }
        )

    @extend_schema(
        request=s.PublicSubmitSerializer, responses={201: s.PublicSubmitResultSerializer}
    )
    def post(self, request: Request, slug: str) -> Response:
        form = self._form(request, slug)
        payload = s.PublicSubmitSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        if not verify_turnstile(d["captcha_token"], client_ip(request)):
            raise ValidationError({"captcha_token": ["Please complete the check."]})
        result = services.submit_form(
            form,
            d["data"],
            ip=client_ip(request),
            user_agent=request.headers.get("User-Agent", ""),
            utm=d["utm"],
            honeypot=d["website"],
        )
        return Response({"ok": True, "pay_url": result["pay_url"]}, status=status.HTTP_201_CREATED)


class PublicEnquiryView(APIView):
    """``POST /public/enquiries``: website or partner integrations (FR-17-1)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_form"

    @extend_schema(
        request=s.PublicEnquirySerializer, responses={201: s.PublicSubmitResultSerializer}
    )
    def post(self, request: Request) -> Response:
        _organisation(request)
        payload = s.PublicEnquirySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        if d["website"]:
            return Response({"ok": True, "pay_url": ""}, status=status.HTTP_201_CREATED)
        if not verify_turnstile(d["captcha_token"], client_ip(request)):
            raise ValidationError({"captcha_token": ["Please complete the check."]})
        services.create_enquiry(
            contact={k: d.get(k, "") for k in ("first_name", "last_name", "email", "phone")},
            students=[dict(st) for st in d.get("students", [])],
            subjects=[dict(x) for x in d.get("subjects", [])] or None,
            notes=d.get("notes", ""),
            source=Enquiry.Source.API,
            utm={k: str(v)[:300] for k, v in d["utm"].items()},
            client={"postcode": d["postcode"]} if d.get("postcode") else None,
        )
        return Response({"ok": True, "pay_url": ""}, status=status.HTTP_201_CREATED)


# --- waitlist -------------------------------------------------------------------------------


class WaitlistViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    model = WaitlistEntry
    serializer_class = s.WaitlistEntrySerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_classes = perms(dict.fromkeys(("GET", "POST", "PATCH"), "leads.waitlist.manage"))

    def get_tenant_queryset(self) -> Any:
        qs = WaitlistEntry.objects.select_related("student")
        state = self.request.query_params.get("status", "waiting")
        return qs.filter(status=state) if state != "all" else qs

    @extend_schema(parameters=[OpenApiParameter("status", str)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        d = serializer.validated_data
        serializer.instance = services.add_to_waitlist(
            student=d["student"],
            subject=d.get("subject", ""),
            level=d.get("level", ""),
            tutor=d.get("tutor"),
            service=d.get("service"),
            notes=d.get("notes", ""),
        )

    @extend_schema(request=s.OfferSerializer, responses=s.WaitlistEntrySerializer)
    @action(detail=True, methods=["post"])
    def offer(self, request: Request, pk: Any = None) -> Response:
        payload = s.OfferSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        entry = self.get_object()
        services.offer_place(
            entry,
            details=payload.validated_data["details"],
            hours=payload.validated_data.get("hours"),
        )
        entry.refresh_from_db()
        return Response(s.WaitlistEntrySerializer(entry).data)

    @extend_schema(request=None, responses=s.WaitlistEntrySerializer)
    @action(detail=True, methods=["post"])
    def remove(self, request: Request, pk: Any = None) -> Response:
        entry = services.remove_from_waitlist(self.get_object())
        return Response(s.WaitlistEntrySerializer(entry).data)


class PublicOfferView(APIView):
    """``/public/offers/{token}``: the family sees and answers a waitlist offer."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(responses=s.PublicOfferSerializer)
    def get(self, request: Request, token: str) -> Response:
        entry = services.offer_for_token(token)
        return Response(
            {
                "student": entry.student.first_name,
                "subject": entry.subject,
                "details": entry.offer_details,
                "status": entry.status,
                "expires_at": entry.offer_expires_at,
                "organisation": _organisation(request).name,
            }
        )

    @extend_schema(request=s.OfferResponseSerializer, responses=s.PublicOfferSerializer)
    def post(self, request: Request, token: str) -> Response:
        payload = s.OfferResponseSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.respond(token, accept=payload.validated_data["accept"])
        return self.get(request, token)


# --- reports (T10) --------------------------------------------------------------------------


class FunnelView(APIView):
    permission_classes = perms({"GET": "leads.enquiry.view"})

    @extend_schema(
        parameters=[
            OpenApiParameter("pipeline", str),
            OpenApiParameter("from", OpenApiTypes.DATE),
            OpenApiParameter("to", OpenApiTypes.DATE),
        ],
        responses=s.FunnelSerializer,
    )
    def get(self, request: Request) -> Response:
        q = request.query_params
        pipeline = (
            get_object_or_404(Pipeline.objects.all(), pk=q["pipeline"])
            if q.get("pipeline")
            else services.default_pipeline()
        )
        zone = ZoneInfo(_organisation(request).timezone)
        try:
            end = date.fromisoformat(q["to"]) if q.get("to") else datetime.now(zone).date()
            start = date.fromisoformat(q["from"]) if q.get("from") else end - timedelta(days=90)
        except ValueError:
            raise ValidationError({"from": ["Use YYYY-MM-DD."]}) from None
        report = services.funnel(
            pipeline,
            datetime.combine(start, time.min, tzinfo=zone),
            datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone),
        )
        return Response(s.FunnelSerializer(report).data)


# --- inbound email --------------------------------------------------------------------------


@csrf_exempt
def inbound_email(request: HttpRequest) -> HttpResponse:
    """``POST /webhooks/inbound-email?token=``: Postmark inbound JSON for
    ``enquiries+<subdomain>@<inbound domain>`` becomes an enquiry (FR-17-1)."""
    import hmac
    import json

    from tutortrack.core.context import tenant_context
    from tutortrack.tenancy.models import Organisation

    expected = getattr(settings, "INBOUND_EMAIL_TOKEN", "")
    if (
        request.method != "POST"
        or not expected
        or not hmac.compare_digest(request.GET.get("token", ""), expected)
    ):
        return HttpResponse(status=403 if request.method == "POST" else 405)
    try:
        body = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    slug = str(body.get("MailboxHash", "")).lower()
    org = Organisation.objects.filter(slug=slug).first()
    sender = body.get("FromFull") or {}
    email = str(sender.get("Email") or body.get("From", "")).strip()
    if org is None or not org.is_operational or not email:
        return HttpResponse(status=200)  # nothing we can route: accept and drop
    with tenant_context(org):
        services.enquiry_from_email(
            from_email=email,
            from_name=str(sender.get("Name", "")),
            subject=str(body.get("Subject", "")),
            body=str(body.get("TextBody", "")),
        )
    return HttpResponse(status=200)
