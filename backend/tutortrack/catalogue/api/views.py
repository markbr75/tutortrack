"""Catalogue and pricing API (E06 §4)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db import transaction
from django.db.models import Prefetch, QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
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

from .. import pricing_rules, rates, services
from ..models import (
    Category,
    DiscountRule,
    Holiday,
    HolidayCalendar,
    Level,
    Location,
    PackageTemplate,
    PayTier,
    PremiumRule,
    PriceList,
    Product,
    PromoCode,
    Room,
    Service,
    ServicePrice,
    ServiceTierRate,
    Subject,
    TaxRate,
    TutorPayTierAssignment,
    TutorServiceRate,
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
        attendees = [
            rates.AttendeeInput(
                student_id=str(row["student"]),
                client_id=str(clients[row["student"]]),
                rate_override=row.get("rate_override"),
                job_rate_override=row.get("job_rate_override"),
            )
            for row in data["students"]
        ]
        tutor_inputs = [
            rates.TutorInput(
                tutor_id=str(row["tutor"]),
                rate_override=row.get("rate_override"),
                job_rate_override=row.get("job_rate_override"),
            )
            for row in data["tutors"]
        ]
        location = (
            Location.objects.filter(pk=data["location"]).first() if data.get("location") else None
        )
        promo = None
        if data.get("promo_code"):
            promo = services.check_promo(data["promo_code"], service=service)
        rules = pricing_rules.load_rules(
            service=service,
            currency=(data.get("currency") or service.currency).upper(),
            start=data.get("starts_at"),
            timezone=data.get("timezone") or _org_timezone(),
            location=location,
            online=data.get("online", False),
            attendees=attendees,
            tutors=tutor_inputs,
            booked_at=data.get("booked_at"),
            promo_code=promo,
        )
        quote = rates.resolve_rates(
            rates.RateContext(
                service=service,
                duration_minutes=data["duration_minutes"],
                currency=data.get("currency"),
                job_charge_rate=data.get("job_charge_rate"),
                attendees=attendees,
                tutors=tutor_inputs,
                rules=rules,
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


def _org_timezone() -> str:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    return str(Organisation.objects.get(pk=require_organisation_id()).timezone)


# --- Phase 2: rooms (T10) -----------------------------------------------------------------


class RoomFilter(filters.FilterSet):
    location = filters.UUIDFilter()
    active = filters.BooleanFilter()
    bookable = filters.BooleanFilter()
    resource = filters.CharFilter(method="with_resource")

    class Meta:
        model = Room
        fields: list[str] = []

    def with_resource(self, qs: QuerySet[Any], name: str, value: str) -> QuerySet[Any]:
        return qs.filter(resources__name__iexact=value).distinct()


class RoomViewSet(CatalogueViewSet):
    """Rooms inside locations, with their resources (FR-06-10). Lessons can't double-book a
    room (E08)."""

    model = Room
    serializer_class = s.RoomSerializer
    filterset_class = RoomFilter
    save = staticmethod(services.save_room)

    def get_tenant_queryset(self) -> QuerySet[Room]:
        return Room.objects.select_related("location").prefetch_related("resources")


# --- pay tiers and tutor rates (T07) -----------------------------------------------------------


def rate_perms() -> list[Any]:
    return [*AUTH, HasMethodPermission.for_({"GET": "billing.rates.view_pay", "*": "rates.manage"})]


class PayTierViewSet(ArchivableViewSet):
    """Wage tiers (FR-06-5)."""

    model = PayTier
    serializer_class = s.PayTierSerializer
    filterset_class = type(
        "PayTierFilter",
        (ArchivedFilter,),
        {"Meta": type("Meta", (), {"model": PayTier, "fields": []})},
    )
    pagination_class = None
    permission_classes = perms("rates.manage")
    save = staticmethod(services.save_pay_tier)


def _money_dict(value: Any) -> dict[str, str] | None:
    return None if value is None else {"amount": f"{value.amount:f}", "currency": value.currency}


class TierRatesView(APIView):
    """The services by tiers grid (GET) and bulk edits of it (POST), FR-06-5."""

    permission_classes = rate_perms()

    @extend_schema(responses=s.TierGridSerializer)
    def get(self, request: Request) -> Response:
        tiers = PayTier.objects.filter(archived_at__isnull=True)
        cells = [
            {
                "service": str(row.service_id),
                "tier": str(row.tier_id),
                "pay_rate": _money_dict(row.pay_rate),
                "charge_rate": _money_dict(row.charge_rate),
            }
            for row in ServiceTierRate.objects.filter(tier__in=tiers)
        ]
        return Response({"tiers": s.PayTierSerializer(tiers, many=True).data, "cells": cells})

    @extend_schema(request=s.TierBulkSerializer, responses=s.TierGridSerializer)
    def post(self, request: Request) -> Response:
        payload = s.TierBulkSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        with transaction.atomic():
            for cell in payload.validated_data["cells"]:
                service = get_object_or_404(Service, pk=cell["service"])
                tier = get_object_or_404(PayTier, pk=cell["tier"])
                services.set_tier_rate(
                    service,
                    tier,
                    pay_rate=cell.get("pay_rate"),
                    charge_rate=cell.get("charge_rate"),
                )
        return self.get(request)


class TierRatesCsvView(APIView):
    """CSV export (GET) and import (POST, multipart ``file``) of the tier grid."""

    permission_classes = rate_perms()
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(responses={(200, "text/csv"): OpenApiTypes.STR})
    def get(self, request: Request) -> HttpResponse:
        response = HttpResponse(services.tier_rates_csv(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="tier-rates.csv"'
        return response

    @extend_schema(request=s.TierImportSerializer, responses=s.TierImportResultSerializer)
    def post(self, request: Request) -> Response:
        payload = s.TierImportSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        upload = payload.validated_data["file"]
        if upload.size > 2_000_000:
            raise ValidationError({"file": ["The file is too large (2 MB at most)."]})
        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError({"file": ["Save the file as UTF-8 CSV."]}) from exc
        result = services.import_tier_rates(text, dry_run=payload.validated_data["dry_run"])
        return Response(
            {"updated": result.updated, "unchanged": result.unchanged, "row_errors": result.errors}
        )


class TierAssignmentFilter(filters.FilterSet):
    tutor = filters.UUIDFilter()
    tier = filters.UUIDFilter()

    class Meta:
        model = TutorPayTierAssignment
        fields: list[str] = []


class TierAssignmentViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Tutors' tiers with effective dates. ``recalculate`` re-prices the tutor's unlocked
    lessons from that date (FR-06-5)."""

    model = TutorPayTierAssignment
    serializer_class = s.TierAssignmentSerializer
    filterset_class = TierAssignmentFilter
    permission_classes = perms("rates.manage")

    def get_tenant_queryset(self) -> QuerySet[TutorPayTierAssignment]:
        return TutorPayTierAssignment.objects.select_related("tier")

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        serializer.instance = services.assign_tier(
            data["tutor"],
            data["tier"],
            effective_from=data["effective_from"],
            note=data.get("note", ""),
            recalculate=data.get("recalculate", False),
        )

    def perform_destroy(self, instance: TutorPayTierAssignment) -> None:
        services.remove_tier_assignment(instance)


