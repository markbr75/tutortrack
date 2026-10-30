"""Pathways API (E34 §4, T01)."""

from __future__ import annotations

from typing import Any

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation
from tutortrack.people.models import TutorProfile

from .. import selectors, services
from ..models import PathwayRun, PathwayStep, PathwayTemplate
from ..pathway_steps import step_types
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def _my_tutor(request: Request) -> TutorProfile:
    tutor = TutorProfile.objects.filter(membership__user=request.user).first()
    if tutor is None:
        raise NotFound("You're not a tutor here.")
    return tutor


TEMPLATE_EXAMPLE = OpenApiExample(
    "A short onboarding",
    value={
        "name": "Join a GCSE job",
        "kind": "join",
        "record_type": "job",
        "stages": [
            {
                "key": "before_first_lesson",
                "name": "Before your first lesson",
                "gate": "ready",
                "steps": [
                    {
                        "key": "agreement",
                        "type": "sign",
                        "name": "Sign the job agreement",
                        "due_days": 3,
                        "config": {"title": "Job agreement", "text": "I agree to..."},
                    },
                    {
                        "key": "check",
                        "type": "staff_review",
                        "assignee": "staff",
                        "role": "coordinator",
                        "config": {"question": "Is the tutor ready?"},
                    },
                ],
            }
        ],
    },
    request_only=True,
)


class PathwayTemplateViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Pathway templates: stages of steps that a tutor follows (FR-34-1). Changing the
    stages adds a version; runs already started keep theirs. Switch one off with
    ``active: false``."""

    model = PathwayTemplate
    serializer_class = s.PathwayTemplateSerializer
    pagination_class = None
    permission_classes = perms({"GET": "pathway.view", "*": "pathway.manage"})

    def get_tenant_queryset(self) -> Any:
        return selectors.templates()

    def _save(self, request: Request, instance: PathwayTemplate | None) -> Response:
        payload = s.PathwayTemplateSerializer(
            instance, data=request.data, partial=instance is not None
        )
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        current = instance.current_version.stages if instance and instance.current_version else []
        template = services.save_template(
            instance,
            name=data.get("name", instance.name if instance else ""),
            subject_type=data.get("subject_type", instance.subject_type if instance else ""),
            stages=data.get("stages", current),
            kind=data.get("kind", instance.kind if instance else PathwayTemplate.Kind.CUSTOM),
            description=data.get("description", instance.description if instance else ""),
            active=data.get("active", instance.active if instance else True),
        )
        template = selectors.templates().get(pk=template.pk)
        return Response(
            s.PathwayTemplateSerializer(template).data,
            status=status.HTTP_200_OK if instance else status.HTTP_201_CREATED,
        )

    @extend_schema(examples=[TEMPLATE_EXAMPLE])
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._save(request, None)

    @extend_schema(examples=[TEMPLATE_EXAMPLE])
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._save(request, self.get_object())

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._save(request, self.get_object())


class PathwaySchemaView(APIView):
    """What a pathway can contain: step types, kinds of record, the questions TutorTrack can
    check, and the staff roles a staff step can name."""

    permission_classes = perms({"GET": "pathway.view"})

    @extend_schema(responses=s.PathwaySchemaSerializer)
    def get(self, request: Request) -> Response:
        from tutortrack.automations import registry
        from tutortrack.automations.conditions import questions

        return Response(
            {
                "step_types": [
                    {"key": t.key, "label": str(t.label), "assignees": list(t.assignees)}
                    for t in step_types()
                ],
                "record_types": [{"key": r.key, "label": r.label} for r in registry.subjects()],
                "questions": [
                    {"key": q["key"], "label": q["label"], "record_type": q["subject"]}
                    for q in questions()
                ],
                "roles": list(services.STAFF_ROLES),
            }
        )


class PathwayRunViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Pathways that tutors are following, and their steps (filter with ``?template=``,
    ``?status=``, ``?tutor=``, or ``?record_type=`` with ``?record_id=``)."""

    model = PathwayRun
    permission_classes = perms({"GET": "pathway.view", "POST": "pathway.run.manage"})

    def get_serializer_class(self) -> Any:
        return s.PathwayRunDetailSerializer if self.action == "retrieve" else s.PathwayRunSerializer

    def get_tenant_queryset(self) -> Any:
        qs = selectors.runs(self.request.user)
        params = self.request.query_params
        for param, field in (
            ("template", "template_id"),
            ("status", "status"),
            ("tutor", "tutor_id"),
            ("record_type", "subject_type"),
            ("record_id", "subject_id"),
        ):
            if params.get(param):
                qs = qs.filter(**{field: params[param]})
        if self.action == "retrieve":
            qs = qs.prefetch_related("steps__completed_by")
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter(p, str, required=False)
            for p in ("template", "status", "tutor", "record_type", "record_id")
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.StartPathwaySerializer, responses={201: s.PathwayRunDetailSerializer})
    def create(self, request: Request) -> Response:
        """Start a pathway for a tutor about one record (for a job, ``record_id`` is the job)."""
        payload = s.StartPathwaySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        template = get_object_or_404(selectors.templates(), pk=data["template"])
        tutor = get_object_or_404(TutorProfile.objects.all(), pk=data["tutor"])
        run = services.start_run(
            template, record_id=data["record_id"], tutor=tutor, owner=request.user
        )
        return Response(
            s.PathwayRunDetailSerializer(self.get_tenant_queryset().get(pk=run.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=s.PathwayReasonSerializer, responses=s.PathwayRunDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        payload = s.PathwayReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        run = services.cancel_run(
            self.get_object(), user=request.user, reason=payload.validated_data["reason"]
        )
        return Response(
            s.PathwayRunDetailSerializer(self.get_tenant_queryset().get(pk=run.pk)).data
        )


class PathwayStepActionView(APIView):
    """Staff act on a step: ``complete`` (a staff step, or accept what a tutor sent),
    ``skip`` or ``reject`` (with a reason), or ``remind`` whoever has to do it."""

    permission_classes = perms({"POST": "pathway.step.complete"})

    @extend_schema(request=s.PathwayCompleteStepSerializer, responses=s.PathwayStepSerializer)
    def post(self, request: Request, pk: Any, key: str, act: str) -> Response:
        run = get_object_or_404(selectors.runs(request.user), pk=pk)
        step = get_object_or_404(PathwayStep.objects.filter(run=run), key=key)
        if act == "complete":
            payload = s.PathwayCompleteStepSerializer(data=request.data)
            payload.is_valid(raise_exception=True)
            step = services.complete_step(step, user=request.user, payload=payload.payload())
        elif act == "remind":
            step = services.remind_step(step, user=request.user)
        else:
            reason = s.PathwayReasonSerializer(data=request.data)
            reason.is_valid(raise_exception=True)
            act_on = services.skip_step if act == "skip" else services.reject_step
            step = act_on(step, user=request.user, reason=reason.validated_data["reason"])
        return Response(s.PathwayStepSerializer(step).data)


class MyPathwayTasksView(APIView):
    """The steps the signed-in tutor has to do, or has sent for review."""

    permission_classes = AUTH

    @extend_schema(responses=s.MyPathwayTaskSerializer(many=True))
    def get(self, request: Request) -> Response:
        tasks = selectors.my_tasks(_my_tutor(request))[:200]
        return Response(s.MyPathwayTaskSerializer(tasks, many=True).data)


class MyPathwayTaskCompleteView(APIView):
    permission_classes = AUTH

    @extend_schema(request=s.PathwayCompleteStepSerializer, responses=s.MyPathwayTaskSerializer)
    def post(self, request: Request, pk: Any) -> Response:
        tutor = _my_tutor(request)
        step = get_object_or_404(
            PathwayStep.objects.filter(run__tutor=tutor, assignee="participant"), pk=pk
        )
        payload = s.PathwayCompleteStepSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        step = services.complete_step(step, user=request.user, payload=payload.payload())
        step = PathwayStep.objects.select_related("run__template").get(pk=step.pk)
        return Response(s.MyPathwayTaskSerializer(step).data)
