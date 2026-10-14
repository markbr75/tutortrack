"""Safeguarding API (E29-T08/T09): concerns and the DSL case record, flagged messages,
lone-working check-ins and children's privacy defaults."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.models import AuditEntry
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, HasPermission

from .. import children, lone_working, safeguarding, selectors
from ..models import LoneWorkingVisit, SafeguardingConcern, SafeguardingFlag
from . import serializers as s

AUTH: list[Any] = [IsAuthenticated, HasOrganisation]
DSL: list[Any] = [*AUTH, HasPermission.for_("safeguarding.dsl")]


class ConcernFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=SafeguardingConcern.Status.choices)
    category = filters.ChoiceFilter(choices=SafeguardingConcern.Category.choices)
    student = filters.UUIDFilter()
    immediate_risk = filters.BooleanFilter()

    class Meta:
        model = SafeguardingConcern
        fields: list[str] = []


class ConcernViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Safeguarding cases. Anyone with ``safeguarding.raise`` can raise a concern (and gets
    back only its reference); listing, opening and managing cases is for Designated
    Safeguarding Leads, and every opening is audited."""

    model = SafeguardingConcern
    filterset_class = ConcernFilter
    permission_classes = [
        *AUTH,
        HasMethodPermission.for_({"POST": "safeguarding.raise", "*": "safeguarding.dsl"}),
    ]

    def get_serializer_class(self) -> Any:
        if self.action == "list":
            return s.ConcernListSerializer
        return s.ConcernSerializer

    def get_tenant_queryset(self) -> QuerySet[SafeguardingConcern]:
        return selectors.concerns(self.request.user).prefetch_related(
            "actions__actor", "attachments"
        )

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        concern = safeguarding.read_case(self.get_object(), request.user)
        return Response(s.ConcernSerializer(concern, context={"request": request}).data)

    @extend_schema(
        request=s.RaiseConcernSerializer,
        responses={201: s.RaisedConcernSerializer},
        examples=[
            OpenApiExample(
                "Raised from a lesson",
                value={
                    "category": "neglect",
                    "description": "Arrived hungry for the third week running and said...",
                    "immediate_risk": False,
                    "student": "0192...",
                    "lesson": "0192...",
                },
                request_only=True,
            )
        ],
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.RaiseConcernSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        concern = safeguarding.raise_concern(
            user=request.user,
            category=data["category"],
            description=data["description"],
            immediate_risk=data["immediate_risk"],
            student_id=data.get("student"),
            lesson_id=data.get("lesson"),
            tutor_id=data.get("tutor"),
            attachment_ids=data.get("attachment_ids") or [],
        )
        return Response(s.RaisedConcernSerializer(concern).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.UpdateConcernSerializer, responses=s.ConcernSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from tutortrack.identity.models import User

        payload = s.UpdateConcernSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        assignee = None
        if data.get("assigned_to"):
            assignee = User.objects.filter(pk=data["assigned_to"]).first()
            if assignee is None:
                raise NotFound()
        concern = safeguarding.update_case(
            self.get_object(),
            status=data.get("status"),
            assigned_to=assignee,
            outcome=data.get("outcome"),
            user=request.user,
        )
        concern = self.get_queryset().get(pk=concern.pk)
        return Response(s.ConcernSerializer(concern, context={"request": request}).data)

    @extend_schema(request=s.AddActionSerializer, responses={201: s.SafeguardingActionSerializer})
    @action(detail=True, methods=["post"], url_path="actions")
    def add_action(self, request: Request, pk: Any = None) -> Response:
        payload = s.AddActionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        created = safeguarding.add_action(
            self.get_object(),
            kind=payload.validated_data["kind"],
            note=payload.validated_data.get("note", ""),
            user=request.user,
        )
        return Response(
            s.SafeguardingActionSerializer(created).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(responses=s.CaseHistorySerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def history(self, request: Request, pk: Any = None) -> Response:
        """The case's own audit trail, including every time it was opened."""
        concern = self.get_object()
        entries = (
            AuditEntry.objects.filter(
                object_type__startswith="privacy.safeguarding",
                object_id__in=[str(concern.pk), *[str(a.pk) for a in concern.actions.all()]],
            )
            .select_related("actor")
            .order_by("created_at")
        )
        return Response(
            s.CaseHistorySerializer(
                [
                    {
                        "at": e.created_at,
                        "action": e.action,
                        "actor": (e.actor.get_full_name() or e.actor.email) if e.actor else "",
                    }
                    for e in entries
                ],
                many=True,
            ).data
        )


class RaisedConcernViewSet(TenantScopedViewMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Concerns I raised: reference and progress only (the case stays with the DSLs)."""

    model = SafeguardingConcern
    serializer_class = s.RaisedConcernSerializer
    permission_classes = [*AUTH, HasPermission.for_("safeguarding.raise")]

    def get_tenant_queryset(self) -> QuerySet[SafeguardingConcern]:
        return selectors.raised_concerns(self.request.user)


class FlagFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=SafeguardingFlag.Status.choices)

    class Meta:
        model = SafeguardingFlag
        fields: list[str] = []


class FlagViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Messages the safeguards flagged (contact details, flagged words, blocked messages)."""

    model = SafeguardingFlag
    serializer_class = s.SafeguardingFlagSerializer
    filterset_class = FlagFilter
    permission_classes = DSL

    def get_tenant_queryset(self) -> QuerySet[SafeguardingFlag]:
        return selectors.flags(self.request.user).select_related("sender")

    @extend_schema(
        request=s.ReviewSafeguardingFlagSerializer, responses=s.SafeguardingFlagSerializer
    )
    @action(detail=True, methods=["post"])
    def review(self, request: Request, pk: Any = None) -> Response:
        """Dismiss the flag, or escalate it into a safeguarding concern."""
        payload = s.ReviewSafeguardingFlagSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        flag = safeguarding.review_flag(
            self.get_object(),
            decision=payload.validated_data["decision"],
            note=payload.validated_data.get("note", ""),
            user=request.user,
        )
        return Response(self.get_serializer(flag).data)


# --- lone working -------------------------------------------------------------------------------


class VisitFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=LoneWorkingVisit.Status.choices)
    lesson = filters.UUIDFilter()

    class Meta:
        model = LoneWorkingVisit
        fields: list[str] = []


class VisitViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Lone-working visits: tutors check in and out of in-person lessons; monitors see every
    visit and resolve overdue ones."""

    model = LoneWorkingVisit
    serializer_class = s.VisitSerializer
    filterset_class = VisitFilter
    permission_classes = AUTH

    def get_tenant_queryset(self) -> QuerySet[LoneWorkingVisit]:
        return selectors.visits(self.request.user)

    @extend_schema(
        request=s.CheckInSerializer,
        responses={201: s.VisitSerializer},
        examples=[OpenApiExample("Arrived", value={"lesson": "0192..."}, request_only=True)],
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="check-in",
        permission_classes=[*AUTH, HasPermission.for_("safeguarding.checkin")],
    )
    def check_in(self, request: Request) -> Response:
        payload = s.CheckInSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        visit = lone_working.check_in(user=request.user, lesson_id=payload.validated_data["lesson"])
        return Response(self.get_serializer(visit).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.CheckInSerializer, responses=s.VisitSerializer)
    @action(
        detail=False,
        methods=["post"],
        url_path="check-out",
        permission_classes=[*AUTH, HasPermission.for_("safeguarding.checkin")],
    )
    def check_out(self, request: Request) -> Response:
        payload = s.CheckInSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        visit = lone_working.check_out(
            user=request.user, lesson_id=payload.validated_data["lesson"]
        )
        return Response(self.get_serializer(visit).data)

    @extend_schema(request=s.ResolveVisitSerializer, responses=s.VisitSerializer)
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[*AUTH, HasPermission.for_("safeguarding.lone_working.monitor")],
    )
    def resolve(self, request: Request, pk: Any = None) -> Response:
        """The tutor is safe (confirmed by phone, for example)."""
        payload = s.ResolveVisitSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        visit = lone_working.resolve(
            self.get_object(), user=request.user, note=payload.validated_data["note"]
        )
        return Response(self.get_serializer(visit).data)


class ChildPrivacyView(APIView):
    """The age-aware defaults that apply to a student (COPPA / Age Appropriate Design Code)."""

    permission_classes = [*AUTH, HasPermission.for_("people.student.view")]

    @extend_schema(responses=s.ChildPrivacySerializer)
    def get(self, request: Request, student_id: str) -> Response:
        from tutortrack.core.permissions import scope_queryset
        from tutortrack.people.models import Student

        student = (
            scope_queryset(request.user, Student.objects.all(), "people.student.view")
            .filter(pk=student_id)
            .first()
        )
        if student is None:
            raise NotFound()
        return Response(s.ChildPrivacySerializer(children.defaults_for(student)).data)
