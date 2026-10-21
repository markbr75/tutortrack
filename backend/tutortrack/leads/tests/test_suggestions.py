"""Gap G5c (FR-17-6): waitlist suggestions when tutor capacity appears."""

from __future__ import annotations

from datetime import date, time
from typing import Any

import pytest

from tutortrack.catalogue.models import Subject
from tutortrack.catalogue.tests.factories import SubjectFactory
from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads import services, suggestions
from tutortrack.leads.models import WaitlistEntry, WaitlistSuggestion
from tutortrack.people import services as people
from tutortrack.people.models import TutorSubject
from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory
from tutortrack.scheduling import services as scheduling

pytestmark = pytest.mark.django_db

EVERY_DAY = [
    {"weekday": d, "start_time": time(9), "end_time": time(20)} for d in range(7)
]  # plenty of room


def teaching(org, subject_name="Maths", *, approved=True, **fields) -> Any:
    with tenant_context(org):
        subject = Subject.objects.filter(name=subject_name).first() or SubjectFactory(
            organisation=org, name=subject_name
        )
        tutor = TutorProfileFactory(organisation=org, status="active", **fields)
        TutorSubject.objects.create(
            tutor=tutor,
            subject=subject_name,
            catalogue_subject=subject,
            approved=approved,
            competency="approved" if approved else "claimed",
        )
    return tutor


def waiting(org, subject="Maths", **fields) -> WaitlistEntry:
    with tenant_context(org):
        family = ClientFactory(organisation=org)
        student = StudentFactory(organisation=org, client=family, status="lead")
        return services.add_to_waitlist(student=student, subject=subject, **fields)


def free_up(org, tutor) -> None:
    """The tutor sets their availability: ``availability.updated`` is published."""
    with tenant_context(org):
        scheduling.set_availability(
            tutor, windows=EVERY_DAY, effective_from=date(2020, 1, 1), timezone=org.timezone
        )
    dispatch_batch()


@pytest.fixture
def coordinator(org):
    return MembershipFactory(organisation=org, role="coordinator")


def open_suggestions(org) -> list[WaitlistSuggestion]:
    with tenant_context(org):
        return list(WaitlistSuggestion.objects.filter(status="open").select_related("entry"))


def test_new_availability_suggests_the_tutor_for_waiting_students(org, coordinator):
    """FR-17-6: capacity appears (availability) → staff get a suggestion, once."""
    tutor = teaching(org, "Maths")
    maths = waiting(org, "maths")  # names match ignoring case
    waiting(org, "French")  # the tutor doesn't teach French
    free_up(org, tutor)
    found = open_suggestions(org)
    assert [(s.entry_id, s.tutor_id, s.reason) for s in found] == [
        (maths.pk, tutor.pk, "availability")
    ]
    assert found[0].score is not None
    with tenant_context(org):
        alerts = Message.objects.filter(type_key="staff_waitlist_suggestion", channel="in_app")
        assert alerts.count() == 1
        assert "room for 1 waiting student" in alerts.get().subject
        assert OutboxEvent.objects.filter(event_type="waitlist.suggestion_created").count() == 1
    free_up(org, tutor)  # a second change: no duplicate suggestion or notice
    assert len(open_suggestions(org)) == 1
    with tenant_context(org):
        assert Message.objects.filter(type_key="staff_waitlist_suggestion").count() == 1


def test_hard_filters_keep_unsuitable_tutors_out(org):
    tutor = teaching(org, "Maths")
    unapproved = teaching(org, "Physics", approved=False)
    other = TutorProfileFactory(organisation=org, status="active")
    named = waiting(org, "Maths", tutor=other)  # waiting for someone else
    excluded = waiting(org, "Maths")
    with tenant_context(org):
        excluded.student.excluded_tutors.add(tutor)
    waiting(org, "Physics")
    free_up(org, tutor)
    free_up(org, unapproved)
    assert open_suggestions(org) == []
    assert named.status == "waiting"


def test_full_tutor_gets_no_suggestion(org, monkeypatch):
    """A tutor at their weekly hours limit has no room."""
    tutor = teaching(org, "Maths", max_weekly_hours=2)
    waiting(org, "Maths")
    with tenant_context(org):
        assert suggestions.has_room(tutor) is True
    booked = {str(tutor.pk): 4 * 90}  # 1.5 hours a week over the next four weeks
    monkeypatch.setattr("tutortrack.scheduling.selectors.scheduled_minutes", lambda *a, **k: booked)
    with tenant_context(org):
        assert suggestions.has_room(tutor) is False
    free_up(org, tutor)
    assert open_suggestions(org) == []