class TutorRateFilter(filters.FilterSet):
    tutor = filters.UUIDFilter()
    service = filters.UUIDFilter()

    class Meta:
        model = TutorServiceRate
        fields: list[str] = []


class TutorRateViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Tutors' personal pay rates per service; ``POST`` sets one (``pay_rate: null``
    removes it)."""

    model = TutorServiceRate
    serializer_class = s.TutorRateSerializer
    filterset_class = TutorRateFilter
    permission_classes = rate_perms()

    def get_tenant_queryset(self) -> QuerySet[TutorServiceRate]:
        return TutorServiceRate.objects.select_related("service")

    @extend_schema(request=s.TutorRateInputSerializer, responses=s.TutorRateSerializer)
    def create(self, request: Request) -> Response:
        payload = s.TutorRateInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        tutor = get_object_or_404(TutorProfile, pk=data["tutor"])
        service = get_object_or_404(Service, pk=data["service"])
        row = services.set_tutor_rate(tutor, service, data["pay_rate"])
        if row is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        body = s.TutorRateSerializer(row, context=self.get_serializer_context()).data
        return Response(body, status=status.HTTP_201_CREATED)


# --- holidays and premiums (T08) ---------------------------------------------------------------


class HolidayCalendarViewSet(CatalogueViewSet):
    """Holiday calendars (FR-06-6): premium rules and lesson series that skip holidays use
    them."""

    model = HolidayCalendar
    serializer_class = s.HolidayCalendarSerializer
    pagination_class = None
    save = staticmethod(services.save_holiday_calendar)

    def get_tenant_queryset(self) -> QuerySet[HolidayCalendar]:
        return HolidayCalendar.objects.prefetch_related("holidays")

    @extend_schema(request=s.HolidayInputSerializer, responses=s.HolidaySerializer)
    @action(detail=True, methods=["post"])
    def holidays(self, request: Request, pk: Any = None) -> Response:
        payload = s.HolidayInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        holiday = services.add_holiday(
            self.get_object(),
            day=payload.validated_data["date"],
            name=payload.validated_data["name"],
        )
        return Response(s.HolidaySerializer(holiday).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.HolidayImportSerializer, responses=s.HolidayCalendarSerializer)
    @action(detail=True, methods=["post"], url_path="import")
    def import_holidays(self, request: Request, pk: Any = None) -> Response:
        """Add the country's public holidays for a year (GB and US)."""
        payload = s.HolidayImportSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        calendar = self.get_object()
        services.import_public_holidays(calendar, payload.validated_data["year"])
        calendar = self.get_tenant_queryset().get(pk=calendar.pk)
        return Response(self.get_serializer(calendar).data)


