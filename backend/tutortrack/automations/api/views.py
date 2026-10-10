"""Automation API (E14 §4)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, has_perm

from .. import conditions, recipes, registry, services
from ..models import Automation, AutomationRun
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]
PERMS: list[Any] = [
    *AUTH,
    HasMethodPermission.for_({"GET": "automation.view", "*": "automation.manage"}),
]


class AutomationViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """Automations: When → If → Then."""

    model = Automation
    serializer_class = s.AutomationSerializer
    permission_classes = PERMS
    pagination_class = None

    def get_tenant_queryset(self) -> Any:
        return Automation.objects.all()

    @extend_schema(request=s.AutomationWriteSerializer, responses={201: s.AutomationSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.AutomationWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        automation = services.create_automation(
            conditions_=data.pop("conditions"), user=request.user, **data
        )
        return Response(s.AutomationSerializer(automation).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.AutomationPatchSerializer, responses=s.AutomationSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.AutomationPatchSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        automation = services.update_automation(
            self.get_object(), user=request.user, **payload.validated_data
        )
        return Response(s.AutomationSerializer(automation).data)

    @extend_schema(request=s.AutomationWriteSerializer, responses=s.AutomationSerializer)
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.AutomationWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        automation = services.update_automation(
            self.get_object(), user=request.user, **payload.validated_data
        )
        return Response(s.AutomationSerializer(automation).data)

    def perform_destroy(self, instance: Automation) -> None:
        services.delete_automation(instance)

    @extend_schema(request=None, responses=s.AutomationSerializer)
    @action(detail=True, methods=["post"])
    def enable(self, request: Request, pk: Any = None) -> Response:
        automation = services.set_enabled(self.get_object(), True, user=request.user)
        return Response(s.AutomationSerializer(automation).data)

    @extend_schema(request=None, responses=s.AutomationSerializer)
    @action(detail=True, methods=["post"])
    def disable(self, request: Request, pk: Any = None) -> Response:
        automation = services.set_enabled(self.get_object(), False, user=request.user)
        return Response(s.AutomationSerializer(automation).data)

    @extend_schema(request=s.DryRunRequestSerializer, responses=s.DryRunSerializer)
    @action(detail=True, methods=["post"])
    def test(self, request: Request, pk: Any = None) -> Response:
        """Dry run against a record: whether it matches and what each step would do."""
        payload = s.DryRunRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = services.dry_run(self.get_object(), payload.validated_data["subject_id"])
        return Response(s.DryRunSerializer(result).data)

    @extend_schema(request=s.ManualRunSerializer, responses=s.StartedSerializer)
    @action(detail=True, methods=["post"])
    def run(self, request: Request, pk: Any = None) -> Response:
        """Run now for the chosen records (manual trigger or bulk action)."""
        payload = s.ManualRunSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        runs = services.run_manually(self.get_object(), payload.validated_data["subject_ids"])
        return Response({"started": len(runs)})

    @extend_schema(responses=s.AutomationRunSerializer(many=True))
    @action(detail=True, methods=["get"])
    def runs(self, request: Request, pk: Any = None) -> Response:
        rows = AutomationRun.objects.filter(automation=self.get_object()).select_related(
            "automation", "version"
        )[:100]  # fmt: skip
        return Response(s.AutomationRunSerializer(rows, many=True).data)


class AutomationRunViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):  # fmt: skip
    """Automation runs and their step log (``?status=``)."""

    model = AutomationRun
    permission_classes = PERMS

    def get_tenant_queryset(self) -> Any:
        qs = AutomationRun.objects.select_related("automation", "version")
        state = self.request.query_params.get("status")
        return qs.filter(status=state) if state else qs

    def get_serializer_class(self) -> Any:
        return (
            s.AutomationRunDetailSerializer if self.action != "list" else s.AutomationRunSerializer
        )

    @extend_schema(parameters=[OpenApiParameter("status", str, required=False)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses=s.AutomationRunDetailSerializer)
    @action(detail=True, methods=["post"])
    def retry(self, request: Request, pk: Any = None) -> Response:
        """Re-run a failed run from its failed step."""
        run = services.retry(self.get_object())
        return Response(s.AutomationRunDetailSerializer(run).data)


class RecipesView(APIView):
    permission_classes = [*AUTH, HasMethodPermission.for_({"GET": "automation.view"})]

    @extend_schema(responses=s.RecipeSerializer(many=True))
    def get(self, request: Request) -> Response:
        installed = set(
            Automation.objects.exclude(recipe_key="").values_list("recipe_key", flat=True)
        )
        rows = [{**asdict(r), "installed": r.key in installed} for r in recipes.RECIPES]
        return Response(s.RecipeSerializer(rows, many=True).data)


class RecipeInstallView(APIView):
    permission_classes = [*AUTH, HasMethodPermission.for_({"POST": "automation.manage"})]

    @extend_schema(request=None, responses={201: s.AutomationSerializer})
    def post(self, request: Request, key: str) -> Response:
        automation = recipes.install(key, user=request.user)
        if automation is None:
            raise NotFound("No such recipe.")
        return Response(s.AutomationSerializer(automation).data, status=status.HTTP_201_CREATED)


class AutomationSchemaView(APIView):
    permission_classes = [*AUTH, HasMethodPermission.for_({"GET": "automation.view"})]

    @extend_schema(responses=s.AutomationSchemaSerializer)
    def get(self, request: Request) -> Response:
        """What the builder can offer: subjects and their fields, events, actions."""
        body = {
            "subjects": [
                {
                    "key": sub.key,
                    "label": sub.label,
                    "fields": [
                        {"path": f.path, "label": f.label, "type": f.type,
                         "choices": list(f.choices)} for f in sub.fields
                    ],
                    "recipients": [*sub.recipients, *(["owner"] if sub.owner else [])],
                    "setters": list(sub.setters),
                    "date_fields": list(sub.date_fields),
                    "taggable": bool(sub.target),
                }
                for sub in registry.subjects()
            ],
            "triggers": [asdict(t) for t in registry.triggers()],
            "actions": [
                {
                    "key": a.key,
                    "label": a.label,
                    "fields": [
                        {"name": f.name, "label": f.label, "type": f.type,
                         "required": f.required, "choices": list(f.choices)} for f in a.fields
                    ],
                    "subjects": list(a.subjects),
                    "permission": a.permission,
                    "allowed": not a.permission or has_perm(request.user, a.permission),
                }
                for a in registry.actions()
            ],
            "operators": list(conditions.OPERATORS),
            "predicates": conditions.predicates(),
        }  # fmt: skip
        return Response(s.AutomationSchemaSerializer(body).data)