def test_gender_preference_applies_only_when_turned_on(org):
    from tutortrack.tenancy import settings_service

    tutor = teaching(org, "Maths", gender="male")
    entry = waiting(org, "Maths")
    with tenant_context(org):
        people.update_student(entry.student, tutor_gender_preference="female")
        settings_service.update_settings("matching", {"matching.gender_preference": True})
    free_up(org, tutor)
    assert open_suggestions(org) == []
    with tenant_context(org):
        settings_service.update_settings("matching", {"matching.gender_preference": False})
    free_up(org, tutor)
    assert len(open_suggestions(org)) == 1


def test_a_job_ending_suggests_its_tutor(org):
    from tutortrack.catalogue.tests.factories import ServiceFactory
    from tutortrack.jobs import services as jobs

    tutor = teaching(org, "Maths")
    entry = waiting(org, "Maths")
    with tenant_context(org):
        subject = TutorSubject.objects.get(tutor=tutor).catalogue_subject
        service = ServiceFactory(organisation=org, subject=subject)
        family = ClientFactory(organisation=org)
        student = StudentFactory(organisation=org, client=family)
        job = jobs.create_job(
            client=family,
            service=service,
            subject=subject,
            students=[{"student": student}],
            status="seeking_tutor",
        )
        jobs.add_tutor(job, tutor=tutor)
        job.refresh_from_db()
        if job.status != "active":
            jobs.change_status(job, "active")
    dispatch_batch()
    assert open_suggestions(org) == []
    with tenant_context(org):
        jobs.change_status(job, "completed")
    dispatch_batch()
    found = open_suggestions(org)
    assert [(s.entry_id, s.reason) for s in found] == [(entry.pk, "job_ended")]


def test_offering_from_a_suggestion_closes_the_others(org, coordinator):
    first = teaching(org, "Maths")
    second = teaching(org, "Maths")
    entry = waiting(org, "Maths")
    free_up(org, first)
    free_up(org, second)
    found = {s.tutor_id: s for s in open_suggestions(org)}
    assert set(found) == {first.pk, second.pk}
    with tenant_context(org):
        done = suggestions.offer_from_suggestion(found[first.pk], user=coordinator.user)
        entry.refresh_from_db()
        other = WaitlistSuggestion.objects.get(pk=found[second.pk].pk)
        assert (done.status, other.status) == ("offered", "closed")
        assert entry.status == "offered"
        assert first.full_name in entry.offer_details
        with pytest.raises(BusinessRuleViolation):
            suggestions.dismiss(other, user=coordinator.user)


def test_a_dismissed_suggestion_is_not_raised_again(org, coordinator):
    tutor = teaching(org, "Maths")
    waiting(org, "Maths")
    free_up(org, tutor)
    (suggestion,) = open_suggestions(org)
    with tenant_context(org):
        suggestions.dismiss(suggestion, user=coordinator.user)
    free_up(org, tutor)
    assert open_suggestions(org) == []


def test_removing_the_student_closes_suggestions(org):
    tutor = teaching(org, "Maths")
    entry = waiting(org, "Maths")
    free_up(org, tutor)
    with tenant_context(org):
        services.remove_from_waitlist(entry)
        assert WaitlistSuggestion.objects.get().status == "closed"


def test_api_lists_offers_and_dismisses(org, coordinator):
    first = teaching(org, "Maths")
    second = teaching(org, "Maths")
    waiting(org, "Maths")
    waiting(org, "Maths")
    free_up(org, first)
    free_up(org, second)
    api = client_for(org, coordinator.user)
    rows = api.get("/api/v1/waitlist-suggestions").json()["results"]
    assert len(rows) == 4
    assert {r["position"] for r in rows} == {1, 2}
    offered = api.post(
        f"/api/v1/waitlist-suggestions/{rows[0]['id']}/offer",
        {"details": "Tuesdays 4pm", "hours": 24},
        format="json",
    )
    assert offered.status_code == 200, offered.content
    assert offered.json()["status"] == "offered"
    left = api.get("/api/v1/waitlist-suggestions").json()["results"]
    assert len(left) == 2  # the offered student's other suggestion closed
    dismissed = api.post(f"/api/v1/waitlist-suggestions/{left[0]['id']}/dismiss")
    assert dismissed.json()["status"] == "dismissed"
    again = api.post(f"/api/v1/waitlist-suggestions/{left[0]['id']}/dismiss")
    assert again.status_code == 422
    everything = api.get("/api/v1/waitlist-suggestions?status=all").json()["results"]
    assert len(everything) == 4


def test_tutors_cannot_see_suggestions(org):
    tutor = MembershipFactory(organisation=org, role="tutor")
    response = client_for(org, tutor.user).get("/api/v1/waitlist-suggestions")
    assert response.status_code == 403


class TestWaitlistSuggestionIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/waitlist-suggestions"

    def make_object(self, organisation: Any) -> WaitlistSuggestion:
        tutor = teaching(organisation, "Maths")
        entry = waiting(organisation, "Maths")
        with tenant_context(organisation):
            return WaitlistSuggestion.objects.create(
                entry=entry, tutor=tutor, reason="availability", branch_id=entry.branch_id
            )