class HolidayViewSet(TenantScopedViewMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    model = Holiday
    serializer_class = s.HolidaySerializer
    permission_classes = perms()

    def get_tenant_queryset(self) -> QuerySet[Holiday]:
        return Holiday.objects.all()

    def perform_destroy(self, instance: Holiday) -> None:
        services.delete_holiday(instance)


class PremiumRuleViewSet(CatalogueViewSet):
    """Premiums and surcharges (FR-06-6)."""

    model = PremiumRule
    serializer_class = s.PremiumRuleSerializer
    permission_classes = perms("rates.manage")
    save = staticmethod(services.save_premium)

    def get_tenant_queryset(self) -> QuerySet[PremiumRule]:
        return PremiumRule.objects.all()


# --- discounts, promo codes and price lists (T09) ----------------------------------------------


class DiscountFilter(filters.FilterSet):
    kind = filters.ChoiceFilter(choices=DiscountRule.Kind.choices)
    active = filters.BooleanFilter()
    client = filters.UUIDFilter()

    class Meta:
        model = DiscountRule
        fields: list[str] = []


class DiscountRuleViewSet(CatalogueViewSet):
    """Discounts (FR-06-7): sibling, volume, first lesson / trial, client, scholarship and
    promo-code discounts."""

    model = DiscountRule
    serializer_class = s.DiscountRuleSerializer
    filterset_class = DiscountFilter
    permission_classes = perms("rates.manage")
    save = staticmethod(services.save_discount)

    def get_tenant_queryset(self) -> QuerySet[DiscountRule]:
        return DiscountRule.objects.all()


class PromoCodeViewSet(CatalogueViewSet):
    model = PromoCode
    serializer_class = s.PromoCodeSerializer
    permission_classes = perms("rates.manage")
    save = staticmethod(services.save_promo_code)

    def get_tenant_queryset(self) -> QuerySet[PromoCode]:
        return PromoCode.objects.select_related("discount")


class PriceListViewSet(CatalogueViewSet):
    """Contract price lists for specific clients (FR-06-11)."""

    model = PriceList
    serializer_class = s.PriceListSerializer
    permission_classes = perms("rates.manage")

    def get_tenant_queryset(self) -> QuerySet[PriceList]:
        return PriceList.objects.prefetch_related("items", "clients")

    @staticmethod
    def _resolve(data: dict[str, Any]) -> dict[str, Any]:
        from tutortrack.people.models import Client

        if "items" in data:
            data["items"] = [
                {"service": get_object_or_404(Service, pk=row["service"]),
                 "charge_rate": row["charge_rate"]}
                for row in data["items"]
            ]  # fmt: skip
        if "clients" in data:
            ids = [str(c) for c in data["clients"]]
            found = list(Client.objects.filter(pk__in=ids))
            if len(found) != len(set(ids)):
                raise ValidationError({"client_ids": ["Unknown client."]})
            data["clients"] = found
        return data

    def perform_create(self, serializer: Any) -> None:
        data = self._resolve(dict(serializer.validated_data))
        serializer.instance = services.save_price_list(None, **data)

    def perform_update(self, serializer: Any) -> None:
        data = self._resolve(dict(serializer.validated_data))
        serializer.instance = services.save_price_list(serializer.instance, **data)
