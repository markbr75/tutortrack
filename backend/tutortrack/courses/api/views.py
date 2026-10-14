"""Courses API (E20 §4): terms, courses, classes (+ roster, sessions, register, waitlist),
enrolments (+ transfer, withdraw, quote) and term rollover."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation

from .. import selectors, services
from ..models import (
    AcademicYear,
    ClassSession,
    Course,
    Enrolment,
    GroupClass,
    MakeupBooking,
    Term,
    TermRollover,
)
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]
VIEW, MANAGE = "courses.view", "courses.manage"


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


MANAGED = {"GET": VIEW, "POST": MANAGE, "PATCH": MANAGE, "PUT": MANAGE, "DELETE": MANAGE}


# --- academic years and terms (T01) -------------------------------------------------------------


class AcademicYearViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = AcademicYear
    serializer_class = s.AcademicYearSerializer
    permission_classes = perms(MANAGED)
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[AcademicYear]:
        from tutortrack.core.permissions import scope_queryset

        return scope_queryset(self.request.user, AcademicYear.objects.all(), VIEW)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.save_academic_year(None, **serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_academic_year(
            serializer.instance, **serializer.validated_data
        )

    def perform_destroy(self, instance: AcademicYear) -> None:
        services.delete_academic_year(instance)


class TermFilter(filters.FilterSet):
    academic_year = filters.UUIDFilter()
    branch = filters.UUIDFilter()

    class Meta:
        model = Term
        fields: list[str] = []


class TermViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """Terms with their breaks (half term). Breaks are skipped by class sessions and left
    out of proration; termly billing plans follow term dates."""

    model = Term
    serializer_class = s.TermSerializer
    filterset_class = TermFilter
    permission_classes = perms(MANAGED)
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[Term]:
        return selectors.terms(self.request.user).prefetch_related("breaks")

    def _save(self, serializer: Any, term: Term | None) -> None:
        data = dict(serializer.validated_data)
        breaks = data.pop("breaks", None)
        serializer.instance = services.save_term(
            term, breaks=[dict(b) for b in breaks] if breaks is not None else None, **data
        )

    def perform_create(self, serializer: Any) -> None:
        self._save(serializer, None)

    def perform_update(self, serializer: Any) -> None:
        self._save(serializer, serializer.instance)

    def perform_destroy(self, instance: Term) -> None:
        services.delete_term(instance)


# --- courses (T02) ------------------------------------------------------------------------------


class CourseFilter(filters.FilterSet):
    archived = filters.BooleanFilter(field_name="archived_at", lookup_expr="isnull", exclude=True)
    is_public = filters.BooleanFilter()
    pricing_model = filters.ChoiceFilter(choices=Course.PricingModel.choices)

    class Meta:
        model = Course
        fields: list[str] = []


class CourseViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = Course
    serializer_class = s.CourseSerializer
    filterset_class = CourseFilter
    permission_classes = perms(MANAGED)
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[Course]:
        return selectors.courses(self.request.user).select_related("service", "subject")

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.save_course(None, **serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_course(serializer.instance, **serializer.validated_data)

    @extend_schema(request=s.ArchiveSerializer, responses=s.CourseSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request: Request, pk: Any = None) -> Response:
        payload = s.ArchiveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        course = services.set_course_archived(self.get_object(), payload.validated_data["archived"])
        return Response(self.get_serializer(course).data)


# --- classes (T02, T06, T07) --------------------------------------------------------------------


class ClassFilter(filters.FilterSet):
    course = filters.UUIDFilter()
    term = filters.UUIDFilter()
    status = filters.MultipleChoiceFilter(choices=GroupClass.Status.choices)

    class Meta:
        model = GroupClass
        fields: list[str] = []


class GroupClassViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Classes: scheduled cohorts of a course in a term. Each runs on an E08 lesson series;
    its roster (enrolments and makeups) decides every future session's attendees."""

    model = GroupClass
    serializer_class = s.GroupClassSerializer
    filterset_class = ClassFilter
    permission_classes = perms(MANAGED)
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[GroupClass]:
        return selectors.classes(self.request.user).prefetch_related("teachers__tutor")

    @extend_schema(request=s.GroupClassCreateSerializer, responses={201: s.ClassCreatedSerializer})
    def create(self, request: Request) -> Response:
        """Create a class and its sessions. ``skipped_dates`` lists sessions not created
        because a teacher or the room was busy (``conflict_mode=skip``)."""
        payload = s.GroupClassCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        teachers = [dict(t) for t in data.pop("teachers", [])]
        group_class, skipped = services.create_class(teachers=teachers, user=request.user, **data)
        body = {"group_class": group_class, "skipped_dates": skipped}
        return Response(
            s.ClassCreatedSerializer(body, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=s.GroupClassUpdateSerializer, responses=s.GroupClassSerializer)
    def partial_update(self, request: Request, pk: Any = None) -> Response:
        payload = s.GroupClassUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        if "teachers" in data:
            data["teachers"] = [dict(t) for t in data["teachers"]]
        group_class = services.update_class(self.get_object(), user=request.user, **data)
        return Response(self.get_serializer(group_class).data)

    @extend_schema(request=None, responses=s.GroupClassSerializer)
    @action(detail=True, methods=["post"])
    def open(self, request: Request, pk: Any = None) -> Response:
        """Open a draft class for enrolment (portal and website)."""
        group_class = services.open_class(self.get_object(), user=request.user)
        return Response(self.get_serializer(group_class).data)

    @extend_schema(request=s.ClassCancelSerializer, responses=s.GroupClassSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        """Cancel the class: future sessions are cancelled and students withdrawn with
        unused sessions credited."""
        payload = s.ClassCancelSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        group_class = services.cancel_class(
            self.get_object(), reason=payload.validated_data["reason"], user=request.user
        )
        return Response(self.get_serializer(group_class).data)

    @extend_schema(responses=s.RosterRowSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def roster(self, request: Request, pk: Any = None) -> Response:
        """Current and past students of the class."""
        group_class = self.get_object()
        rows = [
            {
                "enrolment": e.pk,
                "student": e.student_id,
                "student_name": e.student.full_name,
                "client": e.client_id,
                "client_name": e.client.display_name,
                "status": e.status,
                "start_date": e.start_date,
                "end_date": e.end_date,
                "joined_via": e.source,
            }
            for e in group_class.enrolments.select_related("student", "client").order_by(
                "student__first_name", "-created_at"
            )
        ]
        return Response(s.RosterRowSerializer(rows, many=True).data)

    @extend_schema(responses=s.ClassSessionSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def sessions(self, request: Request, pk: Any = None) -> Response:
        group_class = self.get_object()
        qs = group_class.sessions.select_related("lesson", "group_class__course").order_by("date")
        return Response(s.ClassSessionSerializer(qs, many=True).data)

    @extend_schema(request=s.JoinWaitlistSerializer, responses=s.WaitlistRowSerializer(many=True))
    @action(
        detail=True,
        methods=["get", "post"],
        pagination_class=None,
        permission_classes=perms({"GET": VIEW, "POST": "courses.enrolment.manage"}),
    )
    def waitlist(self, request: Request, pk: Any = None) -> Response:
        """The class waitlist in order (positions for those waiting); POST adds a student."""
        from tutortrack.leads import services as leads

        group_class = self.get_object()
        if request.method == "POST":
            payload = s.JoinWaitlistSerializer(data=request.data)
            payload.is_valid(raise_exception=True)
            services.join_waitlist(group_class, **payload.validated_data)
        rows = [
            {
                "id": e.pk,
                "student": e.student_id,
                "student_name": e.student.full_name,
                "status": e.status,
                "position": leads.position(e) if e.status == "waiting" else None,
                "offer_expires_at": e.offer_expires_at,
                "created_at": e.created_at,
            }
            for e in selectors.waiting(group_class)
        ]
        code = status.HTTP_201_CREATED if request.method == "POST" else status.HTTP_200_OK
        return Response(s.WaitlistRowSerializer(rows, many=True).data, status=code)


class SessionViewSet(TenantScopedViewMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Class sessions: the register and makeup bookings (FR-20-6)."""

    model = ClassSession
    serializer_class = s.ClassSessionSerializer
    permission_classes = perms({"GET": VIEW, "POST": "courses.register.mark"})
    http_method_names = ["get", "post", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[ClassSession]:
        return selectors.sessions(self.request.user)

    def _register(self, session: ClassSession) -> dict[str, Any]:
        lesson = session.lesson
        makeups = {str(m.student_id) for m in selectors.makeups_for(session)}
        reasons = session.absence_reasons or {}
        rows = [
            {
                "student": a.student_id,
                "student_name": a.student.full_name,
                "outcome": a.outcome or "present",
                "late_minutes": a.late_minutes,
                "absence_reason": reasons.get(str(a.student_id), ""),
                "makeup": str(a.student_id) in makeups,
            }
            for a in lesson.attendees.select_related("student").order_by("student__first_name")
        ]
        return {"session": session.pk, "lesson_status": lesson.status, "rows": rows}

    @extend_schema(methods=["GET"], responses=s.RegisterSerializer)
    @extend_schema(
        methods=["POST"], request=s.RegisterInputSerializer, responses=s.RegisterSerializer
    )
    @action(detail=True, methods=["get", "post"], pagination_class=None)
    def register(self, request: Request, pk: Any = None) -> Response:
        """The class register: GET the students (makeups marked); POST everyone's outcome
        at once (completes the session, or corrects attendance after completion)."""
        session = self.get_object()
        if request.method == "POST":
            markable = selectors.sessions(request.user, "courses.register.mark")
            if not markable.filter(pk=session.pk).exists():
                raise PermissionDenied()
            payload = s.RegisterInputSerializer(data=request.data)
            payload.is_valid(raise_exception=True)
            rows = [dict(r) for r in payload.validated_data["rows"]]
            session = services.mark_register(session, rows, user=request.user)
            session.lesson.refresh_from_db()
        return Response(s.RegisterSerializer(self._register(session)).data)

    @extend_schema(request=s.MakeupCreateSerializer, responses={201: s.MakeupBookingSerializer})
    @action(detail=True, methods=["post"])
    def makeups(self, request: Request, pk: Any = None) -> Response:
        """Book a makeup in this session for a student of another class of the course."""
        from tutortrack.delivery.models import MakeupCredit

        session = self.get_object()
        payload = s.MakeupCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        credit = (
            get_object_or_404(MakeupCredit, pk=data["makeup_credit"])
            if data.get("makeup_credit")
            else None
        )
        booking = services.book_makeup(
            session,
            data["student"],
            credit=credit,
            from_session=data.get("from_session"),
            user=request.user,
        )
        return Response(s.MakeupBookingSerializer(booking).data, status=status.HTTP_201_CREATED)


class MakeupViewSet(TenantScopedViewMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    model = MakeupBooking
    serializer_class = s.MakeupBookingSerializer
    permission_classes = perms({"GET": VIEW, "POST": "courses.register.mark"})
    http_method_names = ["get", "post", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[MakeupBooking]:
        visible = selectors.sessions(self.request.user)
        return MakeupBooking.objects.filter(session__in=visible.values("pk"))

    @extend_schema(request=None, responses=s.MakeupBookingSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        booking = services.cancel_makeup(self.get_object(), user=request.user)
        return Response(self.get_serializer(booking).data)


# --- enrolments (T03, T05) ----------------------------------------------------------------------


class EnrolmentFilter(filters.FilterSet):
    group_class = filters.UUIDFilter()
    student = filters.UUIDFilter()
    client = filters.UUIDFilter()
    term = filters.UUIDFilter(field_name="group_class__term")
    status = filters.MultipleChoiceFilter(choices=Enrolment.Status.choices)

    class Meta:
        model = Enrolment
        fields: list[str] = []


class EnrolmentViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Enrolments (FR-20-4): a student's place in a class. POST accepts an
    ``Idempotency-Key`` (it bills fees)."""

    model = Enrolment
    serializer_class = s.EnrolmentSerializer
    filterset_class = EnrolmentFilter
    permission_classes = perms({"GET": VIEW, "POST": "courses.enrolment.manage"})
    http_method_names = ["get", "post", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[Enrolment]:
        return selectors.enrolments(self.request.user)

    @extend_schema(
        request=s.EnrolmentCreateSerializer, responses={201: s.EnrolmentCreatedSerializer}
    )
    def create(self, request: Request) -> Response:
        """Enrol a student. Mid-term joiners are added to future sessions only and their
        fee is prorated (setting); ``override_capacity``/``skip_eligibility`` for staff."""
        payload = s.EnrolmentCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        enrolment = services.enrol(
            data["group_class"],
            data["student"],
            start_date=data.get("start_date"),
            trial=data["trial"],
            override_capacity=data["override_capacity"],
            check_eligibility=not data["skip_eligibility"],
            user=request.user,
        )
        return Response(
            s.EnrolmentCreatedSerializer(enrolment).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=s.QuoteInputSerializer, responses=s.QuoteSerializer)
    @action(detail=False, methods=["post"], permission_classes=perms({"POST": VIEW}))
    def quote(self, request: Request) -> Response:
        """What a place costs now: discounts, proration and what is due at enrolment."""
        payload = s.QuoteInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        student = data.get("student")
        body = services.quote(
            data["group_class"], student=student, start_date=data.get("start_date"),
            trial=data["trial"],
        )  # fmt: skip
        body["problems"] = (
            services.eligibility_problems(
                data["group_class"],
                date_of_birth=student.date_of_birth,
                year_group=student.year_group,
            )
            if student is not None
            else []
        )
        return Response(s.QuoteSerializer(body).data)

    @extend_schema(request=s.WithdrawSerializer, responses=s.EnrolmentSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request: Request, pk: Any = None) -> Response:
        """Withdraw from ``effective_date`` (their first day away). Unused sessions are
        credited by the refund setting (``refund`` overrides it)."""
        payload = s.WithdrawSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        enrolment = services.withdraw(
            self.get_object(),
            effective=data.get("effective_date"),
            reason=data["reason"],
            refund=data.get("refund"),
            user=request.user,
        )
        return Response(self.get_serializer(enrolment).data)

    @extend_schema(request=s.TransferSerializer, responses={201: s.EnrolmentTransferSerializer})
    @action(detail=True, methods=["post"])
    def transfer(self, request: Request, pk: Any = None) -> Response:
        """Move to another class: the old fee is cut to the sessions attended (credited),
        the new class charges its prorated fee."""
        payload = s.TransferSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        record = services.transfer(
            self.get_object(),
            data["to_class"],
            effective=data.get("effective_date"),
            reason=data["reason"],
            override_capacity=data["override_capacity"],
            user=request.user,
        )
        return Response(s.EnrolmentTransferSerializer(record).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=s.EnrolmentSerializer)
    @action(detail=True, methods=["post"], url_path="convert-trial")
    def convert_trial(self, request: Request, pk: Any = None) -> Response:
        enrolment = services.convert_trial(self.get_object(), user=request.user)
        return Response(self.get_serializer(enrolment).data)

    @extend_schema(request=None, responses=s.EnrolmentSerializer)
    @action(detail=True, methods=["post"], url_path="cancel-pending")
    def cancel_pending(self, request: Request, pk: Any = None) -> Response:
        enrolment = services.cancel_pending(self.get_object(), user=request.user)
        return Response(self.get_serializer(enrolment).data)


# --- term rollover (T08) ------------------------------------------------------------------------


class RolloverViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Re-enrolment for next term (``TermRolloverWorkflow``): families confirm or opt out
    by a deadline; then continuing students are enrolled and billed, other places go to
    the waitlists."""

    model = TermRollover
    serializer_class = s.TermRolloverSerializer
    permission_classes = perms({"GET": VIEW, "POST": "courses.rollover.manage"})
    http_method_names = ["get", "post", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[TermRollover]:
        visible = selectors.terms(self.request.user)
        return TermRollover.objects.filter(from_term__in=visible.values("pk")).select_related(
            "from_term", "to_term"
        )

    @extend_schema(request=s.RolloverStartSerializer, responses={201: s.TermRolloverSerializer})
    def create(self, request: Request) -> Response:
        payload = s.RolloverStartSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        rollover = services.start_rollover(
            data["from_term"], data["to_term"], mode=data["mode"], deadline=data["deadline"],
            user=request.user,
        )  # fmt: skip
        return Response(self.get_serializer(rollover).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses=s.RolloverOfferSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def offers(self, request: Request, pk: Any = None) -> Response:
        rollover = self.get_object()
        qs = rollover.offers.select_related(
            "student", "enrolment__group_class", "to_class__course"
        ).order_by("student__first_name")
        return Response(s.RolloverOfferSerializer(qs, many=True).data)

    @extend_schema(request=None, responses=s.TermRolloverSerializer)
    @action(detail=True, methods=["post"])
    def finalise(self, request: Request, pk: Any = None) -> Response:
        """Finish now instead of waiting for the deadline."""
        rollover = services.finish_rollover_now(self.get_object(), user=request.user)
        return Response(self.get_serializer(rollover).data)

    @extend_schema(request=None, responses=s.TermRolloverSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        rollover = services.cancel_rollover(self.get_object(), user=request.user)
        return Response(self.get_serializer(rollover).data)
