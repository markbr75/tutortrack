"""Processes API (E32 §6) and the Temporal codec server (FR-32-9)."""

from __future__ import annotations

import dataclasses
import typing
from typing import Any

import structlog
from django.conf import settings
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from tutortrack.core import audit
from tutortrack.core.api.serializers import BaseModelSerializer
from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.models import WorkflowLink
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, has_perm
from tutortrack.core.workflows import ops
from tutortrack.core.workflows.registry import discover

logger = structlog.get_logger(__name__)


class ProcessSerializer(BaseModelSerializer):
    class Meta:
        model = WorkflowLink
        fields = [
            "id", "workflow_id", "process", "workflow_type", "subject_type", "subject_id",
            "status", "current_step", "started_at", "closed_at", "last_error",
        ]  # fmt: skip
        read_only_fields = fields


class ProcessDetailSerializer(ProcessSerializer):
    live = serializers.DictField(
        child=serializers.JSONField(),
        help_text="The workflow's own `state` query (current step, next deadline...), if any.",
    )

    class Meta(ProcessSerializer.Meta):
        fields = [*ProcessSerializer.Meta.fields, "live"]
        read_only_fields = fields


class ProcessFilter(filters.FilterSet):
    subject_type = filters.CharFilter()
    subject_id = filters.CharFilter()
    process = filters.CharFilter()
    status = filters.ChoiceFilter(choices=WorkflowLink.Status.choices)

    class Meta:
        model = WorkflowLink
        fields: list[str] = []


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


def _input_class(workflow: type) -> Any:
    hints = typing.get_type_hints(workflow.run)  # type: ignore[attr-defined]
    return next(v for k, v in hints.items() if k != "return")


class ProcessViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Durable processes linked to records, e.g. ``?subject_type=invoice&subject_id=…``."""

    model = WorkflowLink
    serializer_class = ProcessSerializer
    lookup_field = "workflow_id"
    lookup_value_regex = "[^/]+"
    filterset_class = ProcessFilter
    permission_classes = [
        IsAuthenticated,
        HasOrganisation,
        HasMethodPermission.for_({"GET": "processes.view", "POST": "processes.view"}),
    ]

    def get_tenant_queryset(self) -> QuerySet[WorkflowLink]:
        return WorkflowLink.objects.all()

    @extend_schema(responses=ProcessDetailSerializer)
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        link = self.get_object()
        live: dict[str, Any] = {}
        try:  # keep the stored status fresh; Temporal being down must not break the page
            status, _ = ops.describe_now(link.workflow_id)
            if status != link.status:
                link.status = status
                link.save(update_fields=["status", "updated_at"])
            if status == "running":
                live = dict(ops.query_now(link.workflow_id, "state") or {})
        except Exception:
            logger.info("process.live_unavailable", workflow_id=link.workflow_id)
        data = ProcessSerializer(link, context={"request": request}).data
        return Response({**data, "live": live})

    def _info(self, link: WorkflowLink) -> Any:
        info = discover().processes.get(link.process)
        if info is None:
            raise BusinessRuleViolation(f"Unknown process {link.process!r}.")
        return info

    @extend_schema(request=None, responses=ProcessSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, workflow_id: str | None = None) -> Response:
        link = self.get_object()
        info = self._info(link)
        if info.cancel_permission is None:
            raise BusinessRuleViolation("This process cannot be cancelled.")
        if not has_perm(request.user, info.cancel_permission):
            raise PermissionDenied()
        if link.status != WorkflowLink.Status.RUNNING:
            raise BusinessRuleViolation("The process is not running.")
        ops.cancel_now(link.workflow_id)
        audit.record(link, "cancel")
        link.current_step = "cancel_requested"
        link.save(update_fields=["current_step", "updated_at"])
        return Response(ProcessSerializer(link, context={"request": request}).data)

    @extend_schema(request=ReasonSerializer, responses=ProcessSerializer)
    @action(detail=True, methods=["post"])
    def terminate(self, request: Request, workflow_id: str | None = None) -> Response:
        """Platform operations: stop a stuck process immediately (audited with a reason)."""
        if not has_perm(request.user, "processes.manage") or not request.user.is_superuser:
            raise PermissionDenied()
        reason = _validated_reason(request)
        link = self.get_object()
        ops.terminate_now(link.workflow_id, reason)
        audit.record(link, "terminate", {"reason": [None, reason]})
        link.status = WorkflowLink.Status.TERMINATED
        link.last_error = reason
        link.save(update_fields=["status", "last_error", "updated_at"])
        return Response(ProcessSerializer(link, context={"request": request}).data)

    @extend_schema(request=ReasonSerializer, responses=ProcessSerializer)
    @action(detail=True, methods=["post"])
    def restart(self, request: Request, workflow_id: str | None = None) -> Response:
        """Platform operations: start a failed/terminated process again with its input."""
        if not has_perm(request.user, "processes.manage") or not request.user.is_superuser:
            raise PermissionDenied()
        reason = _validated_reason(request)
        link = self.get_object()
        if link.status == WorkflowLink.Status.RUNNING:
            raise BusinessRuleViolation("The process is still running.")
        info = self._info(link)
        input_cls = _input_class(info.workflow)
        fields = {f.name for f in dataclasses.fields(input_cls)}
        workflow_input = input_cls(**{k: v for k, v in link.input.items() if k in fields})
        subject = (link.subject_type, link.subject_id) if link.subject_type else None
        if ops.start_now(info.workflow, workflow_input, id=link.workflow_id, subject=subject,
                         branch_id=link.branch_id) is None:  # fmt: skip
            raise BusinessRuleViolation("The process could not be restarted (already running).")
        audit.record(link, "restart", {"reason": [None, reason]})
        link.refresh_from_db()
        return Response(ProcessSerializer(link, context={"request": request}).data)


def _validated_reason(request: Request) -> str:
    payload = ReasonSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    return str(payload.validated_data["reason"])


# --- codec server (staff-only) --------------------------------------------------------------------


def _cors(request: HttpRequest, response: HttpResponse) -> HttpResponse:
    origin = request.headers.get("Origin", "")
    if origin and origin in settings.TEMPORAL_CODEC_CORS_ORIGINS:
        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Credentials"] = "true"
        response["Access-Control-Allow-Headers"] = "content-type,x-namespace"
        response["Access-Control-Allow-Methods"] = "POST,OPTIONS"
        response["Vary"] = "Origin"
    return response


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def codec(request: HttpRequest, operation: str) -> HttpResponse:
    """Temporal Web UI codec endpoint: ``POST /temporal-codec/{encode,decode}``.

    Lets authorised operators read encrypted payloads in the Temporal UI. Platform staff
    only (session cookie; the UI sends credentials); every decode is logged.
    """
    if request.method == "OPTIONS":
        return _cors(request, HttpResponse(status=204))
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not getattr(user, "is_platform_staff", False):
        return _cors(request, JsonResponse({"detail": "Forbidden"}, status=403))
    if operation not in {"encode", "decode"}:
        return _cors(request, JsonResponse({"detail": "Not found"}, status=404))
    from google.protobuf import json_format
    from temporalio.api.common.v1 import Payloads

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.codec import EncryptionCodec

    try:
        payloads = json_format.Parse(request.body or b"{}", Payloads())
    except json_format.ParseError:
        return _cors(request, JsonResponse({"detail": "Invalid payloads"}, status=400))
    codec_impl = EncryptionCodec()
    method = codec_impl.encode if operation == "encode" else codec_impl.decode
    result = runtime.run(method(list(payloads.payloads)))
    if operation == "decode":
        logger.info("temporal.codec_decode", user_id=str(user.pk), count=len(result))
    body = json_format.MessageToJson(Payloads(payloads=result))
    return _cors(request, HttpResponse(body, content_type="application/json"))
