"""E09-T09: client feedback micro-surveys (FR-09-9): who is asked, consent rules, the public
answer link, low-score alerts, E25 review invitations, the staff API and E19 ratings."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.delivery import feedback, selectors, services
from tutortrack.delivery.models import LessonFeedback
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)
from tutortrack.scheduling import services as scheduling
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(org):
    family = ClientFactory(organisation=org, display_name="The Patels")
    contact = ContactFactory(
        organisation=org, client=family, first_name="Priya", email="priya@example.com"
    )
    family.primary_contact = contact
    with tenant_context(org):
        family.save(update_fields=["primary_contact"])
    student = StudentFactory(organisation=org, client=family, first_name="Arjun")
    membership = MembershipFactory(organisation=org, role="tutor")
    tutor = TutorProfileFactory(
        organisation=org, status="active", first_name="Nia", membership=membership
    )
    return {
        "client": family,
        "contact": contact,
        "student": student,
        "tutor": tutor,
        "tutor_user": membership.user,
        "service": ServiceFactory(organisation=org, name="Maths 1:1"),
    }


@pytest.fixture
def enabled(org):
    with tenant_context(org):
        settings_service.update_settings(
            "delivery",
            {"delivery.feedback_every_n_lessons": 1},
        )


def completed_lesson(org, people, *, days_ago=1, outcome="present", student=None):
    start = (now() - timedelta(days=days_ago)).replace(minute=0, second=0, microsecond=0)
    student = student or people["student"]
    with tenant_context(org):
        lesson = scheduling.create_lesson(
            start=start,
            end=start + timedelta(hours=1),
            service=people["service"],
            attendees=[{"student": student}],
            tutors=[{"tutor": people["tutor"]}],
            timezone="Europe/London",
            override_conflicts=True,
        ).lesson
        attendee = lesson.attendees.get()
        services.complete_lesson(
            lesson,
            attendance=[services.AttendanceRow(attendee_id=attendee.pk, outcome=outcome)],
        )
    return lesson


def send(org, lesson, capture):
    with tenant_context(org), capture(execute=True):
        return feedback.send_for_lesson(lesson.pk)


def test_feedback_is_sent_to_the_family_once(
    org, people, enabled, django_capture_on_commit_callbacks
):
    lesson = completed_lesson(org, people)
    sent = send(org, lesson, django_capture_on_commit_callbacks)
    assert len(sent) == 1
    with tenant_context(org):
        item = LessonFeedback.objects.get()
        assert (item.status, item.contact_id, item.tutor_id) == (
            "sent",
            people["contact"].pk,
            people["tutor"].pk,
        )
        message = Message.objects.get(type_key="lesson_feedback_request")
        assert message.recipient_id == str(people["contact"].pk)
        assert "/feedback/" in message.body
        assert OutboxEvent.objects.filter(event_type="lesson_feedback.requested").count() == 1
    assert send(org, lesson, django_capture_on_commit_callbacks) == []  # idempotent


def test_absent_students_are_not_asked(org, people, enabled, django_capture_on_commit_callbacks):
    lesson = completed_lesson(org, people, outcome="no_show")
    assert send(org, lesson, django_capture_on_commit_callbacks) == []


def test_asks_after_the_first_lesson_and_then_every_nth(
    org, people, enabled, django_capture_on_commit_callbacks
):
    with tenant_context(org):
        settings_service.update_settings("delivery", {"delivery.feedback_every_n_lessons": 2})
    lessons = [completed_lesson(org, people, days_ago=d) for d in (5, 4, 3)]
    asked = [bool(send(org, lesson, django_capture_on_commit_callbacks)) for lesson in lessons]
    assert asked == [True, False, True]


def test_contacts_who_do_not_receive_updates_are_skipped(
    org, people, enabled, django_capture_on_commit_callbacks
):
    with tenant_context(org):
        type(people["contact"]).objects.filter(pk=people["contact"].pk).update(
            receives_reports=False
        )
    lesson = completed_lesson(org, people)
    assert send(org, lesson, django_capture_on_commit_callbacks) == []
    with tenant_context(org):
        item = LessonFeedback.objects.get()
        assert (item.status, item.skip_reason) == ("skipped", "no_recipient")
        assert not Message.objects.filter(type_key="lesson_feedback_request").exists()


def test_a_withdrawn_feedback_consent_is_respected(
    org, people, enabled, django_capture_on_commit_callbacks
):
    from tutortrack.privacy.models import ConsentType
    from tutortrack.privacy.services import record_consent

    with tenant_context(org):
        ConsentType.objects.create(
            key="lesson-feedback", name="Lesson feedback requests", category="other"
        )
        record_consent(
            subject_type="people.contact",
            subject_id=str(people["contact"].pk),
            key="lesson-feedback",
            granted=False,
            method="portal",
        )
    lesson = completed_lesson(org, people)
    assert send(org, lesson, django_capture_on_commit_callbacks) == []
    with tenant_context(org):
        assert LessonFeedback.objects.get().skip_reason == "no_consent"


def test_comms_unsubscribe_from_reports_applies(
    org, people, enabled, django_capture_on_commit_callbacks
):
    from tutortrack.comms import services as comms

    with tenant_context(org):
        comms.set_preference("contact", str(people["contact"].pk), "reports", [])
    lesson = completed_lesson(org, people)
    send(org, lesson, django_capture_on_commit_callbacks)
    with tenant_context(org):
        sent = Message.objects.filter(type_key="lesson_feedback_request", status="sent")
        assert not sent.exists()


# --- answering ----------------------------------------------------------------------------------


def make_request(org, people, capture):
    lesson = completed_lesson(org, people)
    send(org, lesson, capture)
    with tenant_context(org):
        item = LessonFeedback.objects.get(lesson=lesson)
        return item, feedback.token_for(item)


def test_family_answers_from_the_link(org, people, enabled, django_capture_on_commit_callbacks):
    item, token = make_request(org, people, django_capture_on_commit_callbacks)
    public = client_for(org)
    shown = public.get(f"/api/v1/public/lesson-feedback/{token}").json()
    assert (shown["student"], shown["tutor"], shown["status"]) == ("Arjun", "Nia", "sent")
    assert "email" not in str(shown).lower()
    response = public.post(
        f"/api/v1/public/lesson-feedback/{token}", {"rating": 5, "comment": "Great!"}, format="json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "answered"
    with tenant_context(org):
        item.refresh_from_db()
        assert (item.rating, item.comment) == (5, "Great!")
        event = OutboxEvent.objects.get(event_type="lesson_feedback.received")
        assert event.payload["data"]["rating"] == 5
        assert "Great" not in str(event.payload)  # comments stay out of events
    again = public.post(f"/api/v1/public/lesson-feedback/{token}", {"rating": 4}, format="json")
    assert again.status_code == 422
    assert again.json()["code"] == "answered"


def test_bad_answers_and_tokens(org, people, enabled, django_capture_on_commit_callbacks):
    item, token = make_request(org, people, django_capture_on_commit_callbacks)
    public = client_for(org)
    assert (
        public.post(f"/api/v1/public/lesson-feedback/{token}", {"rating": 6}, format="json")
    ).status_code == 400
    assert public.get("/api/v1/public/lesson-feedback/not-a-token").status_code == 404
    with tenant_context(org):
        LessonFeedback.objects.filter(pk=item.pk).update(expires_at=now() - timedelta(minutes=1))
    expired = public.post(f"/api/v1/public/lesson-feedback/{token}", {"rating": 3}, format="json")
    assert expired.status_code == 422
    assert expired.json()["code"] == "expired"


def test_tokens_do_not_work_for_another_organisation(
    org, other_org, people, enabled, django_capture_on_commit_callbacks
):
    _item, token = make_request(org, people, django_capture_on_commit_callbacks)
    assert client_for(other_org).get(f"/api/v1/public/lesson-feedback/{token}").status_code == 404


def test_low_scores_alert_staff(org, people, enabled, django_capture_on_commit_callbacks):
    MembershipFactory(organisation=org, role="admin")
    item, token = make_request(org, people, django_capture_on_commit_callbacks)
    with tenant_context(org), django_capture_on_commit_callbacks(execute=True):
        feedback.answer(token, rating=2, comment="Late again")
    with tenant_context(org):
        item.refresh_from_db()
        assert item.low_score_alerted
        assert Message.objects.filter(type_key="staff_lesson_feedback_low").exists()


def test_five_stars_can_invite_a_public_review(
    org, people, enabled, django_capture_on_commit_callbacks
):
    from tutortrack.growth.models import ReviewRequest

    with tenant_context(org):
        settings_service.update_settings("delivery", {"delivery.feedback_invites_review": True})
    _item, token = make_request(org, people, django_capture_on_commit_callbacks)
    with tenant_context(org):
        feedback.answer(token, rating=5)
        request = ReviewRequest.objects.get()
        assert (request.client_id, request.tutor_id, request.trigger) == (
            people["client"].pk,
            people["tutor"].pk,
            "automation",
        )


# --- staff API ----------------------------------------------------------------------------------


def test_staff_list_summary_and_withdraw(org, people, enabled, django_capture_on_commit_callbacks):
    item, token = make_request(org, people, django_capture_on_commit_callbacks)
    with tenant_context(org):
        feedback.answer(token, rating=4)
    other = StudentFactory(organisation=org, client=people["client"], first_name="Maya")
    lesson = completed_lesson(org, people, student=other)
    send(org, lesson, django_capture_on_commit_callbacks)
    staff = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    rows = staff.get("/api/v1/lesson-feedback").json()["results"]
    assert {r["status"] for r in rows} == {"answered", "sent"}
    assert staff.get("/api/v1/lesson-feedback", {"rating": "4"}).json()["results"][0]["id"] == str(
        item.pk
    )
    summary = staff.get("/api/v1/lesson-feedback/summary").json()
    assert (summary["asked"], summary["answered"], summary["average"]) == (2, 1, "4.0")
    assert summary["answer_rate"] == "50.0"
    assert summary["tutors"][0]["tutor"] == "Nia " + people["tutor"].last_name
    open_one = next(r for r in rows if r["status"] == "sent")
    withdrawn = staff.post(f"/api/v1/lesson-feedback/{open_one['id']}/withdraw")
    assert withdrawn.json()["status"] == "expired"
    assert staff.post(f"/api/v1/lesson-feedback/{item.pk}/withdraw").status_code == 422


def test_tutors_see_feedback_on_their_own_lessons_only(
    org, people, enabled, django_capture_on_commit_callbacks
):
    make_request(org, people, django_capture_on_commit_callbacks)
    other_tutor = TutorProfileFactory(organisation=org)
    with tenant_context(org):
        LessonFeedback.objects.create(
            lesson=completed_lesson(org, people, days_ago=3),
            student=people["student"],
            client=people["client"],
            tutor=other_tutor,
            lesson_date=now().date(),
            expires_at=now() + timedelta(days=7),
        )
    tutor = client_for(org, people["tutor_user"])
    rows = tutor.get("/api/v1/lesson-feedback").json()["results"]
    assert [r["tutor"]["id"] for r in rows] == [str(people["tutor"].pk)]
    assert tutor.post(f"/api/v1/lesson-feedback/{rows[0]['id']}/withdraw").status_code == 403
    client_user = MembershipFactory(organisation=org, role="client").user
    assert client_for(org, client_user).get("/api/v1/lesson-feedback").status_code == 403


class TestLessonFeedbackIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/lesson-feedback"

    def make_object(self, organisation):
        family = ClientFactory(organisation=organisation)
        student = StudentFactory(organisation=organisation, client=family)
        service = ServiceFactory(organisation=organisation)
        start = (now() - timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
        with tenant_context(organisation):
            lesson = scheduling.create_lesson(
                start=start,
                end=start + timedelta(hours=1),
                service=service,
                attendees=[{"student": student}],
                tutors=[],
                timezone="Europe/London",
                override_conflicts=True,
            ).lesson
            return LessonFeedback.objects.create(
                lesson=lesson,
                student=student,
                client=family,
                lesson_date=start.date(),
                expires_at=now() + timedelta(days=7),
            )


# --- E19 ratings --------------------------------------------------------------------------------


def test_feedback_feeds_matching_ratings(org, people, enabled, django_capture_on_commit_callbacks):
    from tutortrack.matching.engine import blend_ratings

    _item, token = make_request(org, people, django_capture_on_commit_callbacks)
    with tenant_context(org):
        feedback.answer(token, rating=3)
        ratings = selectors.tutor_feedback_ratings([people["tutor"].pk])
    assert ratings == {str(people["tutor"].pk): (3.0, 1)}
    blended = blend_ratings({"t": (5.0, 3)}, {"t": (3.0, 1)}, {"u": (4.0, 2)})
    assert blended == {"t": 4.5, "u": 4.0}


def test_standard_report_shows_feedback_per_tutor(
    org, people, enabled, django_capture_on_commit_callbacks
):
    _item, token = make_request(org, people, django_capture_on_commit_callbacks)
    with tenant_context(org):
        feedback.answer(token, rating=2)
    other = StudentFactory(organisation=org, client=people["client"], first_name="Maya")
    send(org, completed_lesson(org, people, student=other), django_capture_on_commit_callbacks)
    staff = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    body = staff.get("/api/v1/reporting/reports/lesson_feedback", {"period": "last_30_days"}).json()
    [row] = body["rows"]
    assert (row["asked"], row["answered"], row["answer_rate"], row["average"], row["low"]) == (
        2,
        1,
        "50.0",
        "2.00",
        1,
    )
    assert body["totals"][0]["average"] == "2.00"


def test_feedback_is_in_dsar_exports_and_erased(
    org, people, enabled, django_capture_on_commit_callbacks
):
    from tutortrack.delivery import privacy
    from tutortrack.privacy import registry

    _item, token = make_request(org, people, django_capture_on_commit_callbacks)
    with tenant_context(org):
        feedback.answer(token, rating=4, comment="Arjun loved it")
        person = registry.resolve("people.client", str(people["client"].pk))
        [section] = [s for s in privacy.export(person) if s.key == "delivery.feedback"]
        assert section.records[0]["comment"] == "Arjun loved it"
        ctx = registry.ErasureContext(labels={}, financial_cutoff=now())
        ctx.prepare_scrub(person, "[erased]")
        privacy.erase(person, ctx)
        item = LessonFeedback.objects.get()
        assert (item.comment, item.rating) == ("", 4)
