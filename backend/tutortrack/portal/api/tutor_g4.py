"""Tutor app endpoints from gap batch G4 (FR-16-2/3/4): planning lessons with conflict
feedback, the previous report on the lesson page and a student's lesson history."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from tutortrack.scheduling.api.serializers import ConflictSerializer, LessonResultSerializer

from .. import tutor_lessons
from .tutor_views import TutorView


class TutorJobSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    service = serializers.CharField()
    duration_minutes = serializers.IntegerField()
    online = serializers.BooleanField()
    location = serializers.CharField(allow_blank=True)
    students = serializers.ListField(child=serializers.DictField(child=serializers.CharField()))


class TutorLessonCheckSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    job = serializers.UUIDField(required=False, allow_null=True, default=None)
    lesson = serializers.UUIDField(required=False, allow_null=True, default=None)


class TutorLessonCreateSerializer(serializers.Serializer):
    job = serializers.UUIDField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    notes_for_tutor = serializers.CharField(required=False, allow_blank=True, default="")


class TutorLessonMoveSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)


class ReportAnswerSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    value = serializers.JSONField()


class PreviousReportSerializer(serializers.Serializer):
    id = serializers.CharField()
    lesson_id = serializers.CharField()
    lesson_title = serializers.CharField()
    lesson_start = serializers.DateTimeField()
    tutor = serializers.CharField()
    status = serializers.CharField()
    answers = ReportAnswerSerializer(many=True)


class PreviousReportResultSerializer(serializers.Serializer):
    report = PreviousReportSerializer(allow_null=True)


class StudentLessonSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    service = serializers.CharField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    status = serializers.CharField()
    outcome = serializers.CharField(allow_blank=True)
    report_id = serializers.CharField(allow_null=True)
    report_status = serializers.CharField(allow_blank=True)


class StudentHistorySerializer(serializers.Serializer):
    student = serializers.DictField(child=serializers.CharField(allow_blank=True))
    lessons = StudentLessonSerializer(many=True)
    attendance_percent = serializers.IntegerField(allow_null=True)


def _result(result: Any, request: Request) -> dict[str, Any]:
    from tutortrack.scheduling.api.views import _result as lesson_result

    return lesson_result(result, request)


class TutorJobsView(TutorView):
    """The tutor's active jobs a lesson can be booked on."""

    @extend_schema(responses=TutorJobSerializer(many=True))
    def get(self, request: Request) -> Response:
        rows = tutor_lessons.bookable_jobs(self.tutor(request))
        return Response(TutorJobSerializer(rows, many=True).data)


class TutorLessonCheckView(TutorView):
    """Conflicts for a proposed time (nothing is saved): a new lesson on ``job`` or a
    move of ``lesson``."""

    @extend_schema(
        request=TutorLessonCheckSerializer,
        responses=ConflictSerializer(many=True),
        examples=[
            OpenApiExample(
                "Move",
                value={
                    "lesson": "…",
                    "start": "2026-11-02T16:00:00Z",
                    "end": "2026-11-02T17:00:00Z",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        payload = TutorLessonCheckSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        found = tutor_lessons.check(
            request.user,
            self.tutor(request),
            start=data["start"],
            end=data["end"],
            job_id=data["job"],
            lesson_id=data["lesson"],
        )
        return Response(ConflictSerializer(found, many=True).data)


class TutorLessonsView(TutorView):
    """Book a lesson on one of your jobs (needs the organisation's "tutors can create
    lessons" setting). A hard conflict returns 422 with ``conflicts``."""

    @extend_schema(request=TutorLessonCreateSerializer, responses={201: LessonResultSerializer})
    def post(self, request: Request) -> Response:
        payload = TutorLessonCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        result = tutor_lessons.create(
            request.user,
            self.tutor(request),
            job_id=data["job"],
            start=data["start"],
            end=data["end"],
            notes_for_tutor=data["notes_for_tutor"],
        )
        return Response(_result(result, request), status=201)


class TutorLessonMoveView(TutorView):
    """Move your planned lesson (needs "tutors can reschedule lessons"; otherwise send a
    reschedule request). A hard conflict returns 422 with ``conflicts``."""

    @extend_schema(request=TutorLessonMoveSerializer, responses=LessonResultSerializer)
    def post(self, request: Request, lesson_id: Any) -> Response:
        self.tutor(request)
        payload = TutorLessonMoveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        result = tutor_lessons.move(
            request.user,
            lesson_id=lesson_id,
            start=data["start"],
            end=data["end"],
            reason=data["reason"],
        )
        return Response(_result(result, request))


class TutorPreviousReportView(TutorView):
    """The latest earlier report for this lesson's student(s) that you may read."""

    @extend_schema(responses=PreviousReportResultSerializer)
    def get(self, request: Request, lesson_id: Any) -> Response:
        self.tutor(request)
        report = tutor_lessons.previous_report(request.user, lesson_id)
        return Response(PreviousReportResultSerializer({"report": report}).data)


class TutorStudentLessonsView(TutorView):
    """A student's lessons with you (newest first), attendance and your reports."""

    @extend_schema(responses=StudentHistorySerializer)
    def get(self, request: Request, student_id: Any) -> Response:
        data = tutor_lessons.student_history(request.user, self.tutor(request), student_id)
        return Response(StudentHistorySerializer(data).data)
