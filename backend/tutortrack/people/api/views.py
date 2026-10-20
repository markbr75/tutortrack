"""People API (E05 §4)."""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, QuerySet
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core import audit
from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.permissions import (
    HasMethodPermission,
    HasOrganisation,
    has_perm,
    scope_queryset,
)
from tutortrack.crm.listing import apply_crm_filters, selected_ids, table_export

from .. import selectors, services
from ..models import Client, Contact, Student, TutorProfile, TutorSubject
from .serializers import (
    ClientDetailSerializer,
    ClientSerializer,
    ContactSerializer,
    DuplicatePairSerializer,
    DuplicateSerializer,
    GeocodeRequestSerializer,
    GeocodeResultSerializer,
    MergePreviewSerializer,
    MergeRequestSerializer,
    MergeResultSerializer,
    PeopleMapSerializer,
    QuickAddSerializer,
    StatusSerializer,
    StudentSerializer,
    SubjectInput,
    TutorSerializer,
    TutorSubjectSerializer,
)


def perms(entity: str) -> type[HasMethodPermission]:
    return HasMethodPermission.for_(
        {
            "GET": f"people.{entity}.view",
            "POST": f"people.{entity}.create",
            "PATCH": f"people.{entity}.edit",
            "DELETE": f"people.{entity}.archive",
        }
    )


def _iso(value: Any) -> str:
    return value.isoformat() if value is not None else ""


ORDERING_PARAM = OpenApiParameter(
    "ordering",
    str,
    description="Sort by a list column, e.g. `-balance`, `next_lesson_at`, `hours_this_term`.",
)
EXPORT_RESPONSES = {
    (200, "text/csv"): OpenApiTypes.STR,
    (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): (
        OpenApiTypes.BINARY
    ),
}


def _pop_address(data: dict[str, Any], key: str) -> dict[str, Any]:
    out = {}
    if f"{key}_data" in data:
        out[key] = data.pop(f"{key}_data")
    return out


class AliasOrderingFilter(OrderingFilter):
    """``?ordering=`` over model fields and the computed list fields the queryset carries
    (FR-05-11). ``ordering_aliases`` maps a public name to its never-null sort key, so
    cursor pagination can page over ``next_lesson_at`` and friends."""

    def get_ordering(self, request: Request, queryset: QuerySet[Any], view: Any) -> Any:
        params = request.query_params.get(self.ordering_param)
        if not params:
            return self.get_default_ordering(view)
        aliases = getattr(view, "ordering_aliases", {})
        allowed = set(getattr(view, "ordering_fields", ()))
        available = set(queryset.query.annotations) | {
            f.name for f in queryset.model._meta.concrete_fields
        }
        out = []
        for term in (p.strip() for p in params.split(",")):
            name = term.lstrip("-")
            if name not in allowed:
                continue
            field = aliases.get(name, name)
            if field in available:
                out.append(("-" if term.startswith("-") else "") + field)
        return out or self.get_default_ordering(view)


EXPORT_PARAMS = [
    OpenApiParameter("file_format", str, enum=["csv", "xlsx"], description="Default csv."),
    OpenApiParameter("ids", str, description="Only these records (comma-separated ids)."),
]


class PeopleViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_backends = [filters.DjangoFilterBackend, AliasOrderingFilter]
    entity: str = ""
    entity_type: str = ""
    search_fields: tuple[str, ...] = ()
    ordering_fields: tuple[str, ...] = ("created_at",)
    ordering_aliases: dict[str, str] = {
        "next_lesson_at": "next_lesson_sort",
        "last_lesson_at": "last_lesson_sort",
        "report_sla": "report_sla_sort",
    }

    def scoped(self, qs: QuerySet[Any]) -> QuerySet[Any]:
        qs = scope_queryset(self.request.user, qs, f"people.{self.entity}.view")
        if self.action in {"list", "export"}:
            qs = apply_crm_filters(qs, self.request.query_params, self.entity_type)
            q = self.request.query_params.get("q", "").strip()
            if q:
                condition = Q()
                for field in self.search_fields:
                    condition |= Q(**{f"{field}__icontains": q})
                qs = qs.filter(condition)
            ids = selected_ids(self.request.query_params)
            if ids and self.action == "export":
                qs = qs.filter(pk__in=ids)
        return qs

    def export_file(self, request: Request, columns: list[Any], filename: str) -> Any:
        rows = self.filter_queryset(self.get_queryset())
        return table_export(
            request,
            rows,
            columns,
            filename=filename,
            entity_type=self.entity_type,
            file_format=request.query_params.get("file_format", "csv"),
        )


