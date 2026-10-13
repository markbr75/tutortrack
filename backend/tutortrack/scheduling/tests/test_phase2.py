"""E08-T12..T15: rooms with the exclusion constraint and room view, reschedule requests and
policies, self-booking (holds, settings, approval, payment at booking, widget and portal),
time-off approval and cover flagging."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tutortrack.billing import services as billing
from tutortrack.billing.models import PaymentRequest
from tutortrack.catalogue.tests.factories import (
    LocationFactory,
    PromoCodeFactory,
    RoomFactory,
    ServiceFactory,
)
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.matching.models import CoverRequest
from tutortrack.people.models import Client
from tutortrack.people.tests.factories import StudentFactory, TutorProfileFactory
from tutortrack.portal.tests.test_portal import make_household
from tutortrack.scheduling import services
from tutortrack.scheduling.models import (
    AvailabilityException,
    BookingHold,
    Lesson,
    RescheduleRequest,
)
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db

LONDON = ZoneInfo("Europe/London")


def local(days: int, hhmm: str = "16:00") -> datetime:
    day = date.today() + timedelta(days=days)
    return datetime.combine(day, time.fromisoformat(hhmm), tzinfo=LONDON)


def iso(value: datetime) -> str:
    return value.isoformat()


def events_of(org, kind):
    with tenant_context(org):
        return list(OutboxEvent.objects.filter(event_type=kind).order_by("occurred_at"))


@pytest.fixture
def world(org):
    tutor_membership = MembershipFactory(organisation=org, role="tutor")
    tutor = TutorProfileFactory(
        organisation=org, status="active", first_name="Nia", last_name="Adeyemi",
        membership=tutor_membership,
    )  # fmt: skip
    service = ServiceFactory(organisation=org, name="Maths 1:1", bookable_online=True)
    family = make_household(org, "The Patels")
    admin = MembershipFactory(organisation=org, role="admin")
    with tenant_context(org):
        services.set_availability(
            tutor,
            windows=[{"weekday": d, "start_time": time(8), "end_time": time(20)} for d in range(7)],
            effective_from=date.today(),
            timezone="Europe/London",
        )
    return {
        "tutor": tutor,
        "tutor_api": client_for(org, tutor_membership.user),
        "service": service,
        "family": family,
        "student": family["students"][0],
        "admin_api": client_for(org, admin.user),
        "admin": admin.user,
    }


def make_lesson(org, world, start, minutes=60, **kwargs):
    with tenant_context(org):
        return services.create_lesson(
            start=start,
            end=start + timedelta(minutes=minutes),
            service=world["service"],
            attendees=kwargs.pop("attendees", [{"student": world["student"]}]),
            tutors=kwargs.pop("tutors", [{"tutor": world["tutor"]}]),
            timezone="Europe/London",
            **kwargs,
        ).lesson


# --- rooms (T12) --------------------------------------------------------------------------------


def test_room_double_booking_is_a_hard_conflict_nobody_can_override(org, world):
    with tenant_context(org):
        room = RoomFactory(organisation=org, capacity=1)
    make_lesson(org, world, local(3), room=room)
    other_tutor = TutorProfileFactory(organisation=org, status="active")
    other_student = StudentFactory(organisation=org)
    response = world["admin_api"].post(
        "/api/v1/lessons",
        {
            "service": str(world["service"].pk),
            "start": iso(local(3, "16:30")),
            "end": iso(local(3, "17:30")),
            "attendees": [{"student": str(other_student.pk)}],
            "tutors": [{"tutor": str(other_tutor.pk)}],
            "room": str(room.pk),
            "override_conflicts": True,
        },
        format="json",
    )
    assert response.status_code == 422, response.json()
    assert response.json()["conflicts"][0]["kind"] == "room_double_booked"


def test_exclusion_constraint_catches_what_the_check_misses(org, world):
    with tenant_context(org):
        room = RoomFactory(organisation=org)
    first = make_lesson(org, world, local(4), room=room)
    other_tutor = TutorProfileFactory(organisation=org, status="active")
    with pytest.raises(services.ConflictError) as exc:
        make_lesson(org, world, local(4, "16:15"), room=room, check_conflicts=False,
                    tutors=[{"tutor": other_tutor}])  # fmt: skip
    assert exc.value.extra["conflicts"][0]["kind"] == "room_double_booked"
    with tenant_context(org):
        services.cancel_lesson(first, reason="Moved", chargeable=False)
    make_lesson(org, world, local(4, "16:15"), room=room, tutors=[{"tutor": other_tutor}])


def test_room_sets_location_and_must_match_it(org, world):
    with tenant_context(org):
        room = RoomFactory(organisation=org)
        elsewhere = LocationFactory(organisation=org)
    lesson = make_lesson(org, world, local(5), room=room)
    assert lesson.location_id == room.location_id
    with pytest.raises(BusinessRuleViolation):
        make_lesson(org, world, local(6), room=room, location=elsewhere)


def test_room_capacity_is_a_warning(org, world):
    with tenant_context(org):
        room = RoomFactory(organisation=org, capacity=1)
        group = ServiceFactory(organisation=org, format="small_group", max_students=4)
    sibling = world["family"]["students"][1]
    with tenant_context(org):
        result = services.create_lesson(
            start=local(7), end=local(7, "17:00"), service=group, room=room,
            attendees=[{"student": world["student"]}, {"student": sibling}],
            tutors=[{"tutor": world["tutor"]}], timezone="Europe/London",
        )  # fmt: skip
    assert [w.kind for w in result.warnings] == ["room_capacity"]


def test_room_resource_view(org, world):
    with tenant_context(org):
        room = RoomFactory(organisation=org, name="Room 1")
        RoomFactory(organisation=org, name="Room 2", location=room.location)
    make_lesson(org, world, local(2), room=room)
    response = world["admin_api"].get(
        "/api/v1/calendar/rooms",
        {"start": iso(local(1, "00:00")), "end": iso(local(4, "00:00"))},
    )
    rows = response.json()
    assert [r["name"] for r in rows] == ["Room 1", "Room 2"]
    assert len(rows[0]["lessons"]) == 1
    assert rows[1]["lessons"] == []
    assert rows[0]["lessons"][0]["room_name"] == "Room 1"


def test_series_skips_occurrences_whose_room_is_taken(org, world):
    with tenant_context(org):
        room = RoomFactory(organisation=org)
    other = TutorProfileFactory(organisation=org, status="active")
    blocker_start = local(7)
    make_lesson(org, world, blocker_start, room=room, tutors=[{"tutor": other}],
                attendees=[{"student": world["family"]["students"][1]}])  # fmt: skip
    with tenant_context(org):
        result = services.create_series(
            rrule="FREQ=WEEKLY", start_date=blocker_start.date(), start_time=time(16),
            duration_minutes=60, service=world["service"], timezone="Europe/London",
            attendees=[{"student": world["student"]}], tutors=[{"tutor": world["tutor"]}],
            count=3, room=room,
        )  # fmt: skip
    assert [d for d, _c in result.skipped] == [blocker_start.date()]
    assert len(result.created) == 2
    assert all(str(lesson.room_id) == str(room.pk) for lesson in result.created)


# --- time off (T15) -----------------------------------------------------------------------------


def test_tutor_time_off_waits_for_approval_then_flags_cover(org, world):
    clash = make_lesson(org, world, local(10))
    response = world["tutor_api"].post(
        "/api/v1/time-off",
        {"tutor": str(world["tutor"].pk), "type": "off", "start": iso(local(10, "00:00")),
         "end": iso(local(11, "00:00")), "reason": "Wedding"},
        format="json",
    )  # fmt: skip
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "requested"
    assert body["clashes"] == [str(clash.pk)]
    assert events_of(org, "time_off.requested")
    own = world["tutor_api"].post(f"/api/v1/time-off/{body['id']}/decide", {"approve": True},
                                  format="json")  # fmt: skip
    assert own.status_code == 403
    response = world["admin_api"].post(
        f"/api/v1/time-off/{body['id']}/decide", {"approve": True, "note": "Enjoy"}, format="json"
    )
    assert response.json()["status"] == "approved"
    with tenant_context(org):
        exception = AvailabilityException.objects.get(pk=body["id"])
        flagged = services.flag_cover(exception)  # the workflow's next step
        assert [x.pk for x in flagged] == [clash.pk]
        clash.refresh_from_db()
        assert clash.cover_flagged_at is not None
        exception.refresh_from_db()
        cover = CoverRequest.objects.get(pk=exception.cover_request_id)
        assert cover.original_tutor_id == world["tutor"].pk
        assert services.flag_cover(exception) == []  # idempotent


def test_staff_entered_time_off_is_approved_at_once(org, world):
    make_lesson(org, world, local(12))
    response = world["admin_api"].post(
        "/api/v1/time-off",
        {"tutor": str(world["tutor"].pk), "type": "off", "start": iso(local(12, "00:00")),
         "end": iso(local(13, "00:00"))},
        format="json",
    )  # fmt: skip
    assert response.json()["status"] == "approved"
    assert response.json()["cover_request_id"]


def test_declined_and_expired_time_off(org, world):
    with tenant_context(org):
        exception, _ = services.add_exception(
            world["tutor"], type="off", start=local(3), end=local(4), needs_approval=True
        )
        services.decide_time_off(exception, approve=False, note="Busy week")
        with pytest.raises(BusinessRuleViolation):
            services.decide_time_off(exception, approve=True)
        second, _ = services.add_exception(
            world["tutor"], type="off", start=local(5), end=local(6), needs_approval=True
        )
        assert services.expire_time_off(second.pk)
        second.refresh_from_db()
        assert second.status == "declined"
    assert events_of(org, "time_off.declined")[-1].payload["data"]["expired"] is True


# --- reschedule requests (T13) ------------------------------------------------------------------


def test_client_requests_a_new_time_and_staff_approve_it(org, world):
    lesson = make_lesson(org, world, local(5))
    family_api = world["family"]["api"]
    response = family_api.post(
        f"/api/v1/portal/lessons/{lesson.pk}/reschedule",
        {"options": [{"start": iso(local(6)), "end": iso(local(6, "17:00"))},
                     {"start": iso(local(7)), "end": iso(local(7, "17:00"))}],
         "reason": "School trip"},
        format="json",
    )  # fmt: skip
    assert response.status_code == 201, response.json()
    request_id = response.json()["id"]
    assert response.json()["status"] == "pending"
    again = family_api.post(
        f"/api/v1/portal/lessons/{lesson.pk}/reschedule",
        {"options": [{"start": iso(local(8)), "end": iso(local(8, "17:00"))}]},
        format="json",
    )
    assert again.status_code == 422  # one pending request per lesson
    listed = world["admin_api"].get("/api/v1/reschedule-requests?status=pending").json()
    assert [r["id"] for r in listed["results"]] == [request_id]
    response = world["admin_api"].post(
        f"/api/v1/reschedule-requests/{request_id}/decide",
        {"approve": True, "choice": 1},
        format="json",
    )
    assert response.json()["status"] == "approved"
    with tenant_context(org):
        lesson.refresh_from_db()
        assert lesson.start == local(7)
        assert lesson.rescheduled_from == local(5)
    assert events_of(org, "reschedule.approved")


def test_tutor_answers_a_family_request_for_their_lesson(org, world):
    lesson = make_lesson(org, world, local(5))
    with tenant_context(org):
        item = services.request_reschedule(
            lesson, options=[(local(6), local(6, "17:00"))], requester="client"
        )
    response = world["tutor_api"].post(
        f"/api/v1/reschedule-requests/{item.pk}/decide", {"approve": False}, format="json"
    )
    assert response.json()["status"] == "declined"
    with tenant_context(org):
        lesson.refresh_from_db()
        assert lesson.start == local(5)


def test_tutor_request_is_answered_by_the_family(org, world):
    lesson = make_lesson(org, world, local(5))
    response = world["tutor_api"].post(
        f"/api/v1/lessons/{lesson.pk}/reschedule-requests",
        {"options": [{"start": iso(local(6)), "end": iso(local(6, "17:00"))}]},
        format="json",
    )
    assert response.json()["requester"] == "tutor"
    family_api = world["family"]["api"]
    listed = family_api.get("/api/v1/portal/reschedule-requests").json()
    assert [r["id"] for r in listed] == [response.json()["id"]]
    decided = family_api.post(
        f"/api/v1/portal/reschedule-requests/{response.json()['id']}/decide",
        {"approve": True},
        format="json",
    )
    assert decided.json()["status"] == "approved"


def test_reschedule_policies_notice_and_monthly_limit(org, world):
    start = now().replace(second=0, microsecond=0) + timedelta(hours=5)
    soon = make_lesson(org, world, start - timedelta(minutes=start.minute % 5))
    later = [make_lesson(org, world, local(d)) for d in (8, 9, 10)]
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation, match="close"):
            services.request_reschedule(soon, options=[(local(2), local(2, "17:00"))],
                                        requester="client")  # fmt: skip
        settings_service.update_settings("scheduling", {"scheduling.reschedule_max_per_month": 1})
        services.request_reschedule(later[0], options=[(local(20), local(20, "17:00"))],
                                    requester="client")  # fmt: skip
        with pytest.raises(BusinessRuleViolation, match="limit"):
            services.request_reschedule(later[1], options=[(local(21), local(21, "17:00"))],
                                        requester="client")  # fmt: skip
        # staff are not limited
        services.request_reschedule(later[2], options=[(local(22), local(22, "17:00"))],
                                    requester="staff")  # fmt: skip


def test_expired_and_cancelled_requests(org, world):
    lesson = make_lesson(org, world, local(5))
    with tenant_context(org):
        item = services.request_reschedule(
            lesson, options=[(local(6), local(6, "17:00"))], requester="client"
        )
        assert services.expire_reschedule(item.pk)
        assert not services.expire_reschedule(item.pk)
        item.refresh_from_db()
        assert item.status == "expired"
        second = services.request_reschedule(
            lesson, options=[(local(6), local(6, "17:00"))], requester="client"
        )
        services.cancel_reschedule(second)
        second.refresh_from_db()
        assert second.status == "cancelled"
        assert item.deadline <= lesson.start


# --- self-booking (T14) -------------------------------------------------------------------------


def enable_booking(org, **extra):
    with tenant_context(org):
        return services.save_booking_settings(enabled=True, min_notice_hours=0, **extra)


def first_slot(org, world, days=2):
    with tenant_context(org):
        return services.booking_slots(
            world["service"], start=date.today() + timedelta(days=days),
            end=date.today() + timedelta(days=days),
        )[0]  # fmt: skip


def test_booking_settings_api(org, world):
    response = world["admin_api"].put(
        "/api/v1/booking/settings",
        {"enabled": True, "slot_interval_minutes": 60, "approval_required": True},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["slot_interval_minutes"] == 60
    assert world["tutor_api"].get("/api/v1/booking/settings").status_code == 403


def test_slots_follow_availability_interval_and_holds(org, world):
    enable_booking(org, slot_interval_minutes=60)
    with tenant_context(org):
        day = date.today() + timedelta(days=2)
        slots = services.booking_slots(world["service"], start=day, end=day)
        assert [s.start.astimezone(LONDON).hour for s in slots] == list(range(8, 20))
        services.hold_slot(service=world["service"], start=slots[0].start,
                           student=world["student"])  # fmt: skip
        again = services.booking_slots(world["service"], start=day, end=day)
        assert slots[0].start not in [s.start for s in again]
        with pytest.raises(services.BookingUnavailable):
            services.hold_slot(service=world["service"], start=slots[0].start,
                               student=world["student"])  # fmt: skip


def test_booking_disabled_offers_nothing(org, world):
    with tenant_context(org):
        day = date.today() + timedelta(days=2)
        assert services.booking_slots(world["service"], start=day, end=day) == []


def test_portal_instant_booking_creates_the_lesson(org, world):
    enable_booking(org)
    slot = first_slot(org, world)
    family_api = world["family"]["api"]
    assert family_api.get("/api/v1/portal/me").json()["features"]["booking"] is True
    services_list = family_api.get("/api/v1/portal/booking/services").json()
    assert services_list[0]["tutors"] == [{"id": str(world["tutor"].pk), "name": "Nia A."}]
    response = family_api.post(
        "/api/v1/portal/booking/holds",
        {"service": str(world["service"].pk), "start": iso(slot.start),
         "student": str(world["student"].pk)},
        format="json",
    )  # fmt: skip
    assert response.status_code == 201, response.json()
    hold = response.json()
    assert hold["status"] == "held"
    assert hold["quote"]["amount"] == {"amount": "40.00", "currency": "GBP"}
    response = family_api.post(f"/api/v1/portal/booking/holds/{hold['id']}/submit")
    assert response.json()["booking"]["status"] == "confirmed"
    assert response.json()["pay_url"] == ""
    with tenant_context(org):
        lesson = Lesson.objects.get(pk=response.json()["booking"]["lesson"])
        assert lesson.created_via == "client_booking"
        assert lesson.start == slot.start
    other = make_household(org, "The Smiths")
    assert other["api"].post(f"/api/v1/portal/booking/holds/{hold['id']}/cancel").status_code == 404


def test_booking_needing_approval(org, world):
    enable_booking(org, approval_required=True)
    slot = first_slot(org, world)
    with tenant_context(org):
        hold, _ = services.hold_slot(service=world["service"], start=slot.start,
                                     student=world["student"])  # fmt: skip
        services.submit_hold(hold)
        hold.refresh_from_db()
        assert hold.status == "awaiting_approval"
    response = world["admin_api"].post(f"/api/v1/booking/holds/{hold.pk}/decide",
                                       {"approve": True}, format="json")  # fmt: skip
    assert response.json()["status"] == "confirmed"
    assert response.json()["lesson"]


def test_payment_at_booking_then_confirmed_when_paid(org, world):
    enable_booking(org, payment="at_booking")
    slot = first_slot(org, world)
    with tenant_context(org):
        hold, _ = services.hold_slot(service=world["service"], start=slot.start,
                                     student=world["student"])  # fmt: skip
        hold, pay_url = services.submit_hold(hold)
        assert hold.status == "awaiting_payment"
        assert "/pay/" in pay_url
        request = PaymentRequest.objects.get(pk=hold.payment_request_id)
        assert request.amount == Money("40.00", "GBP")
        billing.pay_payment_request(request, Money("40.00", "GBP"))
        assert services.payment_received(hold.pk) == "confirmed"
        hold.refresh_from_db()
        assert hold.lesson is not None


def test_unpaid_hold_expires_and_cancels_the_payment_request(org, world):
    enable_booking(org, payment="at_booking")
    slot = first_slot(org, world)
    with tenant_context(org):
        hold, _ = services.hold_slot(service=world["service"], start=slot.start,
                                     student=world["student"])  # fmt: skip
        hold, _url = services.submit_hold(hold)
        assert services.release_hold(hold.pk)
        hold.refresh_from_db()
        assert hold.status == "expired"
        assert PaymentRequest.objects.get(pk=hold.payment_request_id).status == "cancelled"
        day = slot.start.astimezone(LONDON).date()
        assert slot.start in [s.start for s in services.booking_slots(
            world["service"], start=day, end=day)]  # fmt: skip


def test_public_widget_booking_for_a_new_family_with_promo(org, world):
    enable_booking(org)
    with tenant_context(org):
        PromoCodeFactory(organisation=org, code="WELCOME", discount__percent=Decimal(25))
    slot = first_slot(org, world)
    public = client_for(org, None)
    services_list = public.get("/api/v1/public/booking/services").json()
    assert services_list[0]["name"] == "Maths 1:1"
    slots = public.get(
        "/api/v1/public/booking/slots",
        {"service": str(world["service"].pk), "from": str(slot.start.date())},
    ).json()
    assert slots[0]["tutor_name"] == "Nia A."
    response = public.post(
        "/api/v1/public/booking/holds",
        {"service": str(world["service"].pk), "start": iso(slot.start), "promo_code": "welcome",
         "contact": {"first_name": "Sam", "last_name": "Lee", "email": "sam@example.com",
                     "student_first_name": "Kai"}},
        format="json",
    )  # fmt: skip
    assert response.status_code == 201, response.json()
    hold, token = response.json(), response.json()["token"]
    assert hold["quote"]["amount"]["amount"] == "30.00"
    assert public.get(f"/api/v1/public/booking/holds/{hold['id']}?token=wrong").status_code == 404
    done = public.post(f"/api/v1/public/booking/holds/{hold['id']}/submit?token={token}")
    assert done.json()["booking"]["status"] == "confirmed"
    with tenant_context(org):
        client = Client.objects.get(pk=done.json()["booking"]["client"])
        assert client.display_name.endswith("Lee") or "Lee" in client.display_name
        lesson = Lesson.objects.get(pk=done.json()["booking"]["lesson"])
        attendee = lesson.attendees.get()
        assert attendee.charge_amount == Money("30.00", "GBP")
        assert attendee.promo_code.code == "WELCOME"


def test_clients_in_collections_cant_book_online(org, world, monkeypatch):
    """E10 hook: ``billing.selectors.booking_block`` (hard blocks self-booking, soft and hard
    warn staff)."""
    enable_booking(org)
    slot = first_slot(org, world)
    monkeypatch.setattr("tutortrack.billing.selectors.booking_block", lambda client_id: "hard")
    with tenant_context(org):
        with pytest.raises(services.BookingUnavailable, match="contact us"):
            services.hold_slot(service=world["service"], start=slot.start, student=world["student"])
        result = services.create_lesson(
            start=slot.start, end=slot.end, service=world["service"],
            attendees=[{"student": world["student"]}], tutors=[{"tutor": world["tutor"]}],
        )  # fmt: skip
    assert "client_in_collections" in [w.kind for w in result.warnings]


def test_admin_cannot_book_over_a_held_slot(org, world):
    enable_booking(org)
    slot = first_slot(org, world)
    with tenant_context(org):
        services.hold_slot(service=world["service"], start=slot.start, student=world["student"])
        with pytest.raises(services.ConflictError):
            services.create_lesson(
                start=slot.start, end=slot.end, service=world["service"],
                attendees=[{"student": world["family"]["students"][1]}],
                tutors=[{"tutor": world["tutor"]}], override_conflicts=True,
            )  # fmt: skip


# --- isolation ----------------------------------------------------------------------------------


class TestRescheduleRequestIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/reschedule-requests"

    def make_object(self, organisation):
        service = ServiceFactory(organisation=organisation)
        tutor = TutorProfileFactory(organisation=organisation, status="active")
        student = StudentFactory(organisation=organisation)
        with tenant_context(organisation):
            lesson = services.create_lesson(
                start=local(5), end=local(5, "17:00"), service=service,
                attendees=[{"student": student}], tutors=[{"tutor": tutor}],
            ).lesson  # fmt: skip
            return RescheduleRequest.objects.create(
                lesson=lesson, requester="staff", proposed=[], deadline=local(4),
                original_start=lesson.start, original_end=lesson.end,
            )  # fmt: skip


class TestBookingHoldIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/booking/holds"

    def make_object(self, organisation):
        service = ServiceFactory(organisation=organisation)
        tutor = TutorProfileFactory(organisation=organisation, status="active")
        with tenant_context(organisation):
            from tutortrack.tenancy.models import Branch

            return BookingHold.objects.create(
                service=service, tutor=tutor, branch=Branch.objects.first(), start=local(5),
                end=local(5, "17:00"), timezone="Europe/London", expires_at=local(1),
            )  # fmt: skip
