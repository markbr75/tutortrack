from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.context import current_branch_ids, require_organisation_id
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation

from .. import permissions as perms
from .. import services, settings_service
from ..models import Branch, Organisation
from ..settings_registry import registry
from .serializers import (
    BranchSerializer,
    OrganisationSerializer,
    SettingsAreaSerializer,
    SettingsPatchSerializer,
)

VIEW_MANAGE = {"GET": perms.SETTINGS_VIEW, "PATCH": perms.SETTINGS_MANAGE}


class OrganisationView(APIView):
    """The current organisation's profile (FR-02-1)."""

    permission_classes = [IsAuthenticated, HasOrganisation, HasMethodPermission.for_(VIEW_MANAGE)]

    def _org(self) -> Organisation:
        return Organisation.objects.get(pk=require_organisation_id())

    @extend_schema(responses=OrganisationSerializer)
    def get(self, request: Request) -> Response:
        return Response(OrganisationSerializer(self._org(), context={"request": request}).data)

    @extend_schema(
        request=OrganisationSerializer,
        responses=OrganisationSerializer,
        examples=[
            OpenApiExample(
                "Rename and set branding",
                value={"name": "Bright Minds Tutoring", "primary_colour": "#1d4ed8"},
                request_only=True,
            ),
            OpenApiExample(
                "Change subdomain (old one redirects for 90 days)",
                value={"slug": "brightminds-london"},
                request_only=True,
            ),
        ],
    )
    def patch(self, request: Request) -> Response:
        org = self._org()
        serializer = OrganisationSerializer(
            org, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        services.update_organisation(org, **serializer.validated_data)
        org.refresh_from_db()
        return Response(OrganisationSerializer(org, context={"request": request}).data)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("include_archived", bool, description="Include archived branches.")
        ]
    ),
    create=extend_schema(
        examples=[
            OpenApiExample(
                "New branch",
                value={"name": "Leeds", "code": "LDS", "timezone": "Europe/London"},
                request_only=True,
            )
        ]
    ),
    destroy=extend_schema(description="Archives the branch (the default branch cannot be)."),
)
class BranchViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Branches (FR-02-2). Extra branches need the ``multi_branch`` feature."""

    model = Branch
    serializer_class = BranchSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_classes = [
        IsAuthenticated,
        HasOrganisation,
        HasMethodPermission.for_({"GET": perms.SETTINGS_VIEW, "*": perms.BRANCH_MANAGE}),
    ]

    def get_tenant_queryset(self) -> QuerySet[Branch]:
        qs = Branch.objects.all()
        scope = current_branch_ids()
        if scope is not None:
            qs = qs.filter(pk__in=scope)
        include_archived = self.request.query_params.get("include_archived") in {"1", "true"}
        if self.action == "list" and not include_archived:
            qs = qs.filter(archived_at__isnull=True)
        return qs

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.create_branch(**serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.update_branch(
            serializer.instance, **serializer.validated_data
        )

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        branch = services.archive_branch(self.get_object())
        return Response(self.get_serializer(branch).data, status=status.HTTP_200_OK)


class SettingsView(APIView):
    """Typed settings for one area, e.g. ``general`` or ``billing`` (FR-02-5).

    ``schema`` describes each setting so the frontend can render the form. With
    ``?branch=<id>``, ``values`` are the effective values for that branch and
    ``overrides`` lists the keys set at branch level.
    """

    permission_classes = [IsAuthenticated, HasOrganisation, HasMethodPermission.for_(VIEW_MANAGE)]
    branch_param = OpenApiParameter(
        "branch", str, description="Branch id: read or override branch-level values."
    )

    def _branch(self, request: Request) -> Branch | None:
        branch_id = request.query_params.get("branch")
        if not branch_id:
            return None
        qs = Branch.objects.all()
        scope = current_branch_ids()
        if scope is not None:
            qs = qs.filter(pk__in=scope)
        try:
            return get_object_or_404(qs, pk=branch_id)
        except Exception as exc:  # malformed uuid -> 404 as well
            raise NotFound() from exc

    def _payload(self, area: str, branch: Branch | None) -> dict[str, Any]:
        return {
            "area": area,
            "branch": branch.pk if branch else None,
            "values": settings_service.area_values(area, branch=branch),
            "overrides": settings_service.branch_overrides(area, branch) if branch else [],
            "schema": [d.describe() for d in registry.area(area)],
        }

    def _check_area(self, area: str) -> None:
        if area not in registry.areas():
            raise NotFound(f"Unknown settings area {area!r}.")

    @extend_schema(parameters=[branch_param], responses=SettingsAreaSerializer)
    def get(self, request: Request, area: str) -> Response:
        self._check_area(area)
        return Response(self._payload(area, self._branch(request)))

    @extend_schema(
        parameters=[branch_param],
        request=SettingsPatchSerializer,
        responses=SettingsAreaSerializer,
        examples=[
            OpenApiExample(
                "Rename Tutor to Teacher",
                value={
                    "values": {
                        "general.terminology": {
                            "tutor": {"singular": "Teacher", "plural": "Teachers"}
                        }
                    }
                },
                request_only=True,
            ),
            OpenApiExample(
                "Branch override, then remove it",
                value={"values": {"general.default_lesson_duration": None}},
                request_only=True,
            ),
        ],
    )
    def patch(self, request: Request, area: str) -> Response:
        self._check_area(area)
        branch = self._branch(request)
        payload = SettingsPatchSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        settings_service.update_settings(area, payload.validated_data["values"], branch=branch)
        return Response(self._payload(area, branch))


# --- org switcher (FR-02-7) ---------------------------------------------------------------------


class MyOrganisationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    url = serializers.CharField()
    role = serializers.CharField()
    status = serializers.CharField(help_text="Organisation status (trial, active, suspended...)")
    is_current = serializers.BooleanField()
    last_active_at = serializers.DateTimeField(allow_null=True)


class MyOrganisationsView(APIView):
    """Organisations the signed-in user belongs to, most recently used first.

    Switching is navigation: open ``url``. Each organisation is a separate security
    context, so permissions never carry across.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MyOrganisationSerializer(many=True))
    def get(self, request: Request) -> Response:
        from tutortrack.identity.selectors import memberships_for_user

        current = getattr(request, "organisation", None)
        rows = [
            {
                "id": m.organisation.pk,
                "name": m.organisation.name,
                "slug": m.organisation.slug,
                "url": m.organisation.base_url,
                "role": m.role,
                "status": m.organisation.status,
                "is_current": current is not None and current.pk == m.organisation_id,
                "last_active_at": m.last_active_at,
            }
            for m in memberships_for_user(request.user)
            if m.organisation.status != Organisation.Status.CANCELLED
        ]
        return Response(MyOrganisationSerializer(rows, many=True).data)


