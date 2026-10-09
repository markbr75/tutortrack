"""Catalogue and pricing API (E06 §4)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db.models import Prefetch, QuerySet
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.permissions import (
    HasMethodPermission,
    HasOrganisation,
    has_perm,
    scope_queryset,
)
from tutortrack.people.models import Student, TutorProfile

from .. import rates, services
from ..models import (
    Category,
    Level,
    Location,
    PackageTemplate,
    Product,
    Service,
    ServicePrice,
    Subject,
    TaxRate,
)
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(manage: str = "catalogue.manage") -> list[Any]:
    return [*AUTH, HasMethodPermission.for_({"GET": "catalogue.view", "*": manage})]


class ArchivedFilter(filters.FilterSet):
    include_archived = filters.BooleanFilter(method="with_archived")

    def with_archived(self, qs: QuerySet[Any], name: str, value: bool) -> QuerySet[Any]:
        return qs  # handled in filter_queryset so the default hides archived rows

    def filter_queryset(self, queryset: QuerySet[Any]) -> QuerySet[Any]:
        queryset = super().filter_queryset(queryset)
        if not self.form.cleaned_data.get("include_archived"):
            queryset = queryset.filter(archived_at__isnull=True)
        return queryset


class CatalogueViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Create and edit through ``save``; nothing is deleted (archive or deactivate)."""

    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_classes = perms()
    save: Callable[..., Any]

    def get_tenant_queryset(self) -> QuerySet[Any]:
        return self.model._default_manager.all()

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = type(self).save(None, **serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = type(self).save(serializer.instance, **serializer.validated_data)


class ArchivableViewSet(CatalogueViewSet):
    def filter_queryset(self, queryset: QuerySet[Any]) -> QuerySet[Any]:
        # Filters (which hide archived rows) apply to lists; archived rows stay addressable.
        return super().filter_queryset(queryset) if self.action == "list" else queryset

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def archive(self, request: Request, pk: Any = None) -> Response:
        instance = services.set_archived(self.get_object(), True)
        return Response(self.get_serializer(instance).data)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def restore(self, request: Request, pk: Any = None) -> Response:
        instance = services.set_archived(self.get_object(), False)
        return Response(self.get_serializer(instance).data)


class CategoryViewSet(ArchivableViewSet):
    """Optional grouping of subjects and services (FR-06-1)."""

    model = Category
    serializer_class = s.CategorySerializer
    filterset_class = type(
        "CategoryFilter",
        (ArchivedFilter,),
        {"Meta": type("Meta", (), {"model": Category, "fields": []})},
    )
    pagination_class = None
    save = staticmethod(services.save_category)


class SubjectFilter(ArchivedFilter):
    category = filters.UUIDFilter()

    class Meta:
        model = Subject
        fields: list[str] = []


class SubjectViewSet(ArchivableViewSet):
    """Subjects with their (active) levels (FR-06-1)."""

    model = Subject
    serializer_class = s.SubjectSerializer
    filterset_class = SubjectFilter
    pagination_class = None
    save = staticmethod(services.save_subject)

    def get_tenant_queryset(self) -> QuerySet[Subject]:
        return Subject.objects.prefetch_related("levels")


class LevelFilter(ArchivedFilter):
    subject = filters.UUIDFilter()

    class Meta:
        model = Level
        fields: list[str] = []


class LevelViewSet(ArchivableViewSet):
    model = Level
    serializer_class = s.LevelSerializer
    filterset_class = LevelFilter
    pagination_class = None
    save = staticmethod(services.save_level)


class TaxRateViewSet(CatalogueViewSet):
    """Tax rates (FR-06-3). One is the default for new services and products."""

    model = TaxRate
    serializer_class = s.TaxRateSerializer
    pagination_class = None
    permission_classes = perms("rates.manage")
    save = staticmethod(services.save_tax_rate)


class ServiceFilter(filters.FilterSet):
    active = filters.BooleanFilter()
    subject = filters.UUIDFilter()
    category = filters.UUIDFilter()
    format = filters.ChoiceFilter(choices=Service.Format.choices)
    bookable_online = filters.BooleanFilter()

    class Meta:
        model = Service
        fields: list[str] = []


RATE_FIELDS = {"charge_rate", "pay_rate", "pay_percent"}


class ServiceViewSet(CatalogueViewSet):
    """What you sell (FR-06-2). Changing default rates needs ``rates.manage``; existing
    lessons keep their snapshotted prices."""

    model = Service
    serializer_class = s.ServiceSerializer
    filterset_class = ServiceFilter

    def get_tenant_queryset(self) -> QuerySet[Service]:
        return Service.objects.select_related("tax_rate").prefetch_related(
            "branches", Prefetch("prices", queryset=ServicePrice.objects.order_by("currency"))
        )

    def _check_rates(self, data: dict[str, Any]) -> None:
        if RATE_FIELDS & set(data) and not has_perm(self.request.user, "rates.manage"):
            raise PermissionDenied()

    def perform_create(self, serializer: Any) -> None:
        self._check_rates(serializer.validated_data)
        serializer.instance = services.create_service(**serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        self._check_rates(serializer.validated_data)
        serializer.instance = services.update_service(
            serializer.instance, **serializer.validated_data
        )

    @extend_schema(request=s.ServicePriceSerializer, responses=s.ServicePriceSerializer)
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[*AUTH, HasMethodPermission.for_({"POST": "rates.manage"})],
    )
    def prices(self, request: Request, pk: Any = None) -> Response:
        """Set the price in another currency (FR-06-12)."""
        payload = s.ServicePriceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        price = services.set_service_price(self.get_object(), **payload.validated_data)
        return Response(s.ServicePriceSerializer(price, context=self.get_serializer_context()).data)


class LocationViewSet(ArchivableViewSet):
    """Where lessons happen (FR-06-10)."""

    model = Location
    serializer_class = s.LocationSerializer
    filterset_class = type(
        "LocationFilter",
        (ArchivedFilter,),
        {"Meta": type("Meta", (), {"model": Location, "fields": []})},
    )
    save = staticmethod(services.save_location)

    def get_tenant_queryset(self) -> QuerySet[Location]:
        return Location.objects.select_related("address")


class ProductFilter(filters.FilterSet):
    active = filters.BooleanFilter()
    category = filters.ChoiceFilter(choices=Product.Category.choices)

    class Meta:
        model = Product
        fields: list[str] = []


class PackageFilter(filters.FilterSet):
    active = filters.BooleanFilter()
    bookable_online = filters.BooleanFilter()

    class Meta:
        model = PackageTemplate
        fields: list[str] = []


class ProductViewSet(CatalogueViewSet):
    """Fees and products for ad hoc charges (FR-06-9)."""

    model = Product
    serializer_class = s.ProductSerializer
    filterset_class = ProductFilter
    save = staticmethod(services.save_product)


class PackageTemplateViewSet(CatalogueViewSet):
    """Prepaid package templates (FR-06-8); selling them is E10."""

    model = PackageTemplate
    serializer_class = s.PackageTemplateSerializer
    filterset_class = PackageFilter
    save = staticmethod(services.save_package)

    def get_tenant_queryset(self) -> QuerySet[PackageTemplate]:
        return PackageTemplate.objects.prefetch_related("services")


class QuoteView(APIView):
    """Dry-run the rate engine for a lesson (FR-06-4): charge lines per student and pay
    lines per tutor, each with a trace. You only see the sides your role may see."""

    permission_classes = [*AUTH, HasMethodPermission.for_({"POST": "catalogue.view"})]

    @extend_schema(
        request=s.QuoteRequestSerializer,
        responses=s.RateQuoteSerializer,
        examples=[
            OpenApiExample(
                "90-minute lesson",
                request_only=True,
                value={
                    "service": "01926d8e-0000-7000-8000-000000000001",
                    "duration_minutes": 90,
                    "students": [{"student": "01926d8e-0000-7000-8000-000000000002"}],
                    "tutors": [{"tutor": "01926d8e-0000-7000-8000-000000000003"}],
                },
            )
        ],
    )
    def post(self, request: Request) -> Response:
        payload = s.QuoteRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        service = get_object_or_404(Service, pk=data["service"])
        student_ids = [str(row["student"]) for row in data["students"]]
        students = scope_queryset(request.user, Student.objects.all(), "people.student.view")
        clients = dict(students.filter(pk__in=student_ids).values_list("pk", "client_id"))
        tutor_ids = {str(row["tutor"]) for row in data["tutors"]}
        known_tutors = {
            str(pk)
            for pk in scope_queryset(
                request.user, TutorProfile.objects.filter(pk__in=tutor_ids), "people.tutor.view"
            ).values_list("pk", flat=True)
        }
        if len(clients) != len(set(student_ids)) or known_tutors != tutor_ids:
            from tutortrack.core.exceptions import NotFound

            raise NotFound()
        quote = rates.resolve_rates(
            rates.RateContext(
                service=service,
                duration_minutes=data["duration_minutes"],
                currency=data.get("currency"),
                job_charge_rate=data.get("job_charge_rate"),
                attendees=[
                    rates.AttendeeInput(
                        student_id=str(row["student"]),
                        client_id=str(clients[row["student"]]),
                        rate_override=row.get("rate_override"),
                        job_rate_override=row.get("job_rate_override"),
                    )
                    for row in data["students"]
                ],
                tutors=[
                    rates.TutorInput(
                        tutor_id=str(row["tutor"]),
                        rate_override=row.get("rate_override"),
                        job_rate_override=row.get("job_rate_override"),
                    )
                    for row in data["tutors"]
                ],
            )
        )
        body = quote.as_dict()
        if not has_perm(request.user, "billing.rates.view_charge"):
            body.pop("charges")
            body.pop("total_charge")
        if not has_perm(request.user, "billing.rates.view_pay"):
            body.pop("pay")
            body.pop("total_pay")
        return Response(body)
