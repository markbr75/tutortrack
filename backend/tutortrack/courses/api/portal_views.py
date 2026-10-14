"""Client portal pages for classes (E15 pages on E20): the class catalogue, enrolling a
household student (with payment at enrolment), the household's enrolments, waitlist
positions and next term's re-enrolment answers. Every view resolves the household first,
so other families' students and offers are 404s."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from tutortrack.core.exceptions import NotFound
from tutortrack.portal.api.views import PortalView
from tutortrack.portal.household import Household
from tutortrack.tenancy.settings_service import get_setting

from .. import selectors, services
from ..models import Enrolment, RolloverOffer
from . import serializers as s
from .public_views import _public_class


class CoursePortalView(PortalView):
    def enrol_household(self, request: Request) -> Household:
        return self.client_household(request, "portal.client.enrol")

    def own_student(self, household: Household, student_id: Any) -> Any:
        student = next((x for x in household.students if str(x.pk) == str(student_id)), None)
        if student is None:
            raise NotFound()
        return student


class PortalCatalogueView(CoursePortalView):
    @extend_schema(responses=s.PublicCatalogueSerializer)
    def get(self, request: Request) -> Response:
        """Classes the household can enrol in (the public catalogue)."""
        self.household(request)
        body = {
            "classes": [selectors.public_card(c) for c in selectors.public_classes()[:100]],
            "terms": str(get_setting("courses.enrolment_terms") or ""),
            "payment": str(get_setting("courses.online_payment")),
        }
        return Response(s.PublicCatalogueSerializer(body).data)


def _enrolment_row(e: Enrolment) -> dict[str, Any]:
    gc = e.group_class
    return {
        "id": e.pk,
        "group_class": gc.pk,
        "class_name": gc.name,
        "course_name": gc.course.name,
        "term": gc.term.name,
        "student": e.student_id,
        "student_name": e.student.full_name,
        "status": e.status,
        "start_date": e.start_date,
        "end_date": e.end_date,
        "weekdays": selectors.meeting_days(gc),
        "start_time": gc.start_time.strftime("%H:%M"),
        "pay_url": services.pay_url(e),
        "hold_expires_at": e.hold_expires_at,
    }


class PortalCoursesView(CoursePortalView):
    @extend_schema(responses=s.PortalCoursesSerializer)
    def get(self, request: Request) -> Response:
        """The household's classes, waitlist places (with positions) and re-enrolment
        questions for next term."""
        from tutortrack.leads import services as leads
        from tutortrack.leads.models import WaitlistEntry

        from ..models import GroupClass

        household = self.household(request)
        enrolments = (
            Enrolment.objects.filter(student_id__in=household.student_ids)
            .select_related("group_class__course", "group_class__term", "student")
            .order_by("-start_date")
        )
        entries = (
            WaitlistEntry.objects.filter(
                student_id__in=household.student_ids,
                group_class_id__isnull=False,
                status__in=["waiting", "offered"],
            )
            .select_related("student")
            .order_by("created_at")
        )
        classes = {
            str(c.pk): c
            for c in GroupClass.objects.filter(
                pk__in=[e.group_class_id for e in entries]
            ).select_related("course")
        }
        waitlist = [
            {
                "id": e.pk,
                "group_class": e.group_class_id,
                "class_name": classes[str(e.group_class_id)].name,
                "course_name": classes[str(e.group_class_id)].course.name,
                "student_name": e.student.full_name,
                "status": e.status,
                "position": leads.position(e) if e.status == "waiting" else None,
                "offer_expires_at": e.offer_expires_at,
            }
            for e in entries
            if str(e.group_class_id) in classes
        ]
        offers = [
            {
                "id": o.pk,
                "student_name": o.student.full_name,
                "course_name": o.to_class.course.name,
                "class_name": o.to_class.name,
                "term": o.to_class.term.name,
                "status": o.status,
                "deadline": o.rollover.deadline,
                "mode": o.rollover.mode,
            }
            for o in RolloverOffer.objects.filter(
                student_id__in=household.student_ids, rollover__status="running"
            ).select_related("student", "to_class__course", "to_class__term", "rollover")
        ]
        body = {
            "enrolments": [_enrolment_row(e) for e in enrolments],
            "waitlist": waitlist,
            "rollover_offers": offers,
        }
        return Response(s.PortalCoursesSerializer(body).data)


class PortalEnrolView(CoursePortalView):
    @extend_schema(request=s.PortalEnrolSerializer, responses={201: s.PortalEnrolmentSerializer})
    def post(self, request: Request) -> Response:
        """Enrol one of the household's students (or join the waitlist when full). With
        payment at enrolment the place is held until ``pay_url`` is paid."""
        household = self.enrol_household(request)
        payload = s.PortalEnrolSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        student = self.own_student(household, data["student"])
        group_class = _public_class(data["group_class"])
        if data["join_waitlist"]:
            services.join_waitlist(group_class, student)
            return Response(status=status.HTTP_204_NO_CONTENT)
        with transaction.atomic():
            enrolment = services.enrol(
                group_class,
                student,
                source=Enrolment.Source.PORTAL,
                payment=str(get_setting("courses.online_payment")),
                accept_terms=data["accept_terms"],
                user=request.user,
            )
        enrolment.refresh_from_db()
        return Response(
            s.PortalEnrolmentSerializer(_enrolment_row(enrolment)).data,
            status=status.HTTP_201_CREATED,
        )


class PortalRolloverAnswerView(CoursePortalView):
    @extend_schema(request=s.RolloverAnswerSerializer, responses=s.PortalRolloverOfferSerializer)
    def post(self, request: Request, offer_id: Any) -> Response:
        """Keep (or give up) a place next term."""
        household = self.enrol_household(request)
        payload = s.RolloverAnswerSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        offer = (
            RolloverOffer.objects.filter(pk=offer_id, student_id__in=household.student_ids)
            .select_related("student", "to_class__course", "to_class__term", "rollover")
            .first()
        )
        if offer is None:
            raise NotFound()
        offer = services.respond_rollover(
            offer, confirm=payload.validated_data["confirm"], user=request.user
        )
        return Response(
            s.PortalRolloverOfferSerializer(
                {
                    "id": offer.pk,
                    "student_name": offer.student.full_name,
                    "course_name": offer.to_class.course.name,
                    "class_name": offer.to_class.name,
                    "term": offer.to_class.term.name,
                    "status": offer.status,
                    "deadline": offer.rollover.deadline,
                    "mode": offer.rollover.mode,
                }
            ).data
        )


class PortalEnrolmentCancelView(CoursePortalView):
    @extend_schema(request=None, responses=s.PortalEnrolmentSerializer)
    def post(self, request: Request, enrolment_id: Any) -> Response:
        """Give up a place that is still waiting for payment."""
        household = self.enrol_household(request)
        enrolment = Enrolment.objects.filter(
            pk=enrolment_id, student_id__in=household.student_ids
        ).first()
        if enrolment is None:
            raise NotFound()
        enrolment = services.cancel_pending(enrolment, user=request.user)
        return Response(s.PortalEnrolmentSerializer(_enrolment_row(enrolment)).data)
