"""``/public/uploads``: anonymous uploads for public forms (G5a, ``core.storage.public``)."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from ..storage import public


class PublicUploadRequestSerializer(serializers.Serializer):
    target = serializers.ChoiceField(
        choices=["form", "opening"],
        help_text="`form` for an enquiry or registration form, `opening` for a job opening.",
    )
    slug = serializers.SlugField(max_length=80, help_text="The form or opening slug.")
    kind = serializers.ChoiceField(choices=public.KIND_CHOICES)
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=127)
    size_bytes = serializers.IntegerField(min_value=1)


class PublicUploadTargetSerializer(serializers.Serializer):
    url = serializers.URLField()
    method = serializers.CharField()
    headers = serializers.DictField(child=serializers.CharField())
    expires_in = serializers.IntegerField()


class PublicUploadCreatedSerializer(serializers.Serializer):
    token = serializers.CharField(help_text="Send this as the file field's answer.")
    upload = PublicUploadTargetSerializer()
    max_bytes = serializers.IntegerField()


class PublicUploadCompleteSerializer(serializers.Serializer):
    token = serializers.CharField()


class PublicUploadedFileSerializer(serializers.Serializer):
    token = serializers.CharField()
    filename = serializers.CharField()
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField()


class AttachedFileSerializer(serializers.Serializer):
    """A file attached to a record (open it with ``GET /files/{id}/download``)."""

    id = serializers.UUIDField()
    filename = serializers.CharField()
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField()
    is_downloadable = serializers.BooleanField()


def _organisation(request: Request) -> Any:
    org = getattr(request, "organisation", None)
    if org is None:
        raise NotFound()
    return org


class PublicUploadView(APIView):
    """Start an upload for a public form's file field: returns a presigned PUT and the token
    the form submission carries. Throttled per IP (``public_upload``)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_upload"

    @extend_schema(
        request=PublicUploadRequestSerializer,
        responses={201: PublicUploadCreatedSerializer},
        examples=[
            OpenApiExample(
                "A CV for a job opening",
                value={
                    "target": "opening",
                    "slug": "maths-tutors-leeds",
                    "kind": "cv",
                    "filename": "Nia Okafor CV.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 182044,
                },
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        _organisation(request)
        payload = PublicUploadRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        _stored, upload, token = public.create(
            context=d["target"],
            reference=d["slug"],
            kind=d["kind"],
            filename=d["filename"],
            content_type=d["content_type"],
            size_bytes=d["size_bytes"],
        )
        return Response(
            {"token": token, "upload": upload.__dict__, "max_bytes": public.max_bytes(d["kind"])},
            status=status.HTTP_201_CREATED,
        )


class PublicUploadCompleteView(APIView):
    """Finish an upload: the file's size, type and signature are checked and it is queued for
    the malware scan."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_upload"

    @extend_schema(request=PublicUploadCompleteSerializer, responses=PublicUploadedFileSerializer)
    def post(self, request: Request) -> Response:
        _organisation(request)
        payload = PublicUploadCompleteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        token = payload.validated_data["token"]
        stored = public.complete(token)
        return Response(
            {
                "token": token,
                "filename": stored.filename,
                "content_type": stored.content_type,
                "size_bytes": stored.size_bytes,
            }
        )
