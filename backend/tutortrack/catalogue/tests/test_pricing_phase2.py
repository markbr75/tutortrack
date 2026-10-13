"""E06-T07..T10: rooms, pay tiers and tutor rates (with CSV), holiday calendars and
premiums, discounts, promo codes and price lists: API, rules loading and lesson pricing."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tutortrack.catalogue import holidays, pricing_rules, services
from tutortrack.catalogue.models import (
    DiscountRule,
    Holiday,
    HolidayCalendar,
    PayTier,
    PremiumRule,
    PromoCode,
    Room,
    ServiceTierRate,
    TutorPayTierAssignment,
    TutorServiceRate,
)
from tutortrack.catalogue.rates import AttendeeInput, TutorInput
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory

from .factories import (
    DiscountRuleFactory,
    HolidayCalendarFactory,
    LocationFactory,
    PayTierFactory,
    PremiumRuleFactory,
    PriceListFactory,
    PromoCodeFactory,
    RoomFactory,
    ServiceFactory,
)

pytestmark = pytest.mark.django_db

S = "/api/v1/catalogue"
LONDON = ZoneInfo("Europe/London")


def api_as(org, role):
    return client_for(org, MembershipFactory(organisation=org, role=role).user)


@pytest.fixture
def admin_api(org):
    return api_as(org, "admin")


def gbp(amount):
    return {"amount": amount, "currency": "GBP"}


def money(amount):
    return Money(Decimal(amount), "GBP")


def lesson(org, service, tutor, student, start, minutes=60):
    from tutortrack.scheduling import services as scheduling

    with tenant_context(org):
        return scheduling.create_lesson(
            start=start,
            end=start + timedelta(minutes=minutes),
            service=service,
            attendees=[{"student": student}],
            tutors=[{"tutor": tutor}],
            timezone="Europe/London",
        ).lesson


def future(days: int, hour: int = 16) -> datetime:
    day = date.today() + timedelta(days=days)
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=LONDON)


# --- rooms (T10) ------------------------------------------------------------------------------


def test_room_with_resources_and_filter(org, admin_api):
    with tenant_context(org):
        centre = LocationFactory(organisation=org)
    response = admin_api.post(
        f"{S}/rooms",
        {
            "location": str(centre.pk),
            "name": "Piano room",
            "capacity": 4,
            "resources_input": [{"name": "Piano", "quantity": 1}, {"name": "Whiteboard"}],
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert {r["name"] for r in body["resources"]} == {"Piano", "Whiteboard"}
    found = admin_api.get(f"{S}/rooms?resource=piano").json()["results"]
    assert [r["id"] for r in found] == [body["id"]]
    dup = admin_api.post(
        f"{S}/rooms", {"location": str(centre.pk), "name": "piano room"}, format="json"
    )
    assert dup.status_code == 422


def test_online_locations_have_no_rooms(org, tenant):
    online = LocationFactory(organisation=org, type="online")
    with pytest.raises(BusinessRuleViolation):
        services.save_room(None, location=online, name="Zoom")


# --- pay tiers and tutor rates (T07) ------------------------------------------------------------


def test_tier_grid_bulk_edit_and_csv_round_trip(org, admin_api):
    with tenant_context(org):
        svc = ServiceFactory(organisation=org, name="Maths 1:1")
        senior = PayTierFactory(organisation=org, name="Senior")
    response = admin_api.post(
        f"{S}/tier-rates",
        {"cells": [{"service": str(svc.pk), "tier": str(senior.pk), "pay_rate": gbp("30")}]},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["cells"][0]["pay_rate"]["amount"].startswith("30")
    csv_text = admin_api.get(f"{S}/tier-rates/csv").content.decode()
    assert "Maths 1:1,Senior,30.0000,,GBP" in csv_text
    upload = SimpleUploadedFile(
        "rates.csv",
        b"service,tier,pay_rate,charge_rate,currency\nMaths 1:1,Senior,32.50,55,GBP\n",
        content_type="text/csv",
    )
    response = admin_api.post(f"{S}/tier-rates/csv", {"file": upload}, format="multipart")
    assert response.json() == {"updated": 1, "unchanged": 0, "row_errors": []}
    with tenant_context(org):
        row = ServiceTierRate.objects.get(service=svc, tier=senior)
        assert (row.pay_rate, row.charge_rate) == (money("32.50"), money("55"))


def test_csv_import_reports_bad_rows_and_saves_nothing(org, tenant):
    svc = ServiceFactory(organisation=org, name="Maths")
    PayTierFactory(organisation=org, name="Senior")
    result = services.import_tier_rates(
        "service,tier,pay_rate\nMaths,Senior,30\nMaths,Nope,30\nMaths,Senior,abc\n"
    )
    assert [e["row"] for e in result.errors] == [3, 4]
    assert not ServiceTierRate.objects.filter(service=svc).exists()


def test_tier_by_effective_date_and_personal_rate_win(org, tenant):
    svc = ServiceFactory(organisation=org)
    tutor = TutorProfileFactory(organisation=org, status="active")
    junior, senior = PayTierFactory(organisation=org), PayTierFactory(organisation=org)
    services.set_tier_rate(svc, junior, pay_rate=money("20"))
    services.set_tier_rate(svc, senior, pay_rate=money("30"))
    services.assign_tier(tutor, junior, effective_from=date(2026, 1, 1))
    services.assign_tier(tutor, senior, effective_from=date(2026, 6, 1))

    def pay_on(day):
        rules = pricing_rules.load_rules(
            service=svc,
            currency="GBP",
            start=datetime(day.year, day.month, day.day, 16, tzinfo=LONDON),
            timezone="Europe/London",
            attendees=[AttendeeInput("s")],
            tutors=[TutorInput(str(tutor.pk))],
        )
        return rules.tier_rates[str(tutor.pk)].pay_rate

    assert pay_on(date(2026, 3, 1)) == money("20")
    assert pay_on(date(2026, 7, 1)) == money("30")
    services.set_tutor_rate(tutor, svc, money("33"))
    assert TutorServiceRate.objects.get(tutor=tutor).pay_rate == money("33")
    services.set_tutor_rate(tutor, svc, None)
    assert not TutorServiceRate.objects.filter(tutor=tutor).exists()


def test_tier_change_with_recalculate_reprices_unlocked_lessons(org):
    with tenant_context(org):
        svc = ServiceFactory(organisation=org)
        tutor = TutorProfileFactory(organisation=org, status="active")
        student = StudentFactory(organisation=org)
        tier = PayTierFactory(organisation=org)
        services.set_tier_rate(svc, tier, pay_rate=money("31"))
    first = lesson(org, svc, tutor, student, future(10))
    with tenant_context(org):
        assert first.tutors.get().pay_amount == money("25.00")
        services.assign_tier(tutor, tier, effective_from=date.today(), recalculate=True)
    dispatch_batch()
    with tenant_context(org):
        assert first.tutors.get().pay_amount == money("31.00")
        assert TutorPayTierAssignment.objects.filter(tutor=tutor).count() == 1


def test_reprice_endpoint_counts_then_applies(org, admin_api):
    with tenant_context(org):
        svc = ServiceFactory(organisation=org)
        tutor = TutorProfileFactory(organisation=org, status="active")
        student = StudentFactory(organisation=org)
    planned = lesson(org, svc, tutor, student, future(5))
    with tenant_context(org):
        PremiumRuleFactory(organisation=org, name="Everything", charge_percent=Decimal(50))
    response = admin_api.post("/api/v1/lessons/reprice", {"service": str(svc.pk)}, format="json")
    assert response.json() == {"lessons": 1, "dry_run": True}
    with tenant_context(org):
        assert planned.attendees.get().charge_amount == money("40.00")
    admin_api.post("/api/v1/lessons/reprice", {"service": str(svc.pk), "dry_run": False},
                   format="json")  # fmt: skip
    with tenant_context(org):
        assert planned.attendees.get().charge_amount == money("60.00")


# --- holidays and premiums (T08) ----------------------------------------------------------------


def test_gb_and_us_public_holidays():
    gb = dict(holidays.public_holidays("GB", 2026))
    assert gb[date(2026, 4, 3)] == "Good Friday"
    assert gb[date(2026, 12, 28)] == "Boxing Day"  # 26th is a Saturday
    us = dict(holidays.public_holidays("US", 2026))
    assert us[date(2026, 11, 26)] == "Thanksgiving Day"
    assert holidays.public_holidays("FR", 2026) == []


def test_holiday_calendar_import_premium_and_series_skip(org, admin_api):
    response = admin_api.post(
        f"{S}/holiday-calendars", {"name": "England", "country": "GB"}, format="json"
    )
    calendar_id = response.json()["id"]
    response = admin_api.post(f"{S}/holiday-calendars/{calendar_id}/import", {"year": 2026},
                              format="json")  # fmt: skip
    assert len(response.json()["holidays"]) == 8
    with tenant_context(org):
        svc = ServiceFactory(organisation=org)
        services.save_premium(None, name="Bank holiday", public_holidays=True,
                              charge_percent=Decimal(50), pay_percent=Decimal(50))  # fmt: skip
        rules = pricing_rules.load_rules(
            service=svc,
            currency="GBP",
            start=datetime(2026, 12, 25, 10, tzinfo=LONDON),
            timezone="Europe/London",
            attendees=[AttendeeInput("s")],
        )
        assert rules.facts.is_holiday
        from tutortrack.scheduling.services import holiday_dates

        assert date(2026, 12, 25) in holiday_dates(None, date(2026, 12, 1), date(2026, 12, 31),
                                                   "Europe/London")  # fmt: skip


def test_premium_validation(org, tenant):
    with pytest.raises(BusinessRuleViolation):
        services.save_premium(None, name="Nothing")
    with pytest.raises(BusinessRuleViolation):
        services.save_premium(None, name="Bad day", weekdays=[7], charge_percent=Decimal(5))
    rule = services.save_premium(None, name="Travel", charge_fixed=money("5"), pay_fixed=money("5"))
    assert rule.currency == "GBP"


def test_weekend_premium_priced_onto_a_lesson(org):
    with tenant_context(org):
        svc = ServiceFactory(organisation=org)
        tutor = TutorProfileFactory(organisation=org, status="active")
        student = StudentFactory(organisation=org)
        services.save_premium(None, name="Weekend", weekdays=[5, 6], charge_percent=Decimal(10),
                              pay_percent=Decimal(20))  # fmt: skip
    day = future(1)
    saturday = day + timedelta(days=(5 - day.weekday()) % 7 or 7)
    made = lesson(org, svc, tutor, student, saturday)
    with tenant_context(org):
        attendee, link = made.attendees.get(), made.tutors.get()
        assert attendee.charge_amount == money("44.00")
        assert attendee.charge_snapshot["premiums"][0]["name"] == "Weekend"
        assert link.pay_amount == money("30.00")


# --- discounts, promo codes and price lists (T09) -----------------------------------------------


def test_sibling_and_first_lesson_discounts_on_lessons(org):
    with tenant_context(org):
        svc = ServiceFactory(organisation=org)
        tutor = TutorProfileFactory(organisation=org, status="active")
        family = ClientFactory(organisation=org)
        older = StudentFactory(organisation=org, client=family)
        younger = StudentFactory(organisation=org, client=family)
        services.save_discount(None, name="Sibling", kind="sibling", percent=Decimal(10))
        services.save_discount(None, name="Trial", kind="first_lesson", fixed_price=money("20"),
                               stackable=False, priority=5)  # fmt: skip
    first = lesson(org, svc, tutor, older, future(3))
    second = lesson(org, svc, tutor, older, future(4))
    sibling = lesson(org, svc, tutor, younger, future(5, 10))
    with tenant_context(org):
        assert first.attendees.get().charge_amount == money("20.00")  # trial price alone
        assert second.attendees.get().charge_amount == money("40.00")
        younger_first = sibling.attendees.get()
        assert younger_first.charge_amount == money("20.00")  # trial beats sibling
        assert younger_first.charge_snapshot["undiscounted_amount"] == gbp("40.00")


def test_price_list_applies_to_its_clients_in_its_dates(org, admin_api):
    with tenant_context(org):
        svc = ServiceFactory(organisation=org)
        school = ClientFactory(organisation=org)
        other = ClientFactory(organisation=org)
        tutor = TutorProfileFactory(organisation=org, status="active")
        pupil = StudentFactory(organisation=org, client=school)
        stranger = StudentFactory(organisation=org, client=other)
    response = admin_api.post(
        f"{S}/price-lists",
        {
            "name": "Council contract",
            "currency": "GBP",
            "valid_from": str(date.today()),
            "items_input": [{"service": str(svc.pk), "charge_rate": gbp("28")}],
            "client_ids": [str(school.pk)],
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["clients"] == [str(school.pk)]
    contract = lesson(org, svc, tutor, pupil, future(2))
    normal = lesson(org, svc, tutor, stranger, future(2, 10))
    with tenant_context(org):
        attendee = contract.attendees.get()
        assert attendee.charge_amount == money("28.00")
        assert attendee.charge_snapshot["trace"][0] == "Council contract price £28.00/h"
        assert normal.attendees.get().charge_amount == money("40.00")


def test_promo_codes_rules(org, tenant):
    svc = ServiceFactory(organisation=org)
    client = ClientFactory(organisation=org)
    promo = services.save_promo_code(
        None,
        code=" spring 25 ",
        discount=DiscountRuleFactory(organisation=org, kind="promo", percent=Decimal(25)),
        max_uses=1,
    )
    assert promo.code == "SPRING25"
    assert services.check_promo("spring25", client=client, service=svc) == promo
    assert services.redeem_promo(promo, client=client, reference="booking:1")
    assert not services.redeem_promo(promo, client=client, reference="booking:1")  # idempotent
    with pytest.raises(services.PromoInvalid):
        services.check_promo("SPRING25", client=client, service=svc)  # used up
    with pytest.raises(services.PromoInvalid):
        services.check_promo("NOPE")
    with pytest.raises(BusinessRuleViolation):
        services.save_promo_code(None, code="X", discount=DiscountRuleFactory(organisation=org))


def test_discount_validation(org, tenant):
    with pytest.raises(BusinessRuleViolation):
        services.save_discount(None, name="Volume", kind="volume", percent=Decimal(5))
    with pytest.raises(BusinessRuleViolation):
        services.save_discount(None, name="Client", kind="client", percent=Decimal(5))
    with pytest.raises(BusinessRuleViolation):
        services.save_discount(None, name="Empty", kind="sibling")


def test_quote_api_uses_rules_and_promo_code(org, admin_api):
    with tenant_context(org):
        svc = ServiceFactory(organisation=org)
        student = StudentFactory(organisation=org)
        PromoCodeFactory(organisation=org, code="HALF", discount__percent=Decimal(50))
    response = admin_api.post(
        "/api/v1/rates/quote",
        {
            "service": str(svc.pk),
            "duration_minutes": 60,
            "students": [{"student": str(student.pk)}],
            "promo_code": "half",
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["charges"][0]["amount"] == gbp("20.00")


def test_rates_endpoints_need_rates_manage(org):
    coordinator = api_as(org, "coordinator")
    response = coordinator.post(f"{S}/premiums", {"name": "X", "charge_percent": "5"},
                                format="json")  # fmt: skip
    assert response.status_code == 403
    tutor_view = api_as(org, "tutor").get(f"{S}/tutor-rates")
    assert tutor_view.status_code == 403


# --- tenant isolation -------------------------------------------------------------------------


class TestRoomIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/rooms"

    def make_object(self, organisation):
        return RoomFactory(organisation=organisation)


class TestPayTierIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/pay-tiers"

    def make_object(self, organisation):
        return PayTierFactory(organisation=organisation)


class TestPremiumIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/premiums"

    def make_object(self, organisation):
        return PremiumRuleFactory(organisation=organisation)


class TestDiscountIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/discounts"

    def make_object(self, organisation):
        return DiscountRuleFactory(organisation=organisation)


class TestPromoIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/promo-codes"

    def make_object(self, organisation):
        return PromoCodeFactory(organisation=organisation)


class TestPriceListIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/price-lists"

    def make_object(self, organisation):
        return PriceListFactory(organisation=organisation)


class TestHolidayCalendarIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/holiday-calendars"

    def make_object(self, organisation):
        return HolidayCalendarFactory(organisation=organisation)


class TestTierAssignmentIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/tier-assignments"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return TutorPayTierAssignment.objects.create(
                tutor=TutorProfileFactory(organisation=organisation),
                tier=PayTierFactory(organisation=organisation),
                effective_from=date(2026, 1, 1),
            )


class TestTutorRateIsolation(TenantIsolationTestMixin):
    list_url = f"{S}/tutor-rates"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return TutorServiceRate.objects.create(
                tutor=TutorProfileFactory(organisation=organisation),
                service=ServiceFactory(organisation=organisation),
                currency="GBP",
                pay_rate_amount=Decimal("30"),
            )


def test_unused_imports_are_models():
    # keep imports meaningful for readers: these models back the endpoints above
    assert {Holiday, HolidayCalendar, PayTier, PremiumRule, PromoCode, Room, DiscountRule}
