"""Scheduling API (E08 §4)."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date, parse_datetime
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import DomainError, NotFound, PermissionDenied
from tutortrack.core.permissions import (
    HasMethodPermission,
    HasOrganisation,
    has_perm,
    permission_scope,
    scope_queryset,
)
from tutortrack.core.time import now
from tutortrack.people.models import TutorProfile

from .. import availability, ical, selectors, services
from ..models import (
    AvailabilityException,
    AvailabilityTemplate,
    BookingHold,
    CalendarEvent,
    ICalFeedToken,
    Lesson,
    LessonSeries,
    RescheduleRequest,
)
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def _override(request: Request, wanted: bool) -> bool:
    if wanted and not has_perm(request.user, "scheduling.override_conflicts"):
        raise PermissionDenied()
    return wanted


def _range(request: Request, *, default_days: int = 7) -> tuple[datetime, datetime]:
    start = parse_datetime(request.query_params.get("start", "") or "")
    end = parse_datetime(request.query_params.get("end", "") or "")
    if start is None:
        raise ValidationError({"start": ["Give a start (ISO 8601 with timezone)."]})
    end = end or start + timedelta(days=default_days)
    if end <= start or end - start > timedelta(days=62):
        raise ValidationError({"end": ["Give an end after the start, at most 62 days later."]})
    return start, end


def _result(result: services.LessonResult, request: Request) -> dict[str, Any]:
    return {
        "lesson": s.LessonSerializer(result.lesson, context={"request": request}).data,
        "warnings": [c.as_dict() for c in result.warnings],
    }


class LessonFilter(filters.FilterSet):
    start = filters.IsoDateTimeFilter(
        field_name="end", lookup_expr="gt", label="Lessons ending after"
    )
    end = filters.IsoDateTimeFilter(
        field_name="start", lookup_expr="lt", label="Lessons starting before"
    )
    status = filters.MultipleChoiceFilter(choices=Lesson.Status.choices)
    tutor = filters.UUIDFilter(field_name="tutors__tutor", distinct=True)
    student = filters.UUIDFilter(field_name="attendees__student", distinct=True)
    client = filters.UUIDFilter(field_name="attendees__client", distinct=True)
    job = filters.UUIDFilter()
    series = filters.UUIDFilter()
    service = filters.UUIDFilter()

    class Meta:
        model = Lesson
        fields: list[str] = []


class LessonViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Lessons (E08). List with ``?start&end`` and filters; edits re-price unlocked lessons.
    A hard conflict returns 422 with ``conflicts``; send ``override_conflicts`` (with the
    permission) to schedule anyway."""

    model = Lesson
    serializer_class = s.LessonSerializer
    filterset_class = LessonFilter
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_classes = perms(
        {
            "GET": "scheduling.lesson.view",
            "POST": "scheduling.lesson.create",
            "PATCH": "scheduling.lesson.edit",
            "DELETE": "scheduling.lesson.delete",
        }
    )

    def get_tenant_queryset(self) -> QuerySet[Lesson]:
        qs = scope_queryset(self.request.user, Lesson.objects.all(), "scheduling.lesson.view")
        return qs.select_related("service", "location").prefetch_related(
            "tutors__tutor", "attendees__student"
        )

    @extend_schema(request=s.LessonWriteSerializer, responses={201: s.LessonResultSerializer})
    def create(self, request: Request) -> Response:
        payload = s.LessonWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        override = _override(request, data.pop("override_conflicts"))
        from tutortrack.people.assignability import override_from_request

        with override_from_request(request):
            result = services.create_lesson(override_conflicts=override, **data)
        return Response(_result(result, request), status=status.HTTP_201_CREATED)

    @extend_schema(request=s.LessonUpdateSerializer, responses=s.LessonResultSerializer)
    def partial_update(self, request: Request, pk: Any = None) -> Response:
        """``scope`` = ``this`` (just this lesson), ``following`` or ``all`` (its series)."""
        lesson = self.get_object()
        payload = s.LessonUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        scope = data.pop("scope", "this")
        overwrite = data.pop("overwrite_exceptions", False)
        override = _override(request, data.pop("override_conflicts", False))
        notify = data.pop("notify", True)
        reason = data.pop("reason", "")
        if scope != "this":
            if lesson.series is None:
                raise ValidationError({"scope": ["This lesson isn't part of a series."]})
            changes = {k: v for k, v in data.items() if k in services.SERIES_FIELDS}
            if "start" in data:
                changes["start_time"] = data["start"].astimezone(_zone(lesson.timezone)).time()
                if "end" in data:
                    changes["duration_minutes"] = int(
                        (data["end"] - data["start"]).total_seconds() // 60
                    )
            services.edit_series(
                lesson.series,
                scope=scope,
                from_lesson=lesson,
                overwrite_exceptions=overwrite,
                **changes,
            )
            lesson.refresh_from_db()
            return Response(_result(services.LessonResult(lesson), request))
        data.pop("service", None) if data.get("service") is None else None
        result = services.update_lesson(
            lesson,
            can_edit_locked=has_perm(request.user, "scheduling.edit_locked"),
            override_conflicts=override,
            notify=notify,
            reason=reason,
            **data,
        )
        return Response(_result(result, request))

    def destroy(self, request: Request, pk: Any = None) -> Response:
        services.delete_lesson(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=s.CancelSerializer,
        responses=s.CancelResultSerializer,
        parameters=[
            OpenApiParameter(
                "preview", bool, description="Only show the policy outcome (nothing changes)."
            )
        ],
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=perms({"POST": "scheduling.lesson.cancel"}),
    )
    def cancel(self, request: Request, pk: Any = None) -> Response:
        """Cancel under the cancellation policy (E09 FR-09-3). ``?preview=true`` returns the
        outcome ("late cancellation: client charged 100%...") without cancelling. An
        ``override`` of the percentages needs ``delivery.cancel.override_policy``."""
        from tutortrack.delivery import services as delivery

        payload = s.CancelSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        if data["override"] and not has_perm(request.user, "delivery.cancel.override_policy"):
            raise PermissionDenied()
        preview = request.query_params.get("preview") in {"1", "true", "yes"}
        result = delivery.cancel_lesson(
            self.get_object(), user=request.user, preview=preview, **data
        )
        return Response(_cancel_out(result, request))

    @extend_schema(request=s.CompleteSerializer, responses=s.LessonSerializer)
    @action(
        detail=True,
        methods=["post"],
        permission_classes=perms({"POST": "scheduling.lesson.complete"}),
    )
    def complete(self, request: Request, pk: Any = None) -> Response:
        """Complete with attendance (E09 FR-09-1/2). Students left out were present. A
        prepaid client without enough credit blocks completion (422,
        ``code=insufficient_balance``); ``override_balance`` needs
        ``delivery.balance.override``."""
        from tutortrack.delivery import services as delivery

        payload = s.CompleteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        if data["override_balance"] and not has_perm(request.user, "delivery.balance.override"):
            raise PermissionDenied()
        lesson = delivery.complete_lesson(
            self.get_object(),
            user=request.user,
            attendance=_attendance(data["attendance"]),
            actual_start=data["actual_start"],
            actual_end=data["actual_end"],
            override_balance=data["override_balance"],
        )
        lesson.refresh_from_db()
        return Response(self.get_serializer(lesson).data)

    @extend_schema(request=s.AttendanceSerializer, responses=s.LessonSerializer)
    @action(
        detail=True,
        methods=["patch"],
        permission_classes=perms({"PATCH": "delivery.attendance.edit"}),
    )
    def attendance(self, request: Request, pk: Any = None) -> Response:
        """Correct attendance after completion (unlocked lessons)."""
        from tutortrack.delivery import services as delivery

        lesson = self.get_object()
        if not scope_queryset(
            request.user, Lesson.objects.filter(pk=lesson.pk), "delivery.attendance.edit"
        ).exists():
            raise PermissionDenied()
        payload = s.AttendanceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lesson = delivery.record_attendance(
            lesson, _attendance(payload.validated_data["attendance"]), user=request.user
        )
        return Response(self.get_serializer(lesson).data)

    @extend_schema(request=s.LessonReasonSerializer, responses=s.LessonSerializer)
    @action(
        detail=True,
        methods=["post"],
        permission_classes=perms({"POST": "scheduling.lesson.complete"}),
    )
    def missed(self, request: Request, pk: Any = None) -> Response:
        payload = s.LessonReasonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lesson = services.mark_missed(self.get_object(), reason=payload.validated_data["reason"])
        return Response(self.get_serializer(lesson).data)

    @extend_schema(request=s.RescheduleSerializer, responses=s.LessonResultSerializer)
    @action(
        detail=True, methods=["post"], permission_classes=perms({"POST": "scheduling.lesson.edit"})
    )
    def reschedule(self, request: Request, pk: Any = None) -> Response:
        payload = s.RescheduleSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        result = services.update_lesson(
            self.get_object(),
            start=data["start"],
            end=data["end"],
            reason=data["reason"],
            notify=data["notify"],
            override_conflicts=_override(request, data["override_conflicts"]),
            can_edit_locked=has_perm(request.user, "scheduling.edit_locked"),
        )
        return Response(_result(result, request))

    @extend_schema(request=s.DuplicateSerializer, responses={201: s.LessonResultSerializer})
    @action(
        detail=True,
        methods=["post"],
        permission_classes=perms({"POST": "scheduling.lesson.create"}),
    )
    def duplicate(self, request: Request, pk: Any = None) -> Response:
        payload = s.DuplicateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = services.duplicate_lesson(
            self.get_object(),
            start=payload.validated_data["start"],
            override_conflicts=_override(request, payload.validated_data["override_conflicts"]),
        )
        return Response(_result(result, request), status=status.HTTP_201_CREATED)

    @extend_schema(request=s.BulkLessonSerializer, responses=s.BulkResultSerializer)
    @action(
        detail=False, methods=["post"], permission_classes=perms({"POST": "scheduling.lesson.edit"})
    )
    def bulk(self, request: Request) -> Response:
        """Bulk actions on up to 200 lessons; each lesson succeeds or fails on its own."""
        payload = s.BulkLessonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        needs = {
            "complete": "scheduling.lesson.complete",
            "cancel": "scheduling.lesson.cancel",
            "delete": "scheduling.lesson.delete",
        }.get(data["action"], "scheduling.lesson.edit")
        if not has_perm(request.user, needs):
            raise PermissionDenied()
        lessons = self.get_queryset().filter(pk__in=data["ids"])
        succeeded: list[str] = []
        errors: dict[str, str] = {}
        for lesson in lessons:
            try:
                from django.db import transaction

                with transaction.atomic():
                    _bulk_one(lesson, data, request)
                succeeded.append(str(lesson.pk))
            except DomainError as exc:
                errors[str(lesson.pk)] = str(exc)
        for missing in {str(i) for i in data["ids"]} - set(succeeded) - set(errors):
            errors[missing] = "Not found."
        return Response({"succeeded": succeeded, "failed": errors})

    @extend_schema(responses=s.ConflictSerializer(many=True))
    @action(detail=True, methods=["get"])
    def pricing(self, request: Request, pk: Any = None) -> Response:
        """The pricing trace stored on the lesson (FR-06-4 popover)."""
        lesson = self.get_object()
        out: dict[str, Any] = {}
        if has_perm(request.user, "billing.rates.view_charge"):
            out["charges"] = [a.charge_snapshot for a in lesson.attendees.all()]
        if has_perm(request.user, "billing.rates.view_pay"):
            out["pay"] = [t.pay_snapshot for t in lesson.tutors.all()]
        if not out:
            raise PermissionDenied()
        return Response(out)


