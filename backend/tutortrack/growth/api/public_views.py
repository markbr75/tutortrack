"""Public pages for E25: the review page families reach from the request email (FR-25-1)
and referral/affiliate link tracking for the website (FR-25-2/3). Anonymous,
tenant-resolved by host and rate-limited."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from .. import services
from ..models import AffiliateLink, ReviewRequest
from . import serializers as s


class PublicView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_widget"


def _page(request: ReviewRequest) -> dict[str, Any]:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    tutor = request.tutor
    return {
        "organisation": org.name,
        "tutor": (tutor.display_name or tutor.first_name) if tutor else "",
        "student": request.student.first_name if request.student else "",
        "reviewer_name": request.contact.first_name if request.contact else "",
        "criteria": services.criteria_keys(),
        "open": request.status in services.OPEN_REQUESTS and request.expires_at > now(),
        "status": request.status,
    }


class PublicReviewView(PublicView):
    @extend_schema(tags=["public"], responses=s.PublicReviewPageSerializer)
    def get(self, request: Request, token: str) -> Response:
        """The review form behind the link in the review request email."""
        return Response(s.PublicReviewPageSerializer(_page(services.request_for_token(token))).data)

    @extend_schema(
        tags=["public"],
        request=s.PublicReviewSubmitSerializer,
        responses={201: s.PublicReviewThanksSerializer},
        examples=[
            OpenApiExample(
                "Five stars",
                request_only=True,
                value={
                    "rating": 5,
                    "criteria": {"communication": 5, "knowledge": 5},
                    "text": "Patient, clear and always prepared.",
                    "reviewer_name": "Priya",
                    "publish_consent": True,
                },
            )
        ],
    )
    def post(self, request: Request, token: str) -> Response:
        """Submit the review. 4-5 star reviewers get the Google review link back."""
        review_request = services.request_for_token(token)
        payload = s.PublicReviewSubmitSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        review = services.submit_review(review_request, **payload.validated_data)
        body = {"status": "submitted", "google_review_url": services.google_prompt_url(review)}
        return Response(s.PublicReviewThanksSerializer(body).data, status=201)


class PublicRefView(PublicView):
    @extend_schema(
        tags=["public"],
        request=s.PublicRefSerializer,
        responses=s.PublicRefResultSerializer,
        examples=[OpenApiExample("A shared link", request_only=True, value={"code": "K7M2Q9XA"})],
    )
    def post(self, request: Request) -> Response:
        """A visit through a referral or affiliate link: counts the click and tells the
        website how long to remember the code (it is sent with the enquiry as ``utm.ref``)."""
        payload = s.PublicRefSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        found = services.record_click(payload.validated_data["code"])
        days = int(get_setting("growth.attribution_days"))
        if found is None:
            body = {"valid": False, "kind": "", "landing_path": "", "remember_days": 0, "offer": ""}
            return Response(s.PublicRefResultSerializer(body).data)
        offer = ""
        if isinstance(found, AffiliateLink):
            kind, landing = "affiliate", found.landing_path or "/"
        else:
            kind, landing = ("tutor" if found.tutor_id else "referral"), "/"
            program = services.active_program()
            if found.client_id and program is not None and program.referee_discount_percent:
                offer = f"{services.percent_text(program.referee_discount_percent)}%"
        body = {
            "valid": True,
            "kind": kind,
            "landing_path": landing,
            "remember_days": days,
            "offer": offer,
        }
        return Response(s.PublicRefResultSerializer(body).data)
