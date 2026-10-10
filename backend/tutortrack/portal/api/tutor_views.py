"""Tutor portal API (E16): who I am, today, my students and my earnings."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils.dateparse import parse_date
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
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
                "can_see_pay": has_perm(request.user, "billing.rates.view_pay")
                or has_perm(request.user, "payroll.view"),
            }
        )


class TutorTodayView(TutorView):
    @extend_schema(responses=s.TutorTodaySerializer)
    def get(self, request: Request) -> Response:
        return Response(
            s.TutorTodaySerializer(selectors.today(self.tutor(request), request.user)).data
        )


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
