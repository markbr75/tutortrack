"""E29-T09 lone working check-ins and E29-T10 children's privacy (COPPA / AADC)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.db import transaction

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people import services as people
from tutortrack.people.tests.factories import StudentFactory, TutorProfileFactory
from tutortrack.privacy import children, lone_working, services
from tutortrack.privacy.models import LoneWorkingVisit
from tutortrack.scheduling import services as scheduling
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db


def lesson_for(org, tutor, student, *, online=False, starts_in=timedelta(minutes=-30)):
    start = (now() + starts_in).replace(second=0, microsecond=0)
    start = start.replace(minute=start.minute - start.minute % 5)
    with tenant_context(org):
        return scheduling.create_lesson(
            start=start,
            end=start + timedelta(minutes=60),
            service=ServiceFactory(organisation=org),
            attendees=[{"student": student}],
            tutors=[{"tutor": tutor}],
            timezone="Europe/London",
            online=online,
            override_conflicts=True,
        ).lesson


def lone_working_on(org, mode="client_homes"):
    with tenant_context(org):
        settings_service.update_settings("safeguarding", {"safeguarding.lone_working": mode})


def test_check_in_is_off_by_default(org, family, tutor):
    lesson = lesson_for(org, tutor, family.student)
    response = client_for(org, tutor.membership.user).post(
        "/api/v1/lone-working/visits/check-in", {"lesson": str(lesson.pk)}, format="json"
    )
    assert response.status_code == 422


def test_tutors_check_in_and_out_of_home_visits(org, family, tutor):
    lone_working_on(org)
    lesson = lesson_for(org, tutor, family.student)
    api = client_for(org, tutor.membership.user)
    arrived = api.post(
        "/api/v1/lone-working/visits/check-in", {"lesson": str(lesson.pk)}, format="json"
    )
    assert arrived.status_code == 201, arrived.content
    assert arrived.json()["status"] == "checked_in"
    assert arrived.json()["expected_end"] is not None
    again = api.post(
        "/api/v1/lone-working/visits/check-in", {"lesson": str(lesson.pk)}, format="json"
    )
    assert again.json()["id"] == arrived.json()["id"]  # idempotent
    left = api.post(
        "/api/v1/lone-working/visits/check-out", {"lesson": str(lesson.pk)}, format="json"
    )
    assert left.json()["status"] == "checked_out"
    mine = api.get("/api/v1/lone-working/visits").json()["results"]
    assert [v["id"] for v in mine] == [arrived.json()["id"]]


def test_online_lessons_need_no_check_in(org, family, tutor):
    lone_working_on(org)
    lesson = lesson_for(org, tutor, family.student, online=True)
    with tenant_context(org), pytest.raises(BusinessRuleViolation):
        lone_working.check_in(user=tutor.membership.user, lesson_id=lesson.pk)


def test_tutors_only_check_in_to_their_own_lessons(org, family, tutor):
    lone_working_on(org)
    other = TutorProfileFactory(organisation=org)
    lesson = lesson_for(org, other, family.student)
    response = client_for(org, tutor.membership.user).post(
        "/api/v1/lone-working/visits/check-in", {"lesson": str(lesson.pk)}, format="json"
    )
    assert response.status_code == 404


def test_overdue_visits_alert_monitors_and_escalate_to_dsls(
    org, family, tutor, owner, django_capture_on_commit_callbacks
):
    from tutortrack.comms.models import Message

    lone_working_on(org)
    coordinator = MembershipFactory(organisation=org, role="coordinator").user
    lesson = lesson_for(org, tutor, family.student, starts_in=timedelta(hours=-3))
    with tenant_context(org), transaction.atomic():
        visit = lone_working.check_in(user=tutor.membership.user, lesson_id=lesson.pk)
    with tenant_context(org), django_capture_on_commit_callbacks(execute=True):
        state = lone_working.state(str(visit.pk))
        assert lone_working.alert(str(visit.pk), escalate=False) == "overdue"
        assert lone_working.alert(str(visit.pk), escalate=True) == "overdue"
    with tenant_context(org):
        recipients = set(
            Message.objects.filter(type_key="lone_working_overdue").values_list(
                "recipient_id", flat=True
            )
        )
        visit.refresh_from_db()
    assert str(coordinator.pk) in recipients
    assert str(owner.pk) in recipients  # escalated to the DSL
    assert str(tutor.pk) in recipients
    assert visit.alerted_at is not None
    assert visit.escalated_at is not None
    assert state["alert_at"] < state["escalate_at"]


def test_monitors_resolve_overdue_visits(org, family, tutor):
    lone_working_on(org)
    coordinator = MembershipFactory(organisation=org, role="coordinator").user
    lesson = lesson_for(org, tutor, family.student)
    with tenant_context(org), transaction.atomic():
        visit = lone_working.check_in(user=tutor.membership.user, lesson_id=lesson.pk)
    api = client_for(org, coordinator)
    missing_note = api.post(f"/api/v1/lone-working/visits/{visit.pk}/resolve", {"note": ""})
    assert missing_note.status_code == 400
    resolved = api.post(
        f"/api/v1/lone-working/visits/{visit.pk}/resolve",
        {"note": "Phoned: running late"},
        format="json",
    )
    assert resolved.json()["status"] == "resolved"
    tutor_api = client_for(org, tutor.membership.user)
    forbidden = tutor_api.post(
        f"/api/v1/lone-working/visits/{visit.pk}/resolve", {"note": "x"}, format="json"
    )
    assert forbidden.status_code == 403


class TestVisitIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/lone-working/visits"

    def make_object(self, organisation):
        tutor = TutorProfileFactory(organisation=organisation)
        student = StudentFactory(organisation=organisation)
        lesson = lesson_for(organisation, tutor, student)
        with tenant_context(organisation):
            return LoneWorkingVisit.objects.create(
                lesson=lesson, tutor=tutor, checked_in_at=now(), expected_end=lesson.end
            )


# --- children's privacy (T10) -------------------------------------------------------------------


def _us(org):
    org.country = "US"
    org.region = "us"
    org.save()


def test_coppa_needs_parental_consent_before_an_under_13_gets_a_login(org, family):
    _us(org)
    child = StudentFactory(
        organisation=org, client=family.client, date_of_birth=date(2018, 1, 1), first_name="Mia"
    )
    with tenant_context(org), transaction.atomic():
        services.ensure_default_types()
        with pytest.raises(children.ParentalConsentRequired):
            people.invite_to_portal(child, email="mia@example.com")
        services.record_consent(
            subject_type="people.student",
            subject_id=str(child.pk),
            key="parental-consent",
            granted=True,
            method="form",
            given_by_name="Priya Patel (mother), signed form",
            on_behalf_of_child=True,
        )
        assert people.invite_to_portal(child, email="mia@example.com") is not None


def test_coppa_does_not_apply_outside_the_us_by_default(org, family):
    child = StudentFactory(organisation=org, client=family.client, date_of_birth=date(2018, 1, 1))
    with tenant_context(org), transaction.atomic():
        assert not children.needs_parental_consent(child)
        settings_service.update_settings("privacy", {"privacy.coppa": "on"})
        assert children.needs_parental_consent(child)


def test_teenagers_are_children_but_not_under_coppa(org, family):
    _us(org)
    teen = StudentFactory(organisation=org, client=family.client, date_of_birth=date(2011, 1, 1))
    with tenant_context(org):
        assert children.is_child(teen)
        assert not children.needs_parental_consent(teen)


def test_unknown_dates_of_birth_get_the_safe_default(org, family):
    _us(org)
    unknown = StudentFactory(organisation=org, client=family.client, date_of_birth=None)
    with tenant_context(org):
        assert children.is_child(unknown)
        assert children.needs_parental_consent(unknown)


def test_marketing_consent_cannot_be_recorded_for_children(org, family):
    with tenant_context(org), transaction.atomic():
        services.ensure_default_types()
        from tutortrack.privacy.models import ConsentType

        ConsentType.objects.filter(key="marketing-email").update(
            applies_to=["people.contact", "people.student"]
        )
        with pytest.raises(BusinessRuleViolation, match="children"):
            services.record_consent(
                subject_type="people.student",
                subject_id=str(family.student.pk),
                key="marketing-email",
                granted=True,
                method="staff",
            )
        # Withdrawing is always allowed.
        services.record_consent(
            subject_type="people.student",
            subject_id=str(family.student.pk),
            key="marketing-email",
            granted=False,
            method="staff",
        )


def test_the_student_privacy_panel(org, family, owner_api):
    response = owner_api.get(f"/api/v1/students/{family.student.pk}/privacy")
    assert response.status_code == 200
    body = response.json()
    assert body["is_child"] is True
    assert body["high_privacy_defaults"] is True
    assert body["coppa_applies"] is False
    tutor = MembershipFactory(organisation=org, role="tutor").user
    other = client_for(org, tutor).get(f"/api/v1/students/{family.student.pk}/privacy")
    assert other.status_code == 404  # not their student