COMPUTED_FILTERS = {
    "balance_min": ("balance", "gte"),
    "balance_max": ("balance", "lte"),
    "next_lesson_before": ("next_lesson_at", "lt"),
    "last_lesson_before": ("last_lesson_at", "lt"),
    "last_lesson_after": ("last_lesson_at", "gte"),
    "hours_this_term_min": ("hours_this_term", "gte"),
    "hours_this_month_min": ("hours_this_month", "gte"),
    "report_sla_below": ("report_sla", "lt"),
}


class ComputedFilterSet(filters.FilterSet):
    """Filters on computed list fields; ignored when the viewer can't see that figure
    (the annotation isn't there)."""

    def computed(self, qs: QuerySet[Any], name: str, value: Any) -> QuerySet[Any]:
        field, lookup = COMPUTED_FILTERS[name]
        if value in (None, "") or field not in qs.query.annotations:
            return qs
        return qs.filter(**{f"{field}__{lookup}": value})

    def upcoming(self, qs: QuerySet[Any], name: str, value: Any) -> QuerySet[Any]:
        if value is None or "next_lesson_at" not in qs.query.annotations:
            return qs
        return qs.filter(next_lesson_at__isnull=not value)


def _computed(kind: str, name: str) -> Any:
    field = {
        "number": filters.NumberFilter,
        "datetime": filters.IsoDateTimeFilter,
    }[kind]
    return field(field_name=name, method="computed")


class ClientFilter(ComputedFilterSet):
    status = filters.ChoiceFilter(choices=Client.Status.choices)
    type = filters.ChoiceFilter(choices=Client.Type.choices)
    branch = filters.UUIDFilter(field_name="branch_id")
    account_manager = filters.UUIDFilter(field_name="account_manager_id")
    balance_min = _computed("number", "balance_min")
    balance_max = _computed("number", "balance_max")
    next_lesson_before = _computed("datetime", "next_lesson_before")
    last_lesson_before = _computed("datetime", "last_lesson_before")
    last_lesson_after = _computed("datetime", "last_lesson_after")
    hours_this_term_min = _computed("number", "hours_this_term_min")
    has_upcoming_lesson = filters.BooleanFilter(method="upcoming")

    class Meta:
        model = Client
        fields: list[str] = []


LIST_PARAMS = [
    OpenApiParameter("q", str, description="Search names, emails and phones."),
    OpenApiParameter("tag", str, many=True, description="Tag id (repeatable)."),
    OpenApiParameter("include_archived", bool),
    OpenApiParameter(
        "missing_required", bool, description="Records missing required custom fields."
    ),
    OpenApiParameter("cf_<key>", str, description="Filter by a custom field value."),
]


