"""DPA acceptance, the sub-processor list, ``security.txt`` and the portal's own data
requests (E29-T05, T11, T12)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.permissions import HasOrganisation, HasPermission
from tutortrack.core.time import now

from .. import compliance, dsar, selectors
from ..models import DataSubjectRequest
from . import serializers as s

AUTH: list[Any] = [IsAuthenticated, HasOrganisation]


class DPAView(APIView):
    """The organisation's Data Processing Agreement with TutorTrack (versioned)."""

    permission_classes = [*AUTH, HasPermission.for_("privacy.dpa.manage")]

    @extend_schema(responses=s.DPAStatusSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.DPAStatusSerializer(compliance.dpa_status()).data)

    @extend_schema(
        request=s.AcceptDPASerializer,
        responses=s.DPAStatusSerializer,
        examples=[
            OpenApiExample(
                "Owner accepts",
                value={
                    "version": compliance.DPA_VERSION,
                    "signer_name": "Sam Patel",
                    "signer_title": "Director",
                    "company_name": "Bright Minds Tutoring Ltd",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        payload = s.AcceptDPASerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        compliance.accept_dpa(user=request.user, **payload.validated_data)
        return Response(s.DPAStatusSerializer(compliance.dpa_status()).data)


class SubprocessorsView(APIView):
    """TutorTrack's sub-processors (public; ``?region=`` filters to one regional stack)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        parameters=[OpenApiParameter("region", str, enum=["uk", "eu", "us", "au"])],
        responses=s.SubprocessorListSerializer,
    )
    def get(self, request: Request) -> Response:
        region = request.query_params.get("region") or None
        return Response(
            s.SubprocessorListSerializer(
                {
                    "version": compliance.SUBPROCESSORS_VERSION,
                    "subprocessors": compliance.subprocessors(region),
                }
            ).data
        )


def security_txt(request: HttpRequest) -> HttpResponse:
    """RFC 9116 ``/.well-known/security.txt`` (vulnerability disclosure, E29-T12)."""
    expires = (now() + timedelta(days=180)).replace(microsecond=0).isoformat()
    lines = [
        f"Contact: mailto:{settings.SECURITY_CONTACT_EMAIL}",
        f"Expires: {expires}",
        "Preferred-Languages: en",
        f"Policy: {settings.SECURITY_POLICY_URL}",
        f"Canonical: {settings.APP_URL.rstrip('/')}/.well-known/security.txt",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")


# --- the portal: my own data requests -----------------------------------------------------------


class MyDataRequestsView(APIView):
    """Ask for a copy of your data or for it to be erased (parents can ask for their child)."""

    permission_classes = AUTH

    @extend_schema(responses=s.MyDataRequestSerializer(many=True))
    def get(self, request: Request) -> Response:
        rows = selectors.my_data_requests(request.user)[:50]
        return Response(s.MyDataRequestSerializer(rows, many=True).data)

    @extend_schema(
        request=s.MyDataRequestCreateSerializer,
        responses={201: s.MyDataRequestSerializer},
        examples=[OpenApiExample("A copy of my data", value={"kind": "access"}, request_only=True)],
    )
    def post(self, request: Request) -> Response:
        from tutortrack.people.models import Contact, Student

        payload = s.MyDataRequestCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        user: Any = request.user
        subject_type, subject_id, relationship = "identity.user", str(user.pk), "self"
        if data.get("student_id"):
            contact = Contact.objects.filter(user=user).first()
            student = Student.objects.filter(
                pk=data["student_id"], client_id=getattr(contact, "client_id", None)
            ).first()
            if contact is None or student is None:
                raise NotFound(_("Student not found."))
            subject_type, subject_id = "people.student", str(student.pk)
            relationship = DataSubjectRequest.Relationship.PARENT
        created = dsar.log_request(
            kind=data["kind"],
            subject_type=subject_type,
            subject_id=subject_id,
            requester_name=user.get_full_name() or user.email,
            requester_email=user.email,
            relationship=relationship,
            channel=DataSubjectRequest.Channel.PORTAL,
            details=data.get("details", ""),
            requester_user=user,
        )
        return Response(s.MyDataRequestSerializer(created).data, status=status.HTTP_201_CREATED)
