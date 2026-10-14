"""Client portal self-booking and reschedule requests (E15 pages on the E08-T13/T14 engine).

Every view resolves the household first: students, lessons and bookings outside it are
404s. The engine (slots, holds, payment, approval, reschedule policies) is
``scheduling.services``.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from tutortrack.core.exceptions import FeatureDisabled, NotFound, PermissionDenied
from tutortrack.core.permissions import has_perm
from tutortrack.scheduling import services as scheduling
from tutortrack.scheduling.api import serializers as ss
from tutortrack.scheduling.api.views import (
    SLOT_PARAMS,
    booking_services_payload,
    booking_slots_payload,
)
from tutortrack.scheduling.models import BookingHold, RescheduleRequest

from ..household import Household
from .views import PortalView


class BookingView(PortalView):
    def booking_household(self, request: Request) -> Household:
        household = self.client_household(request, "portal.client.book")
        if not scheduling.booking_settings().enabled:
            raise FeatureDisabled("Online booking is turned off.")
        return household

    def own_hold(self, household: Household, request: Request, hold_id: Any) -> BookingHold:
        hold = BookingHold.objects.filter(pk=hold_id, student_id__in=household.student_ids).first()
        if hold is None:
            raise NotFound()
        return hold


class PortalBookingServicesView(BookingView):
    @extend_schema(responses=ss.BookingServiceSerializer(many=True))
    def get(self, request: Request) -> Response:
        self.booking_household(request)
        return Response(ss.BookingServiceSerializer(booking_services_payload(), many=True).data)


class PortalBookingSlotsView(BookingView):
    @extend_schema(parameters=SLOT_PARAMS, responses=ss.BookingSlotSerializer(many=True))
    def get(self, request: Request) -> Response:
        self.booking_household(request)
        return Response(ss.BookingSlotSerializer(booking_slots_payload(request), many=True).data)


class PortalBookingHoldsView(BookingView):
    @extend_schema(responses=ss.BookingHoldSerializer(many=True))
    def get(self, request: Request) -> Response:
        household = self.booking_household(request)
        holds = BookingHold.objects.filter(student_id__in=household.student_ids).select_related(
            "service", "tutor", "student"
        )[:50]
        return Response(ss.BookingHoldSerializer(holds, many=True).data)

    @extend_schema(request=ss.BookingHoldInput, responses={201: ss.BookingHoldSerializer})
    def post(self, request: Request) -> Response:
        """Hold a slot for one of the household's students."""
        from tutortrack.catalogue.models import Service
        from tutortrack.people.models import TutorProfile

        household = self.booking_household(request)
        payload = ss.BookingHoldInput(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        student = next((st for st in household.students if st.pk == data.get("student")), None)
        service = Service.objects.filter(
            pk=data["service"], active=True, bookable_online=True
        ).first()
        if student is None or service is None:
            raise NotFound()
        tutor = TutorProfile.objects.filter(pk=data["tutor"]).first() if data.get("tutor") else None
        hold, _token = scheduling.hold_slot(
            service=service,
            start=data["start"],
            tutor=tutor,
            student=student,
            promo_code=data["promo_code"],
            user=request.user,
        )
        return Response(ss.BookingHoldSerializer(hold).data, status=status.HTTP_201_CREATED)


class PortalBookingSubmitView(BookingView):
    @extend_schema(request=None, responses=ss.BookingSubmitResultSerializer)
    def post(self, request: Request, hold_id: Any) -> Response:
        household = self.booking_household(request)
        hold, pay_link = scheduling.submit_hold(self.own_hold(household, request, hold_id))
        hold.refresh_from_db()
        return Response({"booking": ss.BookingHoldSerializer(hold).data, "pay_url": pay_link})


class PortalBookingCancelView(BookingView):
    @extend_schema(request=None, responses=ss.BookingHoldSerializer)
    def post(self, request: Request, hold_id: Any) -> Response:
        household = self.booking_household(request)
        hold = scheduling.cancel_hold(self.own_hold(household, request, hold_id))
        hold.refresh_from_db()
        return Response(ss.BookingHoldSerializer(hold).data)


# --- reschedule requests ------------------------------------------------------------------------


class RescheduleView(PortalView):
    def reschedule_household(self, request: Request) -> Household:
        from tutortrack.tenancy.settings_service import get_setting

        household = self.client_household(request, "portal.client.reschedule")
        if not get_setting("scheduling.reschedule_requests"):
            raise FeatureDisabled("Reschedule requests are turned off.")
        return household


class PortalLessonRescheduleView(RescheduleView):
    @extend_schema(
        request=ss.LessonChangeProposal, responses={201: ss.LessonChangeRequestSerializer}
    )
    def post(self, request: Request, lesson_id: Any) -> Response:
        """Ask to move a household lesson to one of up to three new times."""
        household = self.reschedule_household(request)
        lesson = self.lesson(household, lesson_id)
        payload = ss.LessonChangeProposal(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        created = scheduling.request_reschedule(
            lesson,
            options=[(o["start"], o["end"]) for o in data["options"]],
            requester=RescheduleRequest.Party.CLIENT,
            reason=data["reason"],
            user=request.user,
        )
        return Response(ss.LessonChangeRequestSerializer(created).data, status=201)


class PortalRescheduleRequestsView(RescheduleView):
    @extend_schema(responses=ss.LessonChangeRequestSerializer(many=True))
    def get(self, request: Request) -> Response:
        household = self.reschedule_household(request)
        items = RescheduleRequest.objects.filter(
            lesson__in=household.lessons().values("pk")
        ).select_related("lesson")[:50]
        return Response(ss.LessonChangeRequestSerializer(items, many=True).data)


class PortalRescheduleDecideView(RescheduleView):
    @extend_schema(
        request=ss.LessonChangeDecisionSerializer, responses=ss.LessonChangeRequestSerializer
    )
    def post(self, request: Request, request_id: Any) -> Response:
        """Answer a tutor's request to move a lesson (pick one of the times, or decline)."""
        household = self.reschedule_household(request)
        item = RescheduleRequest.objects.filter(
            pk=request_id, lesson__in=household.lessons().values("pk")
        ).first()
        if item is None:
            raise NotFound()
        if item.requester != RescheduleRequest.Party.TUTOR:
            raise PermissionDenied()
        payload = ss.LessonChangeDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        item = scheduling.decide_reschedule(
            item, approve=data["approve"], choice=data["choice"], note=data["note"],
            user=request.user,
        )  # fmt: skip
        return Response(ss.LessonChangeRequestSerializer(item).data)


class PortalRescheduleCancelView(RescheduleView):
    @extend_schema(request=None, responses=ss.LessonChangeRequestSerializer)
    def post(self, request: Request, request_id: Any) -> Response:
        household = self.reschedule_household(request)
        item = RescheduleRequest.objects.filter(
            pk=request_id, lesson__in=household.lessons().values("pk"), requested_by=request.user
        ).first()
        if item is None:
            raise NotFound()
        return Response(ss.LessonChangeRequestSerializer(scheduling.cancel_reschedule(item)).data)


def portal_features(request: Request) -> dict[str, bool]:
    """Feature flags for ``/portal/me``."""
    from tutortrack.tenancy.settings_service import get_setting

    return {
        "booking": scheduling.booking_settings().enabled
        and has_perm(request.user, "portal.client.book"),
        "reschedule": bool(get_setting("scheduling.reschedule_requests"))
        and has_perm(request.user, "portal.client.reschedule"),
        # E20: classes and re-enrolment (the courses app serves the pages' data).
        "classes": has_perm(request.user, "portal.client.enrol"),
        # E25: the household's referral link and rewards (the growth app serves the page).
        "referrals": has_perm(request.user, "portal.client.refer")
        and _referral_programme_running(),
    }


def _referral_programme_running() -> bool:
    from tutortrack.growth.services import active_program

    return active_program() is not None
