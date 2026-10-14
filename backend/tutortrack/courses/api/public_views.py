"""Public class catalogue and online enrolment (E20-T09, FR-20-8) for the website widget
``<tt-class-catalogue>`` and hosted pages, plus the re-enrolment page families reach from
the rollover email. Anonymous, tenant-resolved by host, rate-limited; they expose only
public courses and open classes."""

from __future__ import annotations

import secrets
from typing import Any

from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tutortrack.core.captcha import verify_turnstile
from tutortrack.core.exceptions import NotFound
from tutortrack.core.middleware import client_ip
from tutortrack.tenancy.settings_service import get_setting

from .. import selectors, services
from ..models import Enrolment, GroupClass, TermRollover
from . import serializers as s


class PublicView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_widget"


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


@extend_schema(tags=["public"])
class PublicCatalogueView(PublicView):
    @extend_schema(
        parameters=[
            OpenApiParameter("subject", str, required=False, description="Subject name or id"),
            OpenApiParameter("age", int, required=False),
            OpenApiParameter("weekday", int, required=False, description="Monday = 0"),
            OpenApiParameter("location", str, required=False),
            OpenApiParameter("course", str, required=False),
        ],
        responses=s.PublicCatalogueSerializer,
    )
    def get(self, request: Request) -> Response:
        """Open classes of public courses with places left (FR-20-8)."""
        q = request.query_params
        rows = selectors.public_classes(
            subject=q.get("subject", ""),
            age=_int(q.get("age")),
            weekday=_int(q.get("weekday")),
            location=q.get("location", ""),
            course=q.get("course", ""),
        )
        body = {
            "classes": [selectors.public_card(c) for c in rows[:100]],
            "terms": str(get_setting("courses.enrolment_terms") or ""),
            "payment": str(get_setting("courses.online_payment")),
        }
        return Response(s.PublicCatalogueSerializer(body).data)


def _public_class(class_id: Any) -> GroupClass:
    found = next((c for c in selectors.public_classes() if str(c.pk) == str(class_id)), None)
    if found is None:
        raise NotFound()
    return found


def _status_body(enrolment: Enrolment, token: str = "") -> dict[str, Any]:
    return {
        "id": enrolment.pk,
        "status": enrolment.status,
        "class_name": enrolment.group_class.name,
        "course_name": enrolment.group_class.course.name,
        "student": enrolment.student.first_name,
        "start_date": enrolment.start_date,
        "pay_url": services.pay_url(enrolment),
        "hold_expires_at": enrolment.hold_expires_at,
        "token": token,
        "waitlist_position": None,
    }


@extend_schema(tags=["public"])
class PublicEnrolView(PublicView):
    @extend_schema(request=s.PublicEnrolSerializer, responses={201: s.PublicEnrolmentSerializer})
    def post(self, request: Request) -> Response:
        """Enrol a new family's child in a class (or join its waitlist when it is full).
        Keep ``token``: it opens the enrolment's status. When payment is due at enrolment
        the place is held until ``pay_url`` is paid."""
        payload = s.PublicEnrolSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        if not verify_turnstile(data.get("captcha", ""), client_ip(request)):
            raise ValidationError({"captcha": ["Please complete the check."]})
        group_class = _public_class(data["group_class"])
        if data["join_waitlist"]:
            return self._waitlist(group_class, data)
        enrolment, token = services.public_enrol(
            group_class,
            contact=dict(data["contact"]),
            student=dict(data["student"]),
            accept_terms=data["accept_terms"],
            consents=data.get("consents") or [],
        )
        return Response(
            s.PublicEnrolmentSerializer(_status_body(enrolment, token)).data,
            status=status.HTTP_201_CREATED,
        )

    def _waitlist(self, group_class: GroupClass, data: dict[str, Any]) -> Response:
        from tutortrack.leads import services as leads
        from tutortrack.people import services as people

        problems = services.eligibility_problems(
            group_class,
            date_of_birth=data["student"].get("date_of_birth"),
            year_group=data["student"].get("year_group", ""),
        )
        if problems:
            raise services.NotEligible(problems[0], extra={"code": "not_eligible"})
        with transaction.atomic():
            contact = data["contact"]
            student = data["student"]
            _client, person, created = people.quick_add_family(
                contact={
                    k: contact.get(k, "") for k in ("first_name", "last_name", "email", "phone")
                },
                students=[
                    {
                        k: v
                        for k, v in {
                            "first_name": student["first_name"],
                            "last_name": student.get("last_name") or contact["last_name"],
                            "date_of_birth": student.get("date_of_birth"),
                            "year_group": student.get("year_group", ""),
                        }.items()
                        if v not in (None, "")
                    }
                ],
            )
            entry = services.join_waitlist(group_class, created[0])
            services.capture_public_consent(
                group_class,
                person,
                created,
                accept_terms=data["accept_terms"],
                consents=data.get("consents") or [],
            )
        body = {
            "id": None,
            "status": "waitlisted",
            "class_name": group_class.name,
            "course_name": group_class.course.name,
            "student": created[0].first_name,
            "start_date": None,
            "pay_url": "",
            "hold_expires_at": None,
            "token": "",
            "waitlist_position": leads.position(entry),
        }
        return Response(s.PublicEnrolmentSerializer(body).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["public"])
class PublicEnrolmentStatusView(PublicView):
    @extend_schema(
        parameters=[OpenApiParameter("token", str, required=True)],
        responses=s.PublicEnrolmentSerializer,
    )
    def get(self, request: Request, enrolment_id: Any) -> Response:
        token = str(request.query_params.get("token") or "")
        enrolment = services.enrolment_for_token(token)
        if str(enrolment.pk) != str(enrolment_id):
            raise NotFound()
        return Response(s.PublicEnrolmentSerializer(_status_body(enrolment)).data)


@extend_schema(tags=["public"])
class PublicRolloverView(PublicView):
    def _offer(self, token: str) -> Any:
        if not token or len(token) > 100:
            raise NotFound()
        return services.offer_for_token(token)

    def _body(self, offer: Any) -> dict[str, Any]:
        rollover = offer.rollover
        target = offer.to_class
        return {
            "student": offer.student.first_name,
            "course_name": target.course.name,
            "class_name": target.name,
            "term": target.term.name,
            "starts": target.start_date,
            "start_time": target.start_time.strftime("%H:%M"),
            "status": offer.status,
            "deadline": rollover.deadline,
            "mode": rollover.mode,
            "open": rollover.status == TermRollover.Status.RUNNING
            and offer.status in ("pending", "confirmed", "declined"),
        }

    @extend_schema(responses=s.RolloverPageSerializer)
    def get(self, request: Request, token: str) -> Response:
        """Next term's place offered to a family (from the rollover email link)."""
        return Response(s.RolloverPageSerializer(self._body(self._offer(token))).data)

    @extend_schema(request=s.RolloverAnswerSerializer, responses=s.RolloverPageSerializer)
    def post(self, request: Request, token: str) -> Response:
        payload = s.RolloverAnswerSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        offer = self._offer(token)
        if not secrets.compare_digest(offer.token_hash, services._hash(token)):
            raise NotFound()
        offer = services.respond_rollover(offer, confirm=payload.validated_data["confirm"])
        offer.refresh_from_db()
        return Response(s.RolloverPageSerializer(self._body(offer)).data)
