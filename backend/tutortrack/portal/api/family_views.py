"""Portal household self-service (gap batch G2): household switcher (FR-15-1), inviting
another guardian (FR-15-8), guardian-managed student logins (FR-15-1) and documents to sign
(FR-15-8, FR-05-9), plus the tutor's documents to sign (FR-18-5)."""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tutortrack.core.context import require_organisation_id
from tutortrack.core.exceptions import NotFound
from tutortrack.crm.models import Document, Note

from .. import family
from ..household import Household
from .tutor_views import TutorView
from .views import HOUSEHOLD_SESSION_KEY, PortalView

# --- serializers ----------------------------------------------------------------------------------


class HouseholdChoiceSerializer(serializers.Serializer):
    client_id = serializers.CharField(allow_blank=True, help_text="Blank shows every household.")


class GuardianSerializer(serializers.Serializer):
    id = serializers.CharField()
    client_id = serializers.CharField()
    name = serializers.CharField()
    relationship = serializers.CharField()
    portal = serializers.ChoiceField(choices=["active", "invited", "none"])


class GuardianInviteSerializer(serializers.Serializer):
    client_id = serializers.CharField(required=False, allow_blank=True)
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    email = serializers.EmailField()
    relationship = serializers.ChoiceField(choices=sorted(family.INVITABLE), default="guardian")
    confirm = serializers.BooleanField(
        help_text="They have parental responsibility or the inviter's permission."
    )


class StudentLoginSerializer(serializers.Serializer):
    student_id = serializers.CharField()
    student_name = serializers.CharField()
    eligible = serializers.BooleanField(help_text="Under 13 (or no date of birth on record).")
    has_email_login = serializers.BooleanField()
    username = serializers.CharField(allow_blank=True)
    pin_changed_at = serializers.DateTimeField(allow_null=True)


class StudentLoginCreateSerializer(serializers.Serializer):
    student_id = serializers.CharField()
    username = serializers.CharField(max_length=40)
    pin = serializers.CharField(write_only=True, trim_whitespace=False, max_length=64)
    parental_consent = serializers.BooleanField(default=False)


class StudentPinSerializer(serializers.Serializer):
    pin = serializers.CharField(write_only=True, trim_whitespace=False, max_length=64)


class StudentSignInSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=40)
    pin = serializers.CharField(write_only=True, trim_whitespace=False, max_length=64)


class SignedInSerializer(serializers.Serializer):
    signed_in = serializers.BooleanField()


class PortalDocumentSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    category = serializers.CharField()
    filename = serializers.CharField()
    signature_required = serializers.BooleanField()
    signature_status = serializers.ChoiceField(choices=["not_required", "awaiting", "signed"])
    signed_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class SignSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=200)
    agree = serializers.BooleanField()


class SignedSerializer(serializers.Serializer):
    signature_id = serializers.CharField()
    signed_at = serializers.DateTimeField()
    content_sha256 = serializers.CharField()


class DocumentDownloadSerializer(serializers.Serializer):
    url = serializers.CharField()
    expires_in = serializers.IntegerField()


def _valid(serializer_class: type[serializers.Serializer], request: Request) -> dict[str, Any]:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def _document_rows(qs: QuerySet[Document]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(d.pk),
            "title": d.title,
            "category": d.category,
            "filename": d.file.filename,
            "signature_required": d.signature_required,
            "signature_status": d.signature_status,
            "signed_at": d.signed_at,
            "created_at": d.created_at,
        }
        for d in qs.select_related("file")
    ]


def _signed(signature: Any) -> Response:
    return Response(
        {
            "signature_id": str(signature.pk),
            "signed_at": signature.signed_at,
            "content_sha256": signature.content_sha256,
        },
        status=status.HTTP_201_CREATED,
    )


def _agreed(data: dict[str, Any]) -> None:
    if not data["agree"]:
        raise serializers.ValidationError({"agree": ["Tick to confirm you agree."]})


# --- household switcher (FR-15-1) -----------------------------------------------------------------


class HouseholdSwitchView(PortalView):
    """Pick the household the portal shows (people linked to several households)."""

    @extend_schema(
        request=HouseholdChoiceSerializer,
        responses=HouseholdChoiceSerializer,
        examples=[OpenApiExample("Switch", value={"client_id": "1f0c..."}, request_only=True)],
    )
    def post(self, request: Request) -> Response:
        household = self.client_household(request)
        client_id = _valid(HouseholdChoiceSerializer, request)["client_id"]
        if client_id and client_id not in {str(c.pk) for c in household.all_clients}:
            raise NotFound()
        request.session[HOUSEHOLD_SESSION_KEY] = client_id
        return Response({"client_id": client_id})


# --- guardians (FR-15-8) --------------------------------------------------------------------------


