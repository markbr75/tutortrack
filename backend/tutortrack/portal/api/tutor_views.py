"""Tutor portal API (E16): who I am, today, my students and my earnings."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils.dateparse import parse_date
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.permissions import HasOrganisation, has_perm
from tutortrack.core.time import now

from .. import tutor as selectors
from . import serializers as s


class IsTutor(BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        return has_perm(request.user, "scheduling.lesson.view")


class TutorView(APIView):
    permission_classes = [IsAuthenticated, HasOrganisation, IsTutor]

    def tutor(self, request: Request) -> Any:
        found = selectors.tutor_for(request.user)
        if found is None:
            raise PermissionDenied("There's no tutor profile for this login.")
        return found


class TutorMeView(TutorView):
    @extend_schema(responses=s.TutorMeSerializer)
    def get(self, request: Request) -> Response:
        tutor = self.tutor(request)
        return Response(
            {
                "id": str(tutor.pk),
                "name": tutor.full_name,
                "email": tutor.email,
                "can_cancel": has_perm(request.user, "scheduling.lesson.cancel"),
                "can_edit_lessons": has_perm(request.user, "scheduling.lesson.edit"),
                # G4 (FR-16-2): plan lessons from the tutor app.
                "can_create_lessons": has_perm(request.user, "scheduling.lesson.create"),
                "can_reschedule": has_perm(request.user, "scheduling.lesson.reschedule"),
                "can_see_pay": has_perm(request.user, "billing.rates.view_pay")
                or has_perm(request.user, "payroll.view"),
            }
        )


class TutorTodayView(TutorView):
    @extend_schema(
        responses=s.TutorTodaySerializer,
        examples=[
            OpenApiExample(
                "Two lessons to mark",
                response_only=True,
                value={
                    "date": "2026-10-22",
                    "lessons": [],
                    "reports_due": 1,
                    "unmarked_lessons": 2,
                    "offers": 0,
                    "unread": 3,
                    "earnings_this_month": {"amount": "420.00", "currency": "GBP"},
                },
            )
        ],
    )
    def get(self, request: Request) -> Response:
        """The tutor's day, plus what is waiting: ``unmarked_lessons`` counts lessons that
        have ended and are still planned, on any of the last 60 days."""
        return Response(
            s.TutorTodaySerializer(selectors.today(self.tutor(request), request.user)).data
        )


class TutorOfflineView(TutorView):
    """The offline pack the tutor PWA caches (E16-T08): recent and upcoming lessons with
    their report forms, so registers and reports can be done without a signal."""

    @extend_schema(responses=s.TutorOfflinePackSerializer)
    def get(self, request: Request) -> Response:
        pack = selectors.offline_pack(self.tutor(request), request.user)
        return Response(s.TutorOfflinePackSerializer(pack).data)


class TutorStudentsView(TutorView):
    @extend_schema(responses=s.TutorStudentSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(
            s.TutorStudentSerializer(selectors.students(self.tutor(request)), many=True).data
        )


class TutorEarningsView(TutorView):
    @extend_schema(
        responses=s.TutorEarningsSerializer,
        parameters=[
            OpenApiParameter("from", OpenApiTypes.DATE),
            OpenApiParameter("to", OpenApiTypes.DATE),
        ],
    )
    def get(self, request: Request) -> Response:
        end = parse_date(request.query_params.get("to") or "") or now().date()
        start = parse_date(request.query_params.get("from") or "") or end.replace(day=1)
        if start > end or end - start > timedelta(days=366):
            start = end.replace(day=1)
        data = selectors.earnings(self.tutor(request), start, end)
        return Response(s.TutorEarningsSerializer(data).data)