@extend_schema(tags=["clients"])
class ClientViewSet(PeopleViewSet):
    """Clients (billing accounts). ``DELETE`` archives (FR-05-14)."""

    model = Client
    entity, entity_type = "client", "people.client"
    search_fields = ("display_name", "contacts__email", "contacts__last_name", "contacts__phone")
    permission_classes = [IsAuthenticated, HasOrganisation, perms("client")]
    filterset_class = ClientFilter

    ordering_fields = (
        "display_name",
        "created_at",
        "students_count",
        "balance",
        "next_lesson_at",
        "last_lesson_at",
        "hours_this_term",
    )

    def get_serializer_class(self) -> Any:
        return ClientDetailSerializer if self.action == "retrieve" else ClientSerializer

    def get_tenant_queryset(self) -> QuerySet[Client]:
        qs = Client.objects.select_related("billing_address").annotate(
            students_count=Count(
                "students", filter=Q(students__archived_at__isnull=True), distinct=True
            )
        )
        qs = self.scoped(qs)
        if self.action in {"list", "retrieve", "export"}:
            qs = selectors.with_client_figures(self.request.user, qs)
        return qs.distinct()  # searching by contact joins one row per contact

    @extend_schema(parameters=[*LIST_PARAMS, ORDERING_PARAM])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        address = data.pop("billing_address_data", None)
        serializer.instance = services.create_client(billing_address=address, **data)

    def perform_update(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        data.update(_pop_address(data, "billing_address"))
        serializer.instance = services.update_client(serializer.instance, **data)

    def perform_destroy(self, instance: Client) -> None:
        services.archive_client(instance)

    @extend_schema(request=None, responses=ClientSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request: Request, pk: Any = None) -> Response:
        if not has_perm(request.user, "people.client.archive"):
            from tutortrack.core.exceptions import PermissionDenied

            raise PermissionDenied()
        client = services.restore_client(self.get_object())
        return Response(ClientSerializer(client, context={"request": request}).data)

    @extend_schema(
        parameters=[*LIST_PARAMS, *EXPORT_PARAMS, ORDERING_PARAM], responses=EXPORT_RESPONSES
    )
    @action(
        detail=False,
        methods=["get"],
        permission_classes=[
            IsAuthenticated,
            HasOrganisation,
            HasMethodPermission.for_({"GET": "people.client.export"}),
        ],
    )
    def export(self, request: Request) -> Any:
        return self.export_file(
            request,
            [
                ("id", lambda c: c.pk),
                ("name", lambda c: c.display_name),
                ("type", lambda c: c.type),
                ("status", lambda c: c.status),
                ("currency", lambda c: c.currency),
                ("students", lambda c: c.students_count),
                ("balance", lambda c: getattr(c, "balance", None)),
                ("next_lesson_at", lambda c: _iso(getattr(c, "next_lesson_at", None))),
                ("last_lesson_at", lambda c: _iso(getattr(c, "last_lesson_at", None))),
                ("hours_this_term", lambda c: getattr(c, "hours_this_term", None)),
                ("created_at", lambda c: c.created_at.isoformat()),
            ],
            "clients",
        )

    @extend_schema(
        request=QuickAddSerializer,
        responses={201: ClientDetailSerializer},
        examples=[
            OpenApiExample(
                "Family with two children",
                request_only=True,
                value={
                    "contact": {
                        "first_name": "Priya",
                        "last_name": "Patel",
                        "email": "priya@example.com",
                    },
                    "students": [
                        {
                            "first_name": "Arjun",
                            "year_group": "Year 10",
                            "subjects": [{"subject": "Maths", "level": "GCSE"}],
                        },
                        {"first_name": "Maya"},
                    ],
                },
            )
        ],
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="quick-add",
        permission_classes=[
            IsAuthenticated,
            HasOrganisation,
            HasMethodPermission.for_({"POST": "people.client.create"}),
        ],
    )
    def quick_add(self, request: Request) -> Response:
        """Client + primary contact + students in one step (FR-05-1)."""
        payload = QuickAddSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        client_fields: dict[str, Any] = {}
        if data.get("billing_address"):
            client_fields["billing_address"] = data["billing_address"]
        if data.get("branch"):
            client_fields["branch_id"] = data["branch"]
        client, _, _ = services.quick_add_family(
            contact=dict(data["contact"]),
            students=[dict(s) for s in data["students"]],
            client=client_fields,
        )
        client = self.get_tenant_queryset().get(pk=client.pk)
        return Response(
            ClientDetailSerializer(client, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class ClientContactViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Contacts of one client: ``/clients/{client_id}/contacts``."""

    model = Contact
    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticated, HasOrganisation, perms("contact")]
    pagination_class = None

    def _client(self) -> Client:
        qs = scope_queryset(self.request.user, Client.objects.all(), "people.client.view")
        return get_object_or_404(qs, pk=self.kwargs["client_id"])

    def get_tenant_queryset(self) -> QuerySet[Contact]:
        return Contact.objects.filter(client=self._client(), archived_at__isnull=True)

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        address = data.pop("address_data", None)
        serializer.instance = services.create_contact(self._client(), address=address, **data)


@extend_schema(tags=["contacts"])
class ContactViewSet(PeopleViewSet):
    """All contacts (search, edit, archive). Create through ``/clients/{id}/contacts``."""

    model = Contact
    serializer_class = ContactSerializer
    entity, entity_type = "contact", "people.contact"
    search_fields = ("first_name", "last_name", "email", "phone", "mobile")
    permission_classes = [IsAuthenticated, HasOrganisation, perms("contact")]
    http_method_names = ["get", "patch", "delete", "head", "options"]
    filterset_fields: list[str] = []
    ordering_fields = ("last_name", "first_name", "created_at")

    def get_tenant_queryset(self) -> QuerySet[Contact]:
        return self.scoped(Contact.objects.select_related("address", "client"))

    @extend_schema(parameters=[*LIST_PARAMS, ORDERING_PARAM])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        parameters=[*LIST_PARAMS, *EXPORT_PARAMS, ORDERING_PARAM], responses=EXPORT_RESPONSES
    )
    @action(
        detail=False,
        methods=["get"],
        permission_classes=[
            IsAuthenticated,
            HasOrganisation,
            HasMethodPermission.for_({"GET": "people.contact.export"}),
        ],
    )
    def export(self, request: Request) -> Any:
        from tutortrack.core.permissions import has_perm

        details = has_perm(request.user, "people.contact.view_details")
        phone = has_perm(request.user, "people.contact.view_phone")
        return self.export_file(
            request,
            [
                ("id", lambda c: c.pk),
                ("first_name", lambda c: c.first_name),
                ("last_name", lambda c: c.last_name),
                ("relationship", lambda c: c.relationship),
                ("client", lambda c: c.client.display_name),
                ("email", lambda c: c.email if details else ""),
                ("phone", lambda c: (c.phone or c.mobile) if phone else ""),
                ("is_primary", lambda c: "yes" if c.is_primary else "no"),
            ],
            "contacts",
        )

    def perform_update(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        data.update(_pop_address(data, "address"))
        serializer.instance = services.update_contact(serializer.instance, **data)

    def perform_destroy(self, instance: Contact) -> None:
        from tutortrack.core.time import now

        with audit.track(instance, action="archive"):
            instance.archived_at = now()
            instance.save(update_fields=["archived_at", "updated_at"])


class StudentFilter(ComputedFilterSet):
    status = filters.MultipleChoiceFilter(choices=Student.Status.choices)
    client = filters.UUIDFilter(field_name="client_id")
    branch = filters.UUIDFilter(field_name="branch_id")
    subject = filters.CharFilter(method="by_subject")
    next_lesson_before = _computed("datetime", "next_lesson_before")
    last_lesson_before = _computed("datetime", "last_lesson_before")
    last_lesson_after = _computed("datetime", "last_lesson_after")
    hours_this_term_min = _computed("number", "hours_this_term_min")
    has_upcoming_lesson = filters.BooleanFilter(method="upcoming")

    class Meta:
        model = Student
        fields: list[str] = []

    def by_subject(self, qs: QuerySet[Student], name: str, value: str) -> QuerySet[Student]:
        return qs.filter(subjects__contains=[{"subject": value}])


@extend_schema(tags=["students"])
class StudentViewSet(PeopleViewSet):
    """Students. ``DELETE`` archives; ``status`` changes the lifecycle status."""

    model = Student
    serializer_class = StudentSerializer
    entity, entity_type = "student", "people.student"
    search_fields = ("first_name", "last_name", "preferred_name", "school")
    permission_classes = [IsAuthenticated, HasOrganisation, perms("student")]
    filterset_class = StudentFilter
    ordering_fields = (
        "last_name",
        "first_name",
        "created_at",
        "next_lesson_at",
        "last_lesson_at",
        "hours_this_term",
    )

    def get_tenant_queryset(self) -> QuerySet[Student]:
        qs = self.scoped(Student.objects.select_related("lesson_address", "client"))
        if self.action in {"list", "retrieve", "export"}:
            qs = selectors.with_student_figures(self.request.user, qs)
        return qs

    @extend_schema(parameters=[*LIST_PARAMS, ORDERING_PARAM])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response = super().retrieve(request, *args, **kwargs)
        if response.data.get("learning_needs") or response.data.get("date_of_birth"):
            audit.record_read(self.get_object(), "sensitive student data")  # FR-29-2
        return response

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        client = data.pop("client")
        if not scope_queryset(
            self.request.user, Client.objects.filter(pk=client.pk), "people.client.view"
        ).exists():
            from rest_framework.exceptions import NotFound

            raise NotFound()
        address = data.pop("lesson_address_data", None)
        serializer.instance = services.create_student(client, lesson_address=address, **data)

    def perform_update(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        data.update(_pop_address(data, "lesson_address"))
        serializer.instance = services.update_student(serializer.instance, **data)

    def perform_destroy(self, instance: Student) -> None:
        services.change_student_status(instance, Student.Status.ARCHIVED)

    @extend_schema(request=StatusSerializer, responses=StudentSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="status",
        permission_classes=[
            IsAuthenticated,
            HasOrganisation,
            HasMethodPermission.for_({"POST": "people.student.edit"}),
        ],
    )
    def change_status(self, request: Request, pk: Any = None) -> Response:
        payload = StatusSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        student = services.change_student_status(
            self.get_object(), payload.validated_data["status"]
        )
        return Response(StudentSerializer(student, context={"request": request}).data)

    @extend_schema(
        parameters=[*LIST_PARAMS, *EXPORT_PARAMS, ORDERING_PARAM], responses=EXPORT_RESPONSES
    )
    @action(
        detail=False,
        methods=["get"],
        permission_classes=[
            IsAuthenticated,
            HasOrganisation,
            HasMethodPermission.for_({"GET": "people.student.export"}),
        ],
    )
    def export(self, request: Request) -> Any:
        return self.export_file(
            request,
            [
                ("id", lambda s: s.pk),
                ("first_name", lambda s: s.first_name),
                ("last_name", lambda s: s.last_name),
                ("status", lambda s: s.status),
                ("year_group", lambda s: s.year_group),
                ("client", lambda s: s.client.display_name),
                (
                    "subjects",
                    lambda s: "; ".join(
                        f"{x['subject']} {x.get('level', '')}".strip() for x in s.subjects
                    ),
                ),
                ("next_lesson_at", lambda s: _iso(getattr(s, "next_lesson_at", None))),
                ("last_lesson_at", lambda s: _iso(getattr(s, "last_lesson_at", None))),
                ("hours_this_term", lambda s: getattr(s, "hours_this_term", None)),
            ],
            "students",
        )


class TutorFilter(ComputedFilterSet):
    status = filters.MultipleChoiceFilter(choices=TutorProfile.Status.choices)
    branch = filters.UUIDFilter(field_name="branches")
    subject = filters.CharFilter(field_name="subjects__subject", lookup_expr="iexact")
    hours_this_month_min = _computed("number", "hours_this_month_min")
    report_sla_below = _computed("number", "report_sla_below")

    class Meta:
        model = TutorProfile
        fields: list[str] = []


@extend_schema(tags=["tutors"])
class TutorViewSet(PeopleViewSet):
    """Tutors. Creating one invites them to join (role Tutor) unless ``invite`` is false."""

    model = TutorProfile
    serializer_class = TutorSerializer
    entity, entity_type = "tutor", "people.tutor"
    search_fields = ("first_name", "last_name", "display_name", "email", "phone")
    permission_classes = [IsAuthenticated, HasOrganisation, perms("tutor")]
    filterset_class = TutorFilter
    http_method_names = ["get", "post", "patch", "put", "delete", "head", "options"]
    ordering_fields = ("last_name", "first_name", "created_at", "hours_this_month", "report_sla")

    def get_tenant_queryset(self) -> QuerySet[TutorProfile]:
        qs = TutorProfile.objects.select_related("address").prefetch_related(
            "subjects", "qualifications"
        )
        qs = self.scoped(qs)
        if self.action in {"list", "retrieve", "export"}:
            qs = selectors.with_tutor_figures(self.request.user, qs)
        return qs.distinct()

    def _with_utilisation(self, tutors: list[TutorProfile]) -> list[TutorProfile]:
        """Utilisation needs weekly availability, so it is worked out per page (it can't be
        sorted or filtered on)."""
        if has_perm(self.request.user, "scheduling.lesson.view"):
            figures = selectors.tutor_utilisation(tutors)
            for tutor in tutors:
                tutor.utilisation = figures.get(str(tutor.pk))  # type: ignore[attr-defined]
        return tutors

    def paginate_queryset(self, queryset: Any) -> Any:
        page = super().paginate_queryset(queryset)
        return self._with_utilisation(list(page)) if page is not None else None

    def get_object(self) -> TutorProfile:
        tutor: TutorProfile = super().get_object()
        if self.action == "retrieve":
            self._with_utilisation([tutor])
        return tutor

    @extend_schema(parameters=[*LIST_PARAMS, ORDERING_PARAM])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        parameters=[*LIST_PARAMS, *EXPORT_PARAMS, ORDERING_PARAM], responses=EXPORT_RESPONSES
    )
    @action(
        detail=False,
        methods=["get"],
        permission_classes=[
            IsAuthenticated,
            HasOrganisation,
            HasMethodPermission.for_({"GET": "people.tutor.export"}),
        ],
    )
    def export(self, request: Request) -> Any:
        return self.export_file(
            request,
            [
                ("id", lambda t: t.pk),
                ("name", lambda t: t.full_name),
                ("email", lambda t: t.email),
                ("status", lambda t: t.status),
                ("subjects", lambda t: "; ".join(sorted({s.subject for s in t.subjects.all()}))),
                ("hours_this_month", lambda t: getattr(t, "hours_this_month", None)),
                ("report_sla_percent", lambda t: getattr(t, "report_sla", None)),
            ],
            "tutors",
        )

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        address = data.pop("address_data", None)
        branches = data.pop("branches", [])
        serializer.instance = services.create_tutor(address=address, branches=branches, **data)

    @extend_schema(
        request=None,
        responses=TutorSerializer,
        description=(
            "Add the signed-in person as a tutor (a sole trader, or an owner who teaches): an "
            "active tutor record on their own login, with no invitation. Idempotent: returns "
            "their existing tutor record if they have one."
        ),
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="add-me",
        permission_classes=[
            IsAuthenticated,
            HasOrganisation,
            HasMethodPermission.for_({"POST": "people.tutor.create"}),
        ],
    )
    def add_me(self, request: Request) -> Response:
        membership = getattr(request, "membership", None)
        if membership is None:
            from tutortrack.core.exceptions import PermissionDenied

            raise PermissionDenied(_("Only members of this organisation can be its tutors."))
        tutor = services.add_self_as_tutor(membership)
        return Response(TutorSerializer(tutor, context={"request": request}).data)

    def perform_update(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        data.pop("invite", None)
        data.pop("email", None)  # changing a tutor's login email belongs to the user
        data.update(_pop_address(data, "address"))
        serializer.instance = services.update_tutor(serializer.instance, **data)

    def perform_destroy(self, instance: TutorProfile) -> None:
        services.change_tutor_status(instance, TutorProfile.Status.ARCHIVED)

    @extend_schema(request=StatusSerializer, responses=TutorSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="status",
        permission_classes=[
            IsAuthenticated,
            HasOrganisation,
            HasMethodPermission.for_({"POST": "people.tutor.edit"}),
        ],
    )
    def change_status(self, request: Request, pk: Any = None) -> Response:
        payload = StatusSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tutor = services.change_tutor_status(self.get_object(), payload.validated_data["status"])
        return Response(TutorSerializer(tutor, context={"request": request}).data)

    @extend_schema(request=SubjectInput(many=True), responses=TutorSubjectSerializer(many=True))
    @action(
        detail=True,
        methods=["put"],
        url_path="subjects",
        permission_classes=[
            IsAuthenticated,
            HasOrganisation,
            HasMethodPermission.for_({"PUT": "people.tutor.edit"}),
        ],
    )
    def set_subjects(self, request: Request, pk: Any = None) -> Response:
        payload = SubjectInput(data=request.data, many=True)
        payload.is_valid(raise_exception=True)
        subjects = services.set_tutor_subjects(
            self.get_object(), [dict(s) for s in payload.validated_data]
        )
        return Response(TutorSubjectSerializer(subjects, many=True).data)

    @extend_schema(
        request=None,
        responses=TutorSubjectSerializer,
        parameters=[OpenApiParameter("subject_id", OpenApiTypes.UUID, OpenApiParameter.PATH)],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"subjects/(?P<subject_id>[^/.]+)/approve",
        permission_classes=[
            IsAuthenticated,
            HasOrganisation,
            HasMethodPermission.for_({"POST": "people.tutor.approve_subjects"}),
        ],
    )
    def approve_subject(self, request: Request, pk: Any = None, subject_id: str = "") -> Response:
        subject = get_object_or_404(
            TutorSubject.objects.filter(tutor=self.get_object()), pk=subject_id
        )
        return Response(
            TutorSubjectSerializer(services.approve_subject(subject, request.user)).data
        )


class DuplicatesView(APIView):
    """Possible duplicates before creating a record (FR-05-13): same email or phone, or same
    name and date of birth."""

    permission_classes = [
        IsAuthenticated,
        HasOrganisation,
        HasMethodPermission.for_({"GET": "people.client.create"}),
    ]

    @extend_schema(
        parameters=[
            OpenApiParameter(n, str)
            for n in ("email", "phone", "first_name", "last_name", "date_of_birth")
        ],
        responses=DuplicateSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        p = request.query_params
        rows = selectors.possible_duplicates(
            email=p.get("email", ""),
            phone=p.get("phone", ""),
            first_name=p.get("first_name", ""),
            last_name=p.get("last_name", ""),
            date_of_birth=p.get("date_of_birth", ""),
        )
        return Response(DuplicateSerializer(rows, many=True).data)


class PeopleMapView(APIView):
    """``/people/map``: geocoded students and tutors for in-person matching (FR-05-11, E05-T12).
    Points are rounded to about 100 m; the response holds no street addresses."""

    permission_classes = [IsAuthenticated, HasOrganisation]

    @extend_schema(
        parameters=[
            OpenApiParameter("kind", str, enum=["all", "student", "tutor"]),
            OpenApiParameter("status", str),
            OpenApiParameter("branch", OpenApiTypes.UUID),
            OpenApiParameter("subject", str),
        ],
        responses=PeopleMapSerializer,
        examples=[
            OpenApiExample(
                "Two people",
                response_only=True,
                value={
                    "points": [
                        {
                            "kind": "student",
                            "id": "01928d6e-0000-7000-8000-000000000001",
                            "name": "Arjun Patel",
                            "status": "active",
                            "area": "SW11",
                            "lat": 51.464,
                            "lng": -0.163,
                            "subjects": ["Maths"],
                            "travel_radius_km": None,
                        },
                        {
                            "kind": "tutor",
                            "id": "01928d6e-0000-7000-8000-000000000002",
                            "name": "Nia Clarke",
                            "status": "active",
                            "area": "SW4",
                            "lat": 51.462,
                            "lng": -0.138,
                            "subjects": ["Maths", "Physics"],
                            "travel_radius_km": 5,
                        },
                    ],
                    "missing": {"student": 3, "tutor": 0},
                },
            )
        ],
    )
    def get(self, request: Request) -> Response:
        if not (
            has_perm(request.user, "people.student.view")
            or has_perm(request.user, "people.tutor.view")
        ):
            from tutortrack.core.exceptions import PermissionDenied

            raise PermissionDenied()
        q = request.query_params
        kind = q.get("kind", "all")
        kinds = selectors.MAP_KINDS if kind in ("", "all") else (kind,)
        data = selectors.map_points(
            request.user,
            kinds=kinds,
            status=q.get("status", ""),
            branch=q.get("branch", ""),
            subject=q.get("subject", ""),
        )
        return Response(PeopleMapSerializer(data).data)


class PeopleMapGeocodeView(APIView):
    """``POST /people/map/geocode``: geocode the people the map can't place yet."""

    permission_classes = [IsAuthenticated, HasOrganisation]

    @extend_schema(
        request=GeocodeRequestSerializer,
        responses=GeocodeResultSerializer,
        examples=[OpenApiExample("Queued", response_only=True, value={"queued": 4})],
    )
    def post(self, request: Request) -> Response:
        payload = GeocodeRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        kinds = payload.validated_data["kinds"]
        if not any(has_perm(request.user, f"people.{k}.edit") for k in kinds):
            from tutortrack.core.exceptions import PermissionDenied

            raise PermissionDenied()
        return Response({"queued": services.geocode_missing(request.user, kinds)})


# --- duplicates and merge (FR-05-13) ------------------------------------------------------------

MERGE_PERMS: list[Any] = [
    IsAuthenticated,
    HasOrganisation,
    HasMethodPermission.for_({"GET": "people.merge", "POST": "people.merge"}),
]
ENTITY_PARAM = OpenApiParameter(
    "entity", str, OpenApiParameter.PATH, enum=sorted(selectors.MERGE_ENTITIES)
)


def _merge_subject(entity: str) -> str:
    from rest_framework.exceptions import NotFound

    subject_type = selectors.MERGE_ENTITIES.get(entity)
    if subject_type is None:
        raise NotFound()
    return subject_type


def _visible_pair(request: Request, subject_type: str, ids: list[Any]) -> None:
    """Both records must be ones the user can see (a hidden id is a 404)."""
    from django.apps import apps
    from django.core.exceptions import ValidationError
    from rest_framework.exceptions import NotFound

    model = apps.get_model(subject_type)
    perm = f"people.{subject_type.split('.')[1]}.view"
    try:
        found = scope_queryset(
            request.user, model._default_manager.filter(pk__in=ids), perm
        ).count()
    except (ValidationError, ValueError):
        found = 0
    if found != len(set(map(str, ids))):
        raise NotFound()


PREVIEW_EXAMPLE = {
    "subject_type": "people.client",
    "source": {"id": "01928d6e-0000-7000-8000-000000000002", "name": "Patel family"},
    "target": {"id": "01928d6e-0000-7000-8000-000000000001", "name": "The Patel Family"},
    "values": [
        {
            "name": "display_name",
            "label": "Name",
            "source": "Patel family",
            "target": "The Patel Family",
            "hidden": False,
            "same": False,
            "default": "target",
        }
    ],
    "moves": [
        {"key": "people.students", "label": "Students", "count": 1},
        {"key": "billing.invoices", "label": "Invoices", "count": 2},
    ],
    "problems": [],
    "warnings": [],
    "can_merge": True,
}


class MergePreviewView(APIView):
    """``GET /merge/{entity}/preview?source=&target=``: the two records side by side, what
    would move to the survivor and anything that stops the merge (FR-05-13)."""

    permission_classes = MERGE_PERMS

    @extend_schema(
        tags=["merge"],
        parameters=[
            ENTITY_PARAM,
            OpenApiParameter("source", OpenApiTypes.UUID, required=True),
            OpenApiParameter("target", OpenApiTypes.UUID, required=True),
        ],
        responses=MergePreviewSerializer,
        examples=[OpenApiExample("Two Patel families", response_only=True, value=PREVIEW_EXAMPLE)],
    )
    def get(self, request: Request, entity: str) -> Response:
        subject_type = _merge_subject(entity)
        source = request.query_params.get("source", "")
        target = request.query_params.get("target", "")
        _visible_pair(request, subject_type, [source, target])
        data = selectors.merge_preview(request.user, subject_type, source, target)
        return Response(MergePreviewSerializer(data).data)


class MergeView(APIView):
    """``POST /merge/{entity}``: merge ``source`` into ``target`` (FR-05-13). Not reversible:
    ``confirm`` must be true. ``choices`` picks the surviving value per field
    (``source`` or ``target``; by default the survivor's, or the duplicate's where the
    survivor's is empty). Every linked record moves to the survivor; the duplicate is
    archived and points at it."""

    permission_classes = MERGE_PERMS

    @extend_schema(
        tags=["merge"],
        parameters=[ENTITY_PARAM],
        request=MergeRequestSerializer,
        responses={200: MergeResultSerializer},
        examples=[
            OpenApiExample(
                "Keep the older family, the newer one's address",
                request_only=True,
                value={
                    "source": "01928d6e-0000-7000-8000-000000000002",
                    "target": "01928d6e-0000-7000-8000-000000000001",
                    "choices": {"billing_address": "source"},
                    "confirm": True,
                },
            ),
            OpenApiExample(
                "Merged",
                response_only=True,
                value={
                    "subject_type": "people.client",
                    "target_id": "01928d6e-0000-7000-8000-000000000001",
                    "merged_id": "01928d6e-0000-7000-8000-000000000002",
                    "moved": {"people.students": 1, "billing.invoices": 2},
                    "notes": [],
                },
            ),
        ],
    )
    def post(self, request: Request, entity: str) -> Response:
        subject_type = _merge_subject(entity)
        payload = MergeRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        _visible_pair(request, subject_type, [data["source"], data["target"]])
        result = services.merge_records(
            subject_type,
            data["source"],
            data["target"],
            choices=data.get("choices") or {},
            confirm=data["confirm"],
            user=request.user,
        )
        return Response(MergeResultSerializer(result).data)


class DuplicatePairsView(APIView):
    """``GET /people/duplicates/pairs?type=client|contact|student``: records that look like
    the same person or family, newest pairs first (FR-05-13), to review and merge."""

    permission_classes = MERGE_PERMS

    @extend_schema(
        tags=["merge"],
        parameters=[
            OpenApiParameter("type", str, enum=["client", "contact", "student"], required=True)
        ],
        responses=DuplicatePairSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        rows = selectors.duplicate_pairs(request.user, request.query_params.get("type", ""))
        return Response(DuplicatePairSerializer(rows, many=True).data)