# --- demo data (E02-T08) ------------------------------------------------------------------------


class DemoDataSerializer(serializers.Serializer):
    has_demo_data = serializers.BooleanField()
    records = serializers.IntegerField()


class DemoDataView(APIView):
    """Load sample data to explore the product (POST) or wipe it in one click (DELETE)."""

    permission_classes = [
        IsAuthenticated,
        HasOrganisation,
        HasMethodPermission.for_({"*": perms.SETTINGS_MANAGE}),
    ]

    @extend_schema(request=None, responses={201: DemoDataSerializer})
    def post(self, request: Request) -> Response:
        from .. import demo

        records = demo.load_demo_data()
        return Response({"has_demo_data": True, "records": records}, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: DemoDataSerializer})
    def delete(self, request: Request) -> Response:
        from .. import demo

        records = demo.wipe_demo_data()
        return Response({"has_demo_data": False, "records": records})


# --- close account (FR-02-8) --------------------------------------------------------------------


class CloseOrganisationSerializer(serializers.Serializer):
    password = serializers.CharField(trim_whitespace=False, write_only=True)
    confirm_slug = serializers.CharField(help_text="Type the organisation's subdomain.")
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)
    export_data = serializers.BooleanField(
        default=True, help_text="Email the owner a full data export (E28) before deletion."
    )


class CloseOrganisationView(APIView):
    """Close the account (owner only). Data is kept for a 30-day grace period, then
    deleted; the subscription is cancelled."""

    permission_classes = [
        IsAuthenticated,
        HasOrganisation,
        HasMethodPermission.for_({"POST": perms.CLOSE}),
    ]

    @extend_schema(
        request=CloseOrganisationSerializer,
        responses=OrganisationSerializer,
        examples=[
            OpenApiExample(
                "Close",
                value={
                    "password": "my password",
                    "confirm_slug": "brightminds",
                    "reason": "Retiring",
                    "export_data": True,
                },
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        from ..lifecycle import close_organisation

        payload = CloseOrganisationSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        org = close_organisation(
            Organisation.objects.get(pk=require_organisation_id()),
            user=request.user,
            password=data["password"],
            confirm_slug=data["confirm_slug"],
            reason=data.get("reason", ""),
            export_requested=data["export_data"],
        )
        return Response(OrganisationSerializer(org, context={"request": request}).data)
