"""Online lesson attendance, recordings and classroom API (E22-T10)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.permissions import HasMethodPermission, has_perm, scope_queryset
from tutortrack.scheduling.models import Lesson

from .. import video
from ..models import LessonRecording
from .views import AUTH


class AttendanceStudentSerializer(serializers.Serializer):
    attendee_id = serializers.UUIDField()
    student_id = serializers.UUIDField()
    name = serializers.CharField()
    suggested_outcome = serializers.CharField()
    late_minutes = serializers.IntegerField(allow_null=True)
    minutes_attended = serializers.IntegerField()
    first_joined_at = serializers.DateTimeField(allow_null=True)
    last_left_at = serializers.DateTimeField(allow_null=True)


class VideoAttendanceSerializer(serializers.Serializer):
    available = serializers.BooleanField()
    students = AttendanceStudentSerializer(many=True)
    actual_minutes = serializers.IntegerField(allow_null=True)
    tutor_minutes = serializers.IntegerField(required=False)
    guests = serializers.IntegerField()


class LessonRecordingSerializer(serializers.ModelSerializer):
    lesson_title = serializers.CharField(source="lesson.title", read_only=True)
    lesson_start = serializers.DateTimeField(source="lesson.start", read_only=True)

    class Meta:
        model = LessonRecording
        fields = [
            "id",
            "lesson",
            "lesson_title",
            "lesson_start",
            "provider",
            "status",
            "started_at",
            "duration_seconds",
            "size_bytes",
            "file_type",
            "missing_consent",
            "shared_with_family",
            "deleted_at",
            "deleted_reason",
            "created_at",
        ]
        read_only_fields = fields


class RecordingUpdateSerializer(serializers.Serializer):
    release = serializers.BooleanField(required=False)
    share_with_family = serializers.BooleanField(required=False)


class RecordingLinkSerializer(serializers.Serializer):
    url = serializers.CharField()
    password = serializers.CharField(allow_blank=True)
    expires_in = serializers.IntegerField()


class ClassroomResourceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()


class ClassroomSerializer(serializers.Serializer):
    lesson_id = serializers.UUIDField()
    title = serializers.CharField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    role = serializers.ChoiceField(choices=["tutor", "family", "staff"])
    provider = serializers.CharField(allow_blank=True)
    embeddable = serializers.BooleanField()
    join_url = serializers.CharField(allow_blank=True)
    opens_at = serializers.DateTimeField(allow_null=True)
    open = serializers.BooleanField()
    safeguarding_banner = serializers.CharField()
    recording = serializers.BooleanField()
    consent_needed = serializers.ListField(child=serializers.UUIDField())
    resources = ClassroomResourceSerializer(many=True)


class ClassroomConsentSerializer(serializers.Serializer):
    student_ids = serializers.ListField(child=serializers.UUIDField(), required=False)


class ClassroomConsentOutSerializer(serializers.Serializer):
    consented = serializers.ListField(child=serializers.UUIDField())


def _visible_lesson(request: Request, pk: Any) -> Lesson:
    lessons = scope_queryset(request.user, Lesson.objects.all(), "scheduling.lesson.view")
    return get_object_or_404(lessons, pk=pk)


class VideoAttendanceView(APIView):
    """``GET /lessons/{id}/video-attendance``: the register suggested by who joined the
    online lesson, and its actual length (pre-fills the tutor's register)."""

    permission_classes = [*AUTH, HasMethodPermission.for_({"GET": "scheduling.lesson.view"})]

    @extend_schema(
        responses=VideoAttendanceSerializer,
        examples=[
            OpenApiExample(
                "One student 7 minutes late",
                value={
                    "available": True,
                    "actual_minutes": 52,
                    "tutor_minutes": 60,
                    "guests": 0,
                    "students": [
                        {
                            "attendee_id": "0c8f9a8e-0f43-4a59-9bb1-0ad0f6d2a7d1",
                            "student_id": "a1c1e0f2-1d0c-4c73-9a51-0d9c46f3d0b7",
                            "name": "Sam Patel",
                            "suggested_outcome": "late",
                            "late_minutes": 7,
                            "minutes_attended": 52,
                            "first_joined_at": "2026-10-14T16:07:00Z",
                            "last_left_at": "2026-10-14T16:59:00Z",
                        }
                    ],
                },
                response_only=True,
            )
        ],
    )
    def get(self, request: Request, pk: str) -> Response:
        lesson = _visible_lesson(request, pk)
        return Response(VideoAttendanceSerializer(video.attendance_suggestions(lesson)).data)


class LessonRecordingViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """``/recordings``: recordings of online lessons. Tutors see their own lessons'
    available recordings; ``video.recording.manage`` sees and manages all."""

    model = LessonRecording
    serializer_class = LessonRecordingSerializer
    permission_classes = [*AUTH, HasMethodPermission.for_({"GET": "video.recording.view"})]

    def get_tenant_queryset(self) -> Any:
        qs = LessonRecording.objects.select_related("lesson")
        lesson = self.request.query_params.get("lesson")
        if lesson:
            qs = qs.filter(lesson_id=lesson)
        if has_perm(self.request.user, "video.recording.manage"):
            return qs
        visible = scope_queryset(self.request.user, qs, "video.recording.view")
        return visible.filter(status=LessonRecording.Status.AVAILABLE).distinct()

    @extend_schema(parameters=[OpenApiParameter("lesson", str)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(request=RecordingUpdateSerializer, responses=LessonRecordingSerializer)
    def partial_update(self, request: Request, pk: Any = None) -> Response:
        payload = RecordingUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        recording = video.update_recording(
            get_object_or_404(self.get_tenant_queryset(), pk=pk),
            user=request.user,
            **payload.validated_data,
        )
        return Response(LessonRecordingSerializer(recording).data)

    def destroy(self, request: Request, pk: Any = None) -> Response:
        recording = get_object_or_404(self.get_tenant_queryset(), pk=pk)
        video.delete_recording(recording, reason="deleted by staff", user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_permissions(self) -> Sequence[Any]:
        if self.action in ("partial_update", "destroy"):
            return [
                *(p() for p in AUTH),
                HasMethodPermission.for_(
                    {"PATCH": "video.recording.manage", "DELETE": "video.recording.manage"}
                )(),
            ]
        return super().get_permissions()

    http_method_names = ["get", "patch", "delete", "head", "options"]


class RecordingPlayView(APIView):
    """``GET /recordings/{id}/play``: a playback link after an access check (staff, the
    lesson's tutor, or the family when shared); every read is audited."""

    permission_classes = AUTH

    @extend_schema(responses=RecordingLinkSerializer)
    def get(self, request: Request, pk: str) -> Response:
        recording = get_object_or_404(LessonRecording.objects.select_related("lesson"), pk=pk)
        response = Response(video.recording_link(recording, user=request.user))
        response["Cache-Control"] = "no-store"
        return response


class MyRecordingsView(APIView):
    """``GET /me/recordings``: recordings shared with the signed-in family."""

    permission_classes = AUTH

    @extend_schema(responses=LessonRecordingSerializer(many=True))
    def get(self, request: Request) -> Response:
        from tutortrack.portal.household import household_for

        household = household_for(request.user)
        if household is None:
            raise PermissionDenied()
        rows = (
            LessonRecording.objects.filter(
                status=LessonRecording.Status.AVAILABLE,
                shared_with_family=True,
                lesson__attendees__student_id__in=household.student_ids,
            )
            .select_related("lesson")
            .distinct()[:100]
        )
        return Response(LessonRecordingSerializer(rows, many=True).data)


class ClassroomView(APIView):
    """``GET /lessons/{id}/classroom``: the in-app classroom (FR-22-5) for the lesson's
    tutor, its families or staff."""

    permission_classes = AUTH

    @extend_schema(responses=ClassroomSerializer)
    def get(self, request: Request, pk: str) -> Response:
        lesson = get_object_or_404(Lesson.objects.all(), pk=pk)
        return Response(ClassroomSerializer(video.classroom(lesson, user=request.user)).data)


class ClassroomConsentView(APIView):
    """``POST /lessons/{id}/classroom/consent``: a family agrees to recording (E29 consent
    record) from the classroom prompt."""

    permission_classes = AUTH

    @extend_schema(request=ClassroomConsentSerializer, responses=ClassroomConsentOutSerializer)
    def post(self, request: Request, pk: str) -> Response:
        payload = ClassroomConsentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lesson = get_object_or_404(Lesson.objects.all(), pk=pk)
        ids = [str(i) for i in payload.validated_data.get("student_ids", [])]
        done = video.give_recording_consent(lesson, user=request.user, student_ids=ids)
        return Response({"consented": done})