def _attendance(rows: list[dict[str, Any]]) -> list[Any]:
    from tutortrack.delivery.services import AttendanceRow

    return [AttendanceRow(r["attendee"], r["outcome"], r.get("late_minutes")) for r in rows]


def _cancel_out(result: Any, request: Request) -> dict[str, Any]:
    decision = result.decision
    outcome = s.CancelOutcomeSerializer(
        {
            "kind": decision.kind,
            "charge_percent": result.charge_percent,
            "pay_percent": result.pay_percent,
            "policy_charge_percent": decision.charge_percent,
            "policy_pay_percent": decision.pay_percent,
            "notice_minutes": decision.notice_minutes,
            "makeup_credit": decision.makeup_credit,
            "policy_name": decision.policy.snapshot()["name"],
            "message": decision.message,
        }
    ).data
    return {
        "outcome": outcome,
        "lesson": (
            s.LessonSerializer(result.lesson, context={"request": request}).data
            if result.lesson
            else None
        ),
        "following_cancelled": result.following_cancelled,
    }


def _bulk_one(lesson: Lesson, data: dict[str, Any], request: Request) -> None:
    from tutortrack.delivery import services as delivery

    action = data["action"]
    if action == "complete":
        delivery.complete_lesson(lesson, user=request.user)
    elif action == "cancel":
        delivery.cancel_lesson(
            lesson, user=request.user, cancelled_by=data["cancelled_by"], reason=data["reason"]
        )
    elif action == "delete":
        services.delete_lesson(lesson)
    elif action == "reassign_tutor":
        if not data.get("tutor"):
            raise ValidationError({"tutor": ["Choose a tutor."]})
        services.update_lesson(
            lesson,
            tutors=[{"tutor": data["tutor"]}],
            can_edit_locked=has_perm(request.user, "scheduling.edit_locked"),
        )
    elif action == "change_location":
        services.update_lesson(lesson, location=data.get("location"))