class GuardiansView(PortalView):
    def _household(self, request: Request) -> Household:
        return self.client_household(request, "portal.client.profile")

    @extend_schema(responses=GuardianSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(family.guardians(self._household(request)))

    @extend_schema(
        request=GuardianInviteSerializer,
        responses={201: GuardianSerializer},
        examples=[
            OpenApiExample(
                "Invite a guardian",
                value={
                    "first_name": "Raj",
                    "last_name": "Patel",
                    "email": "raj@example.com",
                    "relationship": "parent",
                    "confirm": True,
                },
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        household = self._household(request)
        data = _valid(GuardianInviteSerializer, request)
        client_id = data.pop("client_id", "") or (
            str(household.clients[0].pk) if len(household.clients) == 1 else ""
        )
        contact = family.invite_guardian(household, client_id=client_id, **data)
        row = next(r for r in family.guardians(household) if r["id"] == str(contact.pk))
        return Response(row, status=status.HTTP_201_CREATED)


# --- guardian-managed student logins (FR-15-1) ----------------------------------------------------


class StudentLoginsView(PortalView):
    def _household(self, request: Request) -> Household:
        return self.client_household(request, "portal.client.profile")

    @extend_schema(responses=StudentLoginSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(family.logins(self._household(request)))

    @extend_schema(
        request=StudentLoginCreateSerializer,
        responses={201: StudentLoginSerializer},
        examples=[
            OpenApiExample(
                "Create a login",
                value={
                    "student_id": "5b1e...",
                    "username": "maya.p",
                    "pin": "482916",
                    "parental_consent": True,
                },
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        household = self._household(request)
        data = _valid(StudentLoginCreateSerializer, request)
        family.create_login(household, user=request.user, **data)
        row = next(r for r in family.logins(household) if r["student_id"] == data["student_id"])
        return Response(row, status=status.HTTP_201_CREATED)


class StudentLoginDetailView(PortalView):
    @extend_schema(request=None, responses={204: None})
    def delete(self, request: Request, student_id: str) -> Response:
        household = self.client_household(request, "portal.client.profile")
        family.remove_login(household, student_id=student_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentLoginPinView(PortalView):
    @extend_schema(request=StudentPinSerializer, responses=StudentLoginSerializer)
    def post(self, request: Request, student_id: str) -> Response:
        household = self.client_household(request, "portal.client.profile")
        family.change_pin(
            household, student_id=student_id, pin=_valid(StudentPinSerializer, request)["pin"]
        )
        row = next(r for r in family.logins(household) if r["student_id"] == str(student_id))
        return Response(row)


class StudentSignInView(APIView):
    """A child signs in with the username and PIN their guardian set (organisation host)."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        request=StudentSignInSerializer,
        responses=SignedInSerializer,
        examples=[
            OpenApiExample(
                "Sign in", value={"username": "maya.p", "pin": "482916"}, request_only=True
            )
        ],
    )
    def post(self, request: Request) -> Response:
        require_organisation_id()
        data = _valid(StudentSignInSerializer, request)
        family.sign_in(request._request, data["username"], data["pin"])
        return Response({"signed_in": True})


# --- documents to sign (FR-15-8, FR-05-9) ---------------------------------------------------------


def _household_documents(household: Household) -> QuerySet[Document]:
    about = Q(target_type="people.client", target_id__in=[str(i) for i in household.client_ids])
    about |= Q(target_type="people.student", target_id__in=[str(i) for i in household.student_ids])
    return Document.objects.filter(about, visibility=Note.Visibility.CLIENT)


class PortalDocumentsView(PortalView):
    @extend_schema(responses=PortalDocumentSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(_document_rows(_household_documents(self.client_household(request))))


class PortalDocumentDownloadView(PortalView):
    @extend_schema(responses=DocumentDownloadSerializer)
    def get(self, request: Request, document_id: str) -> Response:
        from tutortrack.core.storage.services import presign_download

        document = (
            _household_documents(self.client_household(request)).filter(pk=document_id).first()
        )
        if document is None:
            raise NotFound()
        url, expires = presign_download(document.file)
        return Response({"url": url, "expires_in": expires})


class PortalDocumentSignView(PortalView):
    @extend_schema(
        request=SignSerializer,
        responses={201: SignedSerializer},
        examples=[
            OpenApiExample(
                "Sign", value={"full_name": "Priya Patel", "agree": True}, request_only=True
            )
        ],
    )
    def post(self, request: Request, document_id: str) -> Response:
        from tutortrack.crm import signing

        household = self.client_household(request, "portal.client.profile")
        document = _household_documents(household).filter(pk=document_id).first()
        if document is None:
            raise NotFound()
        data = _valid(SignSerializer, request)
        _agreed(data)
        signature = signing.sign_document(
            document, signer=request.user, full_name=data["full_name"], role="client"
        )
        return _signed(signature)


# --- the tutor's documents (FR-18-5) --------------------------------------------------------------


def _tutor_documents(tutor: Any) -> QuerySet[Document]:
    return Document.objects.filter(target_type="people.tutor", target_id=str(tutor.pk)).exclude(
        visibility=Note.Visibility.STAFF
    )


class TutorDocumentsView(TutorView):
    @extend_schema(responses=PortalDocumentSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(_document_rows(_tutor_documents(self.tutor(request))))


class TutorDocumentSignView(TutorView):
    @extend_schema(request=SignSerializer, responses={201: SignedSerializer})
    def post(self, request: Request, document_id: str) -> Response:
        from tutortrack.crm import signing

        document = _tutor_documents(self.tutor(request)).filter(pk=document_id).first()
        if document is None:
            raise NotFound()
        data = _valid(SignSerializer, request)
        _agreed(data)
        signature = signing.sign_document(
            document, signer=request.user, full_name=data["full_name"], role="tutor"
        )
        return _signed(signature)


class TutorDocumentDownloadView(TutorView):
    @extend_schema(responses=DocumentDownloadSerializer)
    def get(self, request: Request, document_id: str) -> Response:
        from tutortrack.core.storage.services import presign_download

        document = _tutor_documents(self.tutor(request)).filter(pk=document_id).first()
        if document is None:
            raise NotFound()
        url, expires = presign_download(document.file)
        return Response({"url": url, "expires_in": expires})
