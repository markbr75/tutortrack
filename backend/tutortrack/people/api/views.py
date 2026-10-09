"""People API (E05 §4)."""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, QuerySet
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
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
from tutortrack.crm.listing import apply_crm_filters, csv_export

from .. import selectors, services
from ..models import Client, Contact, Student, TutorProfile, TutorSubject
from .serializers import (
    ClientDetailSerializer,
    ClientSerializer,
    ContactSerializer,
    DuplicateSerializer,
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


def _pop_address(data: dict[str, Any], key: str) -> dict[str, Any]:
    out = {}
    if f"{key}_data" in data:
        out[key] = data.pop(f"{key}_data")
    return out


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
    entity: str = ""
    entity_type: str = ""
    search_fields: tuple[str, ...] = ()

    def scoped(self, qs: QuerySet[Any]) -> QuerySet[Any]:
        qs = scope_queryset(self.request.user, qs, f"people.{self.entity}.view")
        if self.action == "list":
            qs = apply_crm_filters(qs, self.request.query_params, self.entity_type)
            q = self.request.query_params.get("q", "").strip()
            if q:
                condition = Q()
                for field in self.search_fields:
                    condition |= Q(**{f"{field}__icontains": q})
                qs = qs.filter(condition)
        return qs


class ClientFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=Client.Status.choices)
    type = filters.ChoiceFilter(choices=Client.Type.choices)
    branch = filters.UUIDFilter(field_name="branch_id")
    account_manager = filters.UUIDFilter(field_name="account_manager_id")

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

    def get_serializer_class(self) -> Any:
        return ClientDetailSerializer if self.action == "retrieve" else ClientSerializer

    def get_tenant_queryset(self) -> QuerySet[Client]:
        qs = Client.objects.select_related("billing_address").annotate(
            students_count=Count("students", filter=Q(students__archived_at__isnull=True))
        )
        return self.scoped(qs).distinct()

    @extend_schema(parameters=LIST_PARAMS)
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

    @extend_schema(parameters=LIST_PARAMS, responses={(200, "text/csv"): OpenApiTypes.STR})
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
        rows = self.filter_queryset(self.get_queryset())
        return csv_export(
            request,
            rows,
            [
                ("id", lambda c: c.pk),
                ("name", lambda c: c.display_name),
                ("type", lambda c: c.type),
                ("status", lambda c: c.status),
                ("currency", lambda c: c.currency),
                ("students", lambda c: c.students_count),
                ("created_at", lambda c: c.created_at.isoformat()),
            ],
            filename="clients.csv",
            entity_type=self.entity_type,
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

    def get_tenant_queryset(self) -> QuerySet[Contact]:
        return self.scoped(Contact.objects.select_related("address", "client"))

    @extend_schema(parameters=LIST_PARAMS)
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def perform_update(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        data.update(_pop_address(data, "address"))
        serializer.instance = services.update_contact(serializer.instance, **data)

    def perform_destroy(self, instance: Contact) -> None:
        from tutortrack.core.time import now

        with audit.track(instance, action="archive"):
            instance.archived_at = now()
            instance.save(update_fields=["archived_at", "updated_at"])


class StudentFilter(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=Student.Status.choices)
    client = filters.UUIDFilter(field_name="client_id")
    branch = filters.UUIDFilter(field_name="branch_id")
    subject = filters.CharFilter(method="by_subject")

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

    def get_tenant_queryset(self) -> QuerySet[Student]:
        return self.scoped(Student.objects.select_related("lesson_address", "client"))

    @extend_schema(parameters=LIST_PARAMS)
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

    @extend_schema(parameters=LIST_PARAMS, responses={(200, "text/csv"): OpenApiTypes.STR})
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
        rows = self.filter_queryset(self.get_queryset())
        return csv_export(
            request,
            rows,
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
            ],
            filename="students.csv",
            entity_type=self.entity_type,
        )


class TutorFilter(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=TutorProfile.Status.choices)
    branch = filters.UUIDFilter(field_name="branches")
    subject = filters.CharFilter(field_name="subjects__subject", lookup_expr="iexact")

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

    def get_tenant_queryset(self) -> QuerySet[TutorProfile]:
        qs = TutorProfile.objects.select_related("address").prefetch_related(
            "subjects", "qualifications"
        )
        return self.scoped(qs).distinct()

    @extend_schema(parameters=LIST_PARAMS)
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        address = data.pop("address_data", None)
        branches = data.pop("branches", [])
        serializer.instance = services.create_tutor(address=address, branches=branches, **data)

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