def _zone(tz: str) -> Any:
    from zoneinfo import ZoneInfo

    return ZoneInfo(tz)


class SeriesViewSet(TenantScopedViewMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Recurring lessons (FR-08-2). Create reports occurrences skipped for clashes."""

    model = LessonSeries
    serializer_class = s.SeriesSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_classes = perms(
        {
            "GET": "scheduling.lesson.view",
            "POST": "scheduling.lesson.create",
            "PATCH": "scheduling.lesson.edit",
        }
    )

    def get_tenant_queryset(self) -> QuerySet[LessonSeries]:
        visible = scope_queryset(self.request.user, Lesson.objects.all(), "scheduling.lesson.view")
        return LessonSeries.objects.filter(pk__in=visible.values("series_id"))

    def _out(self, result: services.SeriesResult, changed: int = 0) -> dict[str, Any]:
        return {
            "series": result.series,
            "lessons_created": len(result.created) if not changed else 0,
            "lessons_changed": changed,
            "skipped": [
                {"date": day, "conflicts": [c.as_dict() for c in found]}
                for day, found in result.skipped
            ],
            "conflicting": [str(lesson.pk) for lesson, _found in result.conflicting],
        }

    @extend_schema(request=s.SeriesCreateSerializer, responses={201: s.SeriesResultSerializer})
    def create(self, request: Request) -> Response:
        payload = s.SeriesCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        if data["conflict_mode"] == "create":
            _override(request, True)
        result = services.create_series(**data)
        return Response(
            s.SeriesResultSerializer(self._out(result)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=s.SeriesUpdateSerializer, responses=s.SeriesResultSerializer)
    def partial_update(self, request: Request, pk: Any = None) -> Response:
        payload = s.SeriesUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        result = services.edit_series(
            self.get_object(),
            scope=data.pop("scope"),
            from_lesson=data.pop("from_lesson", None),
            overwrite_exceptions=data.pop("overwrite_exceptions"),
            **data,
        )
        return Response(
            s.SeriesResultSerializer(self._out(result, changed=len(result.created))).data
        )

    @extend_schema(request=s.EndSeriesSerializer, responses=s.SeriesSerializer)
    @action(
        detail=True,
        methods=["post"],
        permission_classes=perms({"POST": "scheduling.lesson.cancel"}),
    )
    def end(self, request: Request, pk: Any = None) -> Response:
        payload = s.EndSeriesSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        series = self.get_object()
        services.end_series(series, **payload.validated_data)
        return Response(s.SeriesSerializer(series).data)


class ConflictCheckView(APIView):
    """Dry-run the conflict engine for a proposed lesson (FR-08-6)."""

    permission_classes = perms({"POST": "scheduling.lesson.view"})

    @extend_schema(request=s.ConflictCheckSerializer, responses=s.ConflictSerializer(many=True))
    def post(self, request: Request) -> Response:
        from .. import conflicts

        payload = s.ConflictCheckSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        lesson = data.get("lesson")
        found = conflicts.check(
            start=data["start"],
            end=data["end"],
            tz=data.get("timezone") or (lesson.timezone if lesson else "UTC"),
            tutors=data["tutors"],
            students=data["students"],
            exclude_lesson_ids=[lesson.pk] if lesson else [],
            location=data.get("location"),
            online=data["online"],
            job=data.get("job"),
            room=data.get("room"),
        )
        return Response([c.as_dict() for c in found])


class CalendarView(APIView):
    """Lessons and events overlapping ``[start, end)`` in a light shape (FR-08-7)."""

    permission_classes = perms({"GET": "scheduling.lesson.view"})

    @extend_schema(
        parameters=[
            OpenApiParameter("start", str, required=True),
            OpenApiParameter("end", str),
            *[
                OpenApiParameter(name, str, many=True)
                for name in (
                    "tutor",
                    "student",
                    "client",
                    "service",
                    "job",
                    "location",
                    "branch",
                    "status",
                    "room",
                )
            ],
            OpenApiParameter("include_events", bool),
        ],
        responses=s.CalendarItemSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        start, end = _range(request)
        keys = (
            "tutor", "student", "client", "service", "job", "location", "branch", "status", "room",
        )  # fmt: skip
        filters_ = {
            k: request.query_params.getlist(k) for k in keys if request.query_params.getlist(k)
        }
        items = [
            selectors.project_lesson(lesson)
            for lesson in selectors.lessons_in_range(request.user, start, end, filters_)
        ]
        if request.query_params.get("include_events", "true") != "false":
            items += [
                selectors.project_event(event)
                for event in selectors.events_in_range(
                    request.user, start, end, filters_.get("tutor")
                )
            ]
        items.sort(key=lambda item: item["start"])
        return Response(s.CalendarItemSerializer(items, many=True).data)


class EventViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Calendar events and organisation-wide closures (FR-08-4)."""

    model = CalendarEvent
    serializer_class = s.CalendarEventSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_classes = perms({"GET": "scheduling.lesson.view", "*": "scheduling.event.manage"})

    def get_tenant_queryset(self) -> QuerySet[CalendarEvent]:
        qs = CalendarEvent.objects.prefetch_related("participants")
        if not has_perm(self.request.user, "scheduling.event.view"):
            qs = qs.filter(CalendarEvent.own_scope_q(self.request.user))
        if self.action == "list":
            start, end = _range(self.request, default_days=31)
            qs = qs.filter(start__lt=end, end__gt=start)
        return qs

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        serializer.instance, _cancelled = services.save_event(
            None, tutors=data.pop("tutors", None), **data
        )

    def perform_update(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        serializer.instance, _cancelled = services.save_event(
            serializer.instance, tutors=data.pop("tutors", None), **data
        )

    def perform_destroy(self, instance: CalendarEvent) -> None:
        services.delete_event(instance)


def _tutor_for(request: Request, tutor_id: Any, *, edit: bool) -> TutorProfile:
    """Tutors manage their own availability; others need the view/manage permission and
    must be able to see the tutor."""
    tutor = get_object_or_404(TutorProfile, pk=tutor_id)
    membership = tutor.membership
    own = membership is not None and membership.user_id == request.user.pk
    if own:
        codename = "scheduling.availability.edit" if edit else "scheduling.availability.view"
        if has_perm(request.user, codename):
            return tutor
    codename = "scheduling.availability.manage_others" if edit else "scheduling.availability.view"
    visible = scope_queryset(
        request.user, TutorProfile.objects.filter(pk=tutor.pk), "people.tutor.view"
    )
    if own or not has_perm(request.user, codename) or not visible.exists():
        raise NotFound()
    return tutor


class AvailabilityView(APIView):
    """A tutor's weekly availability (GET current template and windows, PUT a new one)."""

    permission_classes = AUTH

    @extend_schema(responses=s.AvailabilitySerializer)
    def get(self, request: Request, tutor_id: Any) -> Response:
        tutor = _tutor_for(request, tutor_id, edit=False)
        template = availability.template_for(tutor.pk, now().date()) or (
            AvailabilityTemplate.objects.filter(tutor=tutor).order_by("-effective_from").first()
        )
        if template is None:
            return Response(
                {
                    "effective_from": None,
                    "timezone": tutor.membership.user.timezone if tutor.membership else "",
                    "windows": [],
                }
            )
        return Response(
            {
                "effective_from": template.effective_from,
                "timezone": template.timezone,
                "windows": s.WindowSerializer(template.windows.all(), many=True).data,
            }
        )

    @extend_schema(request=s.AvailabilitySerializer, responses=s.AvailabilitySerializer)
    def put(self, request: Request, tutor_id: Any) -> Response:
        tutor = _tutor_for(request, tutor_id, edit=True)
        payload = s.AvailabilitySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        template = services.set_availability(
            tutor,
            windows=data["windows"],
            effective_from=data["effective_from"],
            timezone=data["timezone"],
        )
        return Response(
            {
                "effective_from": template.effective_from,
                "timezone": template.timezone,
                "windows": s.WindowSerializer(template.windows.all(), many=True).data,
            }
        )


class SlotsView(APIView):
    """Free start times for a tutor (FR-08-5 AC)."""

    permission_classes = AUTH

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, required=True),
            OpenApiParameter("to", str, required=True),
            OpenApiParameter("duration", int, required=True),
            OpenApiParameter("step", int),
        ],
        responses=s.SlotSerializer(many=True),
    )
    def get(self, request: Request, tutor_id: Any) -> Response:
        tutor = _tutor_for(request, tutor_id, edit=False)
        start = parse_date(request.query_params.get("from", "") or "")
        end = parse_date(request.query_params.get("to", "") or "")
        try:
            duration = int(request.query_params.get("duration", "60"))
            step = int(request.query_params.get("step", "15"))
        except ValueError as exc:
            raise ValidationError({"duration": ["Enter minutes."]}) from exc
        if start is None or end is None or end < start or (end - start).days > 31:
            raise ValidationError({"to": ["Give from and to dates, at most 31 days apart."]})
        if not 5 <= duration <= 720 or not 5 <= step <= 120:
            raise ValidationError({"duration": ["Between 5 and 720 minutes."]})
        slots = availability.free_slots(
            tutor.pk, start=start, end=end, duration_minutes=duration, step_minutes=step
        )
        return Response(
            s.SlotSerializer([{"start": x.start, "end": x.end} for x in slots], many=True).data
        )


@extend_schema_view(
    list=extend_schema(parameters=[OpenApiParameter("tutor", str), OpenApiParameter("status", str)])
)
class TimeOffViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Time off and extra availability (FR-08-5). Creating time off returns the planned
    lessons that now need cover in ``clashes``."""

    model = AvailabilityException
    serializer_class = s.ExceptionSerializer
    filterset_fields: list[str] = []

    def get_tenant_queryset(self) -> QuerySet[AvailabilityException]:
        qs = scope_queryset(
            self.request.user, AvailabilityException.objects.all(), "scheduling.availability.view"
        ).select_related("tutor")
        tutor = self.request.query_params.get("tutor")
        wanted = self.request.query_params.get("status")
        if wanted:
            qs = qs.filter(status=wanted)
        return qs.filter(tutor_id=tutor) if tutor else qs

    def create(self, request: Request) -> Response:
        """Tutors asking for their own time off wait for approval when
        ``scheduling.time_off_approval`` is on (E08-T15); staff entering it approve it."""
        from tutortrack.tenancy.settings_service import get_setting

        payload = s.ExceptionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        tutor = _tutor_for(request, data.pop("tutor").pk, edit=True)
        own = tutor.membership is not None and tutor.membership.user_id == request.user.pk
        needs_approval = (
            own
            and bool(get_setting("scheduling.time_off_approval"))
            and permission_scope(request.user, "scheduling.availability.manage_others")
            not in ("all", "branch")
        )
        exception, clashes = services.add_exception(
            tutor, needs_approval=needs_approval, user=request.user, **data
        )
        body = s.ExceptionSerializer(exception).data
        body["clashes"] = [str(lesson.pk) for lesson in clashes]
        return Response(body, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance: AvailabilityException) -> None:
        _tutor_for(self.request, instance.tutor_id, edit=True)
        services.delete_exception(instance)

    @extend_schema(request=s.ApprovalDecisionSerializer, responses=s.ExceptionSerializer)
    @action(
        detail=True,
        methods=["post"],
        permission_classes=perms({"POST": "scheduling.availability.manage_others"}),
    )
    def decide(self, request: Request, pk: Any = None) -> Response:
        """Approve or decline requested time off (E08-T15)."""
        payload = s.ApprovalDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        exception = self.get_object()
        if exception.tutor.membership and exception.tutor.membership.user_id == request.user.pk:
            raise PermissionDenied("You can't approve your own time off.")
        exception = services.decide_time_off(
            exception,
            approve=payload.validated_data["approve"],
            note=payload.validated_data["note"],
            user=request.user,
        )
        return Response(s.ExceptionSerializer(exception).data)


class FeedViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Your secret calendar feed URLs (FR-08-11). The URL is shown once, when created."""

    model = ICalFeedToken
    serializer_class = s.FeedSerializer
    pagination_class = None
    permission_classes = AUTH

    def get_tenant_queryset(self) -> QuerySet[ICalFeedToken]:
        return ICalFeedToken.objects.filter(user=self.request.user, revoked_at__isnull=True)

    @extend_schema(request=s.FeedSerializer, responses={201: s.FeedCreatedSerializer})
    def create(self, request: Request) -> Response:
        payload = s.FeedSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        kind, subject_id = payload.validated_data["kind"], payload.validated_data["subject_id"]
        _check_feed_subject(request, kind, subject_id)
        feed, token = services.create_feed(request.user, kind=kind, subject_id=subject_id)
        body = s.FeedSerializer(feed).data
        body["url"] = request.build_absolute_uri(f"/ical/{token}.ics")
        return Response(body, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def revoke(self, request: Request, pk: Any = None) -> Response:
        services.revoke_feed(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


def _check_feed_subject(request: Request, kind: str, subject_id: Any) -> None:
    from tutortrack.people.models import Client, Student

    model, perm = {
        "tutor": (TutorProfile, "people.tutor.view"),
        "client": (Client, "people.client.view"),
        "student": (Student, "people.student.view"),
    }[kind]
    if not scope_queryset(request.user, model.objects.filter(pk=subject_id), perm).exists():
        raise NotFound()


def ical_feed(request: HttpRequest, token: str) -> HttpResponse:
    """Public, read-only feed: ``/ical/<token>.ics`` on the organisation's host."""
    feed = ICalFeedToken.objects.filter(
        token_hash=services.hash_token(token), revoked_at__isnull=True
    ).first()
    if feed is None:
        return HttpResponse(status=404)
    ICalFeedToken.objects.filter(pk=feed.pk).update(last_used_at=now())
    body = ical.render(ical.feed_lessons(feed), name="TutorTrack", host=request.get_host())
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Cache-Control"] = "private, max-age=300"
    return response


# --- Phase 2: rooms (T12) and re-pricing ----------------------------------------------------------


class RoomScheduleView(APIView):
    """The room resource view: each room with its lessons in ``[start, end)`` (E08-T12)."""

    permission_classes = perms({"GET": "scheduling.lesson.view"})

    @extend_schema(
        parameters=[
            OpenApiParameter("start", str, required=True),
            OpenApiParameter("end", str),
            OpenApiParameter("location", str),
        ],
        responses=s.RoomScheduleSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        from tutortrack.catalogue.models import Location

        start, end = _range(request)
        location = None
        if request.query_params.get("location"):
            location = get_object_or_404(Location, pk=request.query_params["location"])
        rows = selectors.room_schedule(request.user, start, end, location)
        return Response(s.RoomScheduleSerializer(rows, many=True).data)


class RepriceView(APIView):
    """Re-price unlocked lessons with the current rates and rules (FR-06-4 "apply to future
    lessons? (N affected)", E06-T07 retroactive tool). ``dry_run`` (default) only counts."""

    permission_classes = perms({"POST": "rates.manage"})

    @extend_schema(request=s.RepriceRequestSerializer, responses=s.RepriceResultSerializer)
    def post(self, request: Request) -> Response:
        payload = s.RepriceRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        dry_run = data.pop("dry_run")
        filters_ = {
            "start": data.get("start"),
            "end": data.get("end"),
            "tutor_id": data.get("tutor"),
            "service_id": data.get("service"),
            "include_past": data["include_past"],
        }
        count = services.reprice_lessons(dry_run=dry_run, **filters_)
        return Response({"lessons": count, "dry_run": dry_run})


# --- reschedule requests (T13) -------------------------------------------------------------------


def _tutor_on(lesson: Lesson, user: Any) -> bool:
    return lesson.tutors.filter(tutor__membership__user=user).exists()


class LessonRescheduleRequestView(APIView):
    """Ask to move a lesson (its tutor, or staff): the other side or an admin approves."""

    permission_classes = perms({"POST": "scheduling.lesson.view"})

    @extend_schema(request=s.LessonChangeProposal, responses={201: s.LessonChangeRequestSerializer})
    def post(self, request: Request, lesson_id: Any) -> Response:
        visible = scope_queryset(request.user, Lesson.objects.all(), "scheduling.lesson.view")
        lesson = get_object_or_404(visible, pk=lesson_id)
        if _tutor_on(lesson, request.user):
            requester = RescheduleRequest.Party.TUTOR
        elif has_perm(request.user, "scheduling.lesson.edit", lesson):
            requester = RescheduleRequest.Party.STAFF
        else:
            raise PermissionDenied()
        payload = s.LessonChangeProposal(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        created = services.request_reschedule(
            lesson,
            options=[(o["start"], o["end"]) for o in data["options"]],
            requester=requester,
            reason=data["reason"],
            user=request.user,
        )
        return Response(s.LessonChangeRequestSerializer(created).data, status=201)


class RescheduleRequestViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Requests to move lessons (FR-08-8). Staff answer any; a tutor answers a family's
    request for their lesson. Undecided requests are declined at ``deadline``."""

    model = RescheduleRequest
    serializer_class = s.LessonChangeRequestSerializer
    permission_classes = perms({"GET": "scheduling.lesson.view", "POST": "scheduling.lesson.view"})

    def get_tenant_queryset(self) -> QuerySet[RescheduleRequest]:
        visible = scope_queryset(self.request.user, Lesson.objects.all(), "scheduling.lesson.view")
        qs = RescheduleRequest.objects.filter(lesson__in=visible.values("pk")).select_related(
            "lesson"
        )
        for key in ("status", "lesson"):
            if self.request.query_params.get(key):
                qs = qs.filter(**{key: self.request.query_params[key]})
        return qs

    @extend_schema(parameters=[OpenApiParameter("status", str), OpenApiParameter("lesson", str)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=s.LessonChangeDecisionSerializer, responses=s.LessonChangeRequestSerializer
    )
    @action(detail=True, methods=["post"])
    def decide(self, request: Request, pk: Any = None) -> Response:
        item = self.get_object()
        staff = has_perm(request.user, "scheduling.lesson.edit", item.lesson)
        counterpart = item.requester == RescheduleRequest.Party.CLIENT and _tutor_on(
            item.lesson, request.user
        )
        if not (staff or counterpart) or item.requested_by_id == request.user.pk:
            raise PermissionDenied()
        payload = s.LessonChangeDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        item = services.decide_reschedule(
            item,
            approve=data["approve"],
            choice=data["choice"],
            note=data["note"],
            user=request.user,
            override_conflicts=_override(request, data["override_conflicts"]),
        )
        return Response(s.LessonChangeRequestSerializer(item).data)

    @extend_schema(request=None, responses=s.LessonChangeRequestSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        item = self.get_object()
        if item.requested_by_id != request.user.pk and not has_perm(
            request.user, "scheduling.lesson.edit", item.lesson
        ):
            raise PermissionDenied()
        return Response(s.LessonChangeRequestSerializer(services.cancel_reschedule(item)).data)


# --- online booking (T14) ------------------------------------------------------------------------


class BookingSettingsView(APIView):
    """Online booking settings (FR-08-9)."""

    permission_classes = perms(
        {"GET": "scheduling.booking.settings", "PUT": "scheduling.booking.settings"}
    )

    @extend_schema(responses=s.BookingSettingsSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.BookingSettingsSerializer(services.booking_settings()).data)

    @extend_schema(request=s.BookingSettingsSerializer, responses=s.BookingSettingsSerializer)
    def put(self, request: Request) -> Response:
        payload = s.BookingSettingsSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        updated = services.save_booking_settings(**payload.validated_data)
        return Response(s.BookingSettingsSerializer(updated).data)


class BookingHoldViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Online bookings: staff approve or decline those waiting (FR-08-9)."""

    model = BookingHold
    serializer_class = s.BookingHoldSerializer
    permission_classes = perms(
        {"GET": "scheduling.lesson.view", "POST": "scheduling.lesson.create"}
    )

    def get_tenant_queryset(self) -> QuerySet[BookingHold]:
        if not has_perm(self.request.user, "scheduling.lesson.create"):
            return BookingHold.objects.none()
        qs = BookingHold.objects.select_related("service", "tutor", "student")
        wanted = self.request.query_params.get("status")
        return qs.filter(status=wanted) if wanted else qs

    @extend_schema(parameters=[OpenApiParameter("status", str)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(request=s.ApprovalDecisionSerializer, responses=s.BookingHoldSerializer)
    @action(detail=True, methods=["post"])
    def decide(self, request: Request, pk: Any = None) -> Response:
        payload = s.ApprovalDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        hold = services.decide_booking(
            self.get_object(),
            approve=payload.validated_data["approve"],
            note=payload.validated_data["note"],
            user=request.user,
        )
        hold.refresh_from_db()
        return Response(s.BookingHoldSerializer(hold).data)

    @extend_schema(request=None, responses=s.BookingHoldSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        hold = services.cancel_hold(self.get_object(), user=request.user)
        hold.refresh_from_db()
        return Response(s.BookingHoldSerializer(hold).data)


def public_name(tutor: TutorProfile) -> str:
    """First name and last initial: what families see before booking."""
    initial = f" {tutor.last_name[:1]}." if tutor.last_name else ""
    return f"{tutor.first_name}{initial}".strip()


def booking_services_payload(*, show_prices: bool = True) -> list[dict[str, Any]]:
    """Bookable services with their tutors (shared by the portal and the public widget)."""
    if not services.booking_settings().enabled:
        return []
    out = []
    for service in services.bookable_services():
        tutors = services.bookable_tutors(service)
        out.append(
            {
                "id": str(service.pk),
                "name": service.name,
                "description": service.public_description,
                "duration_minutes": service.default_duration_minutes,
                "delivery_mode": service.delivery_mode,
                "price": service.charge_rate.round_to_minor().to_dict() if show_prices else None,
                "tutors": [{"id": str(t.pk), "name": public_name(t)} for t in tutors],
            }
        )
    return out


def booking_slots_payload(request: Request) -> list[dict[str, Any]]:
    from tutortrack.catalogue.models import Service

    service = Service.objects.filter(
        pk=request.query_params.get("service") or None, active=True, bookable_online=True
    ).first()
    if service is None:
        raise NotFound()
    tutor = None
    if request.query_params.get("tutor"):
        tutor = get_object_or_404(TutorProfile, pk=request.query_params["tutor"])
    start = parse_date(request.query_params.get("from", "") or "") or now().date()
    end = parse_date(request.query_params.get("to", "") or "") or start + timedelta(days=7)
    if end < start or (end - start).days > 31:
        raise ValidationError({"to": ["Ask for at most 31 days."]})
    slots = services.booking_slots(service, start=start, end=end, tutor=tutor)
    names = {str(t.pk): public_name(t) for t in services.bookable_tutors(service)}
    return [
        {"tutor": x.tutor_id, "tutor_name": names.get(x.tutor_id, ""), "start": x.start,
         "end": x.end}
        for x in slots
    ]  # fmt: skip


SLOT_PARAMS = [
    OpenApiParameter("service", str, required=True),
    OpenApiParameter("tutor", str),
    OpenApiParameter("from", str, description="First local date (YYYY-MM-DD)."),
    OpenApiParameter("to", str, description="Last local date (at most 31 days on)."),
]


class PublicBookingView(APIView):
    """Public, token-scoped booking for the website widget (FR-08-9, E24)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_widget"

    def hold(self, request: Request, hold_id: Any) -> BookingHold:
        body = request.data if isinstance(request.data, dict) else {}
        token = request.query_params.get("token") or body.get("token") or ""
        hold = BookingHold.objects.filter(pk=hold_id).first()
        if (
            hold is None
            or not hold.token_hash
            or not secrets.compare_digest(hold.token_hash, services.hash_token(str(token)))
        ):
            raise NotFound()
        return hold


@extend_schema(tags=["public"])
class PublicBookingServicesView(PublicBookingView):
    @extend_schema(responses=s.BookingServiceSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.BookingServiceSerializer(booking_services_payload(), many=True).data)


@extend_schema(tags=["public"])
class PublicBookingSlotsView(PublicBookingView):
    @extend_schema(parameters=SLOT_PARAMS, responses=s.BookingSlotSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.BookingSlotSerializer(booking_slots_payload(request), many=True).data)


@extend_schema(tags=["public"])
class PublicBookingHoldsView(PublicBookingView):
    @extend_schema(request=s.BookingHoldInput, responses={201: s.BookingHoldCreatedSerializer})
    def post(self, request: Request) -> Response:
        """Hold a slot for a new family. Keep ``token``: it opens the booking."""
        from tutortrack.catalogue.models import Service

        payload = s.BookingHoldInput(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        if not data.get("contact"):
            raise ValidationError({"contact": ["Tell us who you are."]})
        service = Service.objects.filter(
            pk=data["service"], active=True, bookable_online=True
        ).first()
        if service is None:
            raise NotFound()
        tutor = TutorProfile.objects.filter(pk=data["tutor"]).first() if data.get("tutor") else None
        hold, token = services.hold_slot(
            service=service,
            start=data["start"],
            tutor=tutor,
            contact=dict(data["contact"]),
            promo_code=data["promo_code"],
            source=BookingHold.Source.WIDGET,
        )
        body = s.BookingHoldSerializer(hold).data
        body["token"] = token
        return Response(body, status=status.HTTP_201_CREATED)


@extend_schema(tags=["public"])
class PublicBookingHoldView(PublicBookingView):
    @extend_schema(
        parameters=[OpenApiParameter("token", str, required=True)],
        responses=s.BookingHoldSerializer,
    )
    def get(self, request: Request, hold_id: Any) -> Response:
        return Response(s.BookingHoldSerializer(self.hold(request, hold_id)).data)


@extend_schema(tags=["public"])
class PublicBookingSubmitView(PublicBookingView):
    @extend_schema(
        parameters=[OpenApiParameter("token", str, required=True)],
        request=None,
        responses=s.BookingSubmitResultSerializer,
    )
    def post(self, request: Request, hold_id: Any) -> Response:
        hold, pay_link = services.submit_hold(self.hold(request, hold_id))
        hold.refresh_from_db()
        return Response({"booking": s.BookingHoldSerializer(hold).data, "pay_url": pay_link})


@extend_schema(tags=["public"])
class PublicBookingCancelView(PublicBookingView):
    @extend_schema(
        parameters=[OpenApiParameter("token", str, required=True)],
        request=None,
        responses=s.BookingHoldSerializer,
    )
    def post(self, request: Request, hold_id: Any) -> Response:
        hold = services.cancel_hold(self.hold(request, hold_id))
        hold.refresh_from_db()
        return Response(s.BookingHoldSerializer(hold).data)
