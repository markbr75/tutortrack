"""Gap batch G5a (E18): CV and video uploads on the application form (FR-18-1), the job-
opening editor (FR-18-1), compliance export and bulk document requests (FR-18-8), probation
reviews, performance notes and offboarding (FR-18-9), interview booking through the slot
engine (FR-18-2) and online subject tests (FR-18-3)."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, time, timedelta
from typing import Any

import pytest
from django.conf import settings
from django.test import Client as HttpClient

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent, StoredFile
from tutortrack.core.storage import public
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads.models import Form
from tutortrack.people.models import TutorProfile, TutorSubject
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.recruitment import catalogue, compliance, interviews, performance, services
from tutortrack.recruitment.models import (
    Interview,
    JobOpening,
    OffboardingChecklist,
    PerformanceNote,
    ProbationReview,
    TutorApplication,
)

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.5 my cv"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16


def anonymous(org: Any) -> HttpClient:
    return HttpClient(HTTP_HOST=f"{org.slug}.{settings.TENANT_BASE_DOMAIN}")


@pytest.fixture
def admin(org: Any) -> Any:
    with tenant_context(org):
        return MembershipFactory(organisation=org, role="admin").user


@pytest.fixture
def tutor(org: Any) -> TutorProfile:
    with tenant_context(org):
        membership = MembershipFactory(organisation=org, role="tutor")
        return TutorProfileFactory(organisation=org, status="active", membership=membership)


# --- FR-18-1: the job-opening editor and the standard application form ----------------------


def test_openings_editor_creates_the_standard_form_and_checks_slugs(org, admin):
    api = client_for(org, admin)
    created = api.post(
        "/api/v1/job-openings",
        {
            "title": "Maths tutors in Leeds",
            "description": "GCSE and A level",
            "subjects": ["Maths", {"subject": "Physics", "level": "A level"}],
            "location": "Leeds",
            "published": True,
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["slug"] == "maths-tutors-in-leeds"
    assert body["form_name"] == "Tutor application"
    assert body["subjects"] == [
        {"subject": "Maths", "level": ""},
        {"subject": "Physics", "level": "A level"},
    ]
    with tenant_context(org):
        form = Form.objects.get(pk=body["form"])
        assert form.type == "application"
        kinds = {f.get("file_kind") for s in form.schema["steps"] for f in s["fields"]}
        assert {"cv", "video"} <= kinds
    clash = api.post(
        "/api/v1/job-openings",
        {"title": "Other", "slug": "maths-tutors-in-leeds"},
        format="json",
    )
    assert clash.status_code == 422
    assert "slug" in clash.json()["errors"]
    with tenant_context(org):
        enquiry_form = Form.objects.create(
            name="Enquiry", slug="enq", schema={"steps": []}, published=True
        )
    wrong = api.patch(
        f"/api/v1/job-openings/{body['id']}", {"form": str(enquiry_form.pk)}, format="json"
    )
    assert wrong.status_code == 422
    edited = api.patch(
        f"/api/v1/job-openings/{body['id']}",
        {"closes_on": "2027-01-31", "published": False},
        format="json",
    )
    assert edited.status_code == 200
    assert (edited.json()["closes_on"], edited.json()["published"]) == ("2027-01-31", False)
    listed = api.get("/api/v1/job-openings").json()
    assert listed[0]["applications_open"] == 0
    default = api.post("/api/v1/job-openings/default-form").json()
    assert default["id"] == body["form"]  # created once, then reused


def test_only_pipeline_managers_edit_openings(org):
    with tenant_context(org):
        coordinator = MembershipFactory(organisation=org, role="coordinator").user
    response = client_for(org, coordinator).post(
        "/api/v1/job-openings", {"title": "Tutors"}, format="json"
    )
    assert response.status_code == 403


# --- FR-18-1: CV and video uploads ----------------------------------------------------------


def _opening(org: Any) -> JobOpening:
    with tenant_context(org):
        return services.save_opening(None, title="Tutors", published=True)


def _upload(org: Any, s3: Any, kind: str, data: bytes, content_type: str, name: str) -> str:
    client = anonymous(org)
    created = client.post(
        "/api/v1/public/uploads",
        data=json.dumps(
            {
                "target": "opening",
                "slug": "tutors",
                "kind": kind,
                "filename": name,
                "content_type": content_type,
                "size_bytes": len(data),
            }
        ),
        content_type="application/json",
    )
    assert created.status_code == 201, created.json()
    token = created.json()["token"]
    with tenant_context(org):
        stored = StoredFile.objects.get(pk=public.read_token(token).file_id)
    s3.put_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
        Key=stored.storage_key,
        Body=data,
        ContentType=content_type,
    )
    done = client.post(
        "/api/v1/public/uploads/complete",
        data=json.dumps({"token": token}),
        content_type="application/json",
    )
    assert done.status_code == 200, done.json()
    return token


APPLICANT = {
    "first_name": "Nia",
    "last_name": "Okafor",
    "email": "nia@example.com",
    "subjects": "Maths",
    "referees": [{"name": "Dr Ade", "email": "ade@example.com"}],
    "privacy": True,
}


def test_application_form_takes_a_cv_and_a_video(org, admin, s3):
    _opening(org)
    cv = _upload(org, s3, "cv", PDF, "application/pdf", "Nia CV.pdf")
    video = _upload(org, s3, "video", MP4, "video/mp4", "hello.mp4")
    # A CV slot doesn't take videos.
    bad = anonymous(org).post(
        "/api/v1/public/uploads",
        data=json.dumps(
            {
                "target": "opening",
                "slug": "tutors",
                "kind": "cv",
                "filename": "x.mp4",
                "content_type": "video/mp4",
                "size_bytes": 10,
            }
        ),
        content_type="application/json",
    )
    assert bad.json()["code"] == "file_type_not_allowed"
    response = anonymous(org).post(
        "/api/v1/public/job-openings/tutors",
        data=json.dumps({"data": {**APPLICANT, "cv": cv, "video": video}}),
        content_type="application/json",
    )
    assert response.status_code == 201, response.json()
    with tenant_context(org):
        application = TutorApplication.objects.get()
        assert application.cv.filename == "Nia CV.pdf"
        assert application.video.filename == "hello.mp4"
        assert application.cv.owner_object_id == str(application.pk)
    detail = client_for(org, admin).get(f"/api/v1/applications/{application.pk}").json()
    assert detail["cv_file"]["filename"] == "Nia CV.pdf"
    assert detail["video_file"]["content_type"] == "video/mp4"
    # A video token can't stand in for the CV.
    swapped = anonymous(org).post(
        "/api/v1/public/job-openings/tutors",
        data=json.dumps(
            {
                "data": {
                    **APPLICANT,
                    "email": "b@example.com",
                    "cv": _upload(org, s3, "video", MP4, "video/mp4", "b.mp4"),
                }
            }
        ),
        content_type="application/json",
    )
    assert swapped.status_code == 422
    assert "cv" in swapped.json()["errors"]


def test_closed_openings_take_no_uploads(org, s3):
    opening = _opening(org)
    with tenant_context(org):
        JobOpening.objects.filter(pk=opening.pk).update(closes_on=date(2020, 1, 1))
        assert services.upload_kinds_for_opening("tutors") is None
        JobOpening.objects.filter(pk=opening.pk).update(closes_on=None)
        assert services.upload_kinds_for_opening("tutors") == {"cv", "video"}


# --- FR-18-8: compliance export and bulk requests -------------------------------------------


def test_dashboard_filters_and_csv_export(org, admin, tutor):
    with tenant_context(org):
        TutorProfile.objects.filter(pk=tutor.pk).update(first_name="=HYPERLINK(1)")
        other = TutorProfileFactory(organisation=org, status="onboarding")
        compliance.ensure_requirement_types()
    api = client_for(org, admin)
    board = api.get("/api/v1/compliance/dashboard", {"tutor_status": "onboarding"}).json()
    assert [r["tutor"] for r in board["rows"]] == [str(other.pk)]
    one = api.get("/api/v1/compliance/dashboard", {"requirement": "dbs_enhanced"}).json()
    assert [r["key"] for r in one["requirements"]] == ["dbs_enhanced"]
    gaps = api.get("/api/v1/compliance/dashboard", {"gaps": "1"}).json()
    assert len(gaps["rows"]) == 2
    response = api.get("/api/v1/compliance/dashboard/export", {"requirement": "dbs_enhanced"})
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0][:3] == ["Tutor", "Email", "Tutor status"]
    assert rows[0][3:] == ["Enhanced DBS check", "Enhanced DBS check expiry"]
    names = {r[0] for r in rows[1:]}
    assert any(n.startswith("'=HYPERLINK") for n in names)  # formula injection neutralised
    assert {r[3] for r in rows[1:]} == {"Missing"}
    with tenant_context(org):
        from tutortrack.core.models import AuditEntry

        assert AuditEntry.objects.filter(action="export", object_repr="compliance dashboard")


def test_request_missing_documents_tells_each_tutor_once_a_day(org, admin, tutor):
    with tenant_context(org):
        compliance.ensure_requirement_types()
        other = TutorProfileFactory(organisation=org, status="active")
    api = client_for(org, admin)
    sent = api.post(
        "/api/v1/compliance/request-missing",
        {"tutors": [str(tutor.pk)], "requirements": ["dbs_enhanced"]},
        format="json",
    )
    assert sent.status_code == 200, sent.json()
    assert sent.json() == {
        "count": 1,
        "requests": [{"tutor": str(tutor.pk), "requirements": ["dbs_enhanced"]}],
    }
    with tenant_context(org):
        messages = Message.objects.filter(type_key="compliance_documents_requested")
        assert messages.count() == 2  # email and in-app
        assert "Enhanced DBS check" in messages.get(channel="email").body
        assert OutboxEvent.objects.filter(event_type="compliance.documents_requested").count() == 1
    api.post(
        "/api/v1/compliance/request-missing",
        {"tutors": [str(tutor.pk)], "requirements": ["dbs_enhanced"]},
        format="json",
    )
    with tenant_context(org):
        assert Message.objects.filter(type_key="compliance_documents_requested").count() == 2
    everyone = api.post("/api/v1/compliance/request-missing", {}, format="json").json()
    assert {r["tutor"] for r in everyone["requests"]} == {str(tutor.pk), str(other.pk)}
    with tenant_context(org):
        coordinator = MembershipFactory(organisation=org, role="coordinator").user
    forbidden = client_for(org, coordinator).post(
        "/api/v1/compliance/request-missing", {}, format="json"
    )
    assert forbidden.status_code == 403


# --- FR-18-9: probation reviews, performance notes and offboarding --------------------------


def test_probation_reviews_schedule_extend_and_pass(org, admin, tutor):
    api = client_for(org, admin)
    due = (date.today() + timedelta(days=30)).isoformat()
    created = api.post(
        "/api/v1/probation-reviews", {"tutor": str(tutor.pk), "due_on": due}, format="json"
    )
    assert created.status_code == 201, created.json()
    review = created.json()
    assert review["status"] == "scheduled"
    twice = api.post(
        "/api/v1/probation-reviews", {"tutor": str(tutor.pk), "due_on": due}, format="json"
    )
    assert twice.status_code == 422
    bad = api.post(
        f"/api/v1/probation-reviews/{review['id']}/complete",
        {"outcome": "extended", "extend_to": due},
        format="json",
    )
    assert bad.status_code == 422
    later = (date.today() + timedelta(days=60)).isoformat()
    extended = api.post(
        f"/api/v1/probation-reviews/{review['id']}/complete",
        {"outcome": "extended", "notes": "Punctuality", "extend_to": later},
        format="json",
    )
    assert extended.json()["status"] == "extended"
    listed = api.get("/api/v1/probation-reviews", {"tutor": str(tutor.pk)}).json()["results"]
    assert [r["status"] for r in listed] == ["scheduled", "extended"]
    assert listed[0]["due_on"] == later
    passed = api.post(
        f"/api/v1/probation-reviews/{listed[0]['id']}/complete",
        {"outcome": "passed", "notes": "Great"},
        format="json",
    )
    assert passed.json()["status"] == "passed"
    with tenant_context(org):
        types = set(
            OutboxEvent.objects.filter(event_type__startswith="probation.").values_list(
                "event_type", flat=True
            )
        )
    assert types == {"probation.scheduled", "probation.completed"}


def test_first_probation_review_follows_activation(org, tutor, settings):
    with tenant_context(org):
        review = performance.schedule_after_activation(tutor.pk)
        assert review is not None
        assert review.due_on == compliance.today() + timedelta(days=90)
        assert performance.schedule_after_activation(tutor.pk) is None  # idempotent


def test_performance_notes(org, admin, tutor):
    api = client_for(org, admin)
    added = api.post(
        "/api/v1/performance-notes",
        {"tutor": str(tutor.pk), "kind": "praise", "body": "Great feedback"},
        format="json",
    )
    assert added.status_code == 201, added.json()
    assert added.json()["author_name"]
    listed = api.get("/api/v1/performance-notes", {"tutor": str(tutor.pk)}).json()["results"]
    assert [n["body"] for n in listed] == ["Great feedback"]
    tutor_api = client_for(org, tutor.membership.user)
    assert tutor_api.get("/api/v1/performance-notes").status_code == 403
    assert api.delete(f"/api/v1/performance-notes/{listed[0]['id']}").status_code == 204
    with tenant_context(org):
        assert not PerformanceNote.objects.exists()


def test_offboarding_checklist(org, admin, tutor):
    api = client_for(org, admin)
    url = f"/api/v1/tutors/{tutor.pk}/offboarding"
    assert api.get(url).json()["id"] is None
    with tenant_context(org):
        performance.schedule_probation(tutor, due_on=date.today() + timedelta(days=10))
    started = api.post(url, {"reason": "Moving abroad", "leaving_on": "2026-12-20"}, format="json")
    assert started.status_code == 200, started.json()
    state = started.json()
    assert state["tutor_status"] == "inactive"
    done = {i["key"]: i["done"] for i in state["items"]}
    assert done == {
        "jobs": True,
        "lessons": True,
        "access": False,
        "final_pay": True,
        "equipment": False,
        "records": False,
    }
    with tenant_context(org):
        assert ProbationReview.objects.get().status == "cancelled"
    assert api.post(f"{url}/complete").status_code == 422
    assert api.post(f"{url}/access/done").status_code == 422  # ticks itself
    api.post(f"{url}/equipment/done")
    api.post(f"{url}/records/done")
    revoked = api.post(f"{url}/revoke-access").json()
    assert all(i["done"] for i in revoked["items"])
    finished = api.post(f"{url}/complete").json()
    assert finished["completed_at"]
    assert finished["tutor_status"] == "archived"
    with tenant_context(org):
        tutor.membership.refresh_from_db()
        assert tutor.membership.status == "removed"
        assert OutboxEvent.objects.filter(event_type="offboarding.completed").exists()
        assert OffboardingChecklist.objects.get().completed_at is not None


def test_offboarding_waits_for_jobs_and_lessons(org, admin, tutor):
    from tutortrack.catalogue.tests.factories import ServiceFactory
    from tutortrack.jobs import services as jobs
    from tutortrack.jobs.models import JobTutor
    from tutortrack.people.tests.factories import ClientFactory, StudentFactory

    with tenant_context(org):
        family = ClientFactory(organisation=org)
        job = jobs.create_job(
            client=family,
            service=ServiceFactory(organisation=org),
            students=[{"student": StudentFactory(organisation=org, client=family)}],
            tutors=[{"tutor": tutor}],
            status="active",
        )
        assert JobTutor.objects.filter(job=job, tutor=tutor).exists()
        checklist = performance.start_offboarding(tutor, reason="Leaving", user=admin)
        state = {i["key"]: i["done"] for i in performance.offboarding_state(checklist)}
        assert state["jobs"] is False
        JobTutor.objects.filter(job=job).update(status=JobTutor.Status.ENDED)
        state = {i["key"]: i["done"] for i in performance.offboarding_state(checklist)}
        assert state["jobs"] is True


# --- FR-18-2: interview booking through the slot engine -------------------------------------


def _application(org: Any) -> TutorApplication:
    opening = _opening(org)
    with tenant_context(org):
        return services.apply(opening, dict(APPLICANT))


def _next_weekday() -> date:
    day = date.today() + timedelta(days=2)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def test_booking_link_offers_the_interviewers_free_time(org, admin):
    application = _application(org)
    day = _next_weekday()
    with tenant_context(org):
        _interview, token = services.propose_interview(
            application,
            interviewer=admin,
            mode=Interview.Mode.AVAILABILITY,
            window_start=day,
            window_end=day,
            minutes=60,
        )
    page = anonymous(org).get(f"/api/v1/public/interviews/{token}").json()
    assert page["mode"] == "availability"
    options = page["options"]
    # Office hours 09:00-17:00 local, hourly interviews on a 30-minute step: 15 starts.
    assert len(options) == 15
    first = datetime.fromisoformat(options[0])
    with tenant_context(org):
        from zoneinfo import ZoneInfo

        local = first.astimezone(ZoneInfo(org.timezone))
    assert (local.date(), local.time()) == (day, time(9, 0))
    booked = anonymous(org).post(
        f"/api/v1/public/interviews/{token}",
        data=json.dumps({"start": options[0]}),
        content_type="application/json",
    )
    assert booked.status_code == 200, booked.json()
    assert booked.json()["status"] == "booked"
    with tenant_context(org):
        assert OutboxEvent.objects.filter(event_type="application.interview_booked").exists()
        # A second applicant can't take the same slot.
        _second, token2 = services.propose_interview(
            _second_application(org),
            interviewer=admin,
            mode=Interview.Mode.AVAILABILITY,
            window_start=day,
            window_end=day,
            minutes=60,
        )
    page2 = anonymous(org).get(f"/api/v1/public/interviews/{token2}").json()
    assert options[0] not in page2["options"]
    assert options[1] not in page2["options"]  # 09:30 would overlap the 09:00 interview
    taken = anonymous(org).post(
        f"/api/v1/public/interviews/{token2}",
        data=json.dumps({"start": options[0]}),
        content_type="application/json",
    )
    assert taken.status_code == 422
    assert taken.json()["code"] == "slot_taken"


def _second_application(org: Any) -> TutorApplication:
    opening = JobOpening.objects.get(slug="tutors")
    return services.apply(opening, {**APPLICANT, "email": "sam@example.com"})


def test_interviewers_who_tutor_use_their_availability(org, tutor):
    from tutortrack.scheduling.models import AvailabilityTemplate, AvailabilityWindow

    day = _next_weekday()
    with tenant_context(org):
        template = AvailabilityTemplate.objects.create(
            tutor=tutor, effective_from=date.today(), timezone=org.timezone
        )
        AvailabilityWindow.objects.create(
            template=template, weekday=day.weekday(), start_time=time(18), end_time=time(19)
        )
        slots = interviews.interviewer_slots(tutor.membership.user, start=day, end=day, minutes=30)
        assert len(slots) == 2
        with pytest.raises(Exception, match="no free time"):
            services.propose_interview(
                _application(org),
                interviewer=tutor.membership.user,
                mode=Interview.Mode.AVAILABILITY,
                window_start=day + timedelta(days=1),
                window_end=day + timedelta(days=1),
            )


def test_booking_window_is_checked(org, admin):
    application = _application(org)
    with tenant_context(org), pytest.raises(Exception, match="four weeks"):
        services.propose_interview(
            application,
            interviewer=admin,
            mode=Interview.Mode.AVAILABILITY,
            window_start=date.today() + timedelta(days=1),
            window_end=date.today() + timedelta(days=40),
        )


def test_staff_send_a_booking_link_through_the_api(org, admin, django_capture_on_commit_callbacks):
    application = _application(org)
    day = _next_weekday()
    with tenant_context(org), django_capture_on_commit_callbacks(execute=True):
        response = client_for(org, admin).post(
            f"/api/v1/applications/{application.pk}/interviews",
            {
                "mode": "availability",
                "window_start": day.isoformat(),
                "window_end": day.isoformat(),
            },
            format="json",
        )
    assert response.status_code == 200, response.json()
    [interview] = response.json()["interviews"]
    assert (interview["mode"], interview["window_start"]) == ("availability", day.isoformat())
    with tenant_context(org):
        assert Message.objects.filter(type_key="interview_invite").exists()


# --- FR-18-3: online subject tests ----------------------------------------------------------


@pytest.fixture
def maths_test(org: Any, admin: Any) -> Any:
    from tutortrack.catalogue.tests.factories import SubjectFactory
    from tutortrack.learning import services as learning

    with tenant_context(org):
        subject = SubjectFactory(organisation=org, name="Maths")
        return learning.save_quiz(
            None,
            user=admin,
            title="Maths screening",
            subject=subject,
            purpose="tutor_test",
            pass_percent=50,
            questions=[
                {
                    "kind": "single",
                    "prompt": "2 + 2?",
                    "choices": [{"id": "a", "text": "3"}, {"id": "b", "text": "4"}],
                    "answer": ["b"],
                },
                {"kind": "short", "prompt": "Square root of 81?", "answer": ["9", "nine"]},
            ],
        )


def test_tutors_take_subject_tests_and_passing_assesses_the_subject(org, admin, tutor, maths_test):
    from tutortrack.people.services import set_tutor_subjects

    with tenant_context(org):
        set_tutor_subjects(tutor, [{"subject": "Maths", "level": "GCSE"}])
    api = client_for(org, tutor.membership.user)
    [entry] = api.get("/api/v1/me/subject-tests").json()
    assert (entry["title"], entry["status"], entry["can_take"]) == (
        "Maths screening",
        "not_taken",
        True,
    )
    assert entry["subjects"] == ["Maths GCSE"]
    detail = api.get(f"/api/v1/me/subject-tests/{maths_test.pk}").json()
    assert len(detail["questions"]) == 2
    assert "answer" not in detail["questions"][0]
    q1, q2 = (q["id"] for q in detail["questions"])
    result = api.post(
        f"/api/v1/me/subject-tests/{maths_test.pk}",
        {"answers": {q1: "b", q2: "Nine"}},
        format="json",
    )
    assert result.status_code == 200, result.json()
    assert result.json()["passed"] is True
    assert result.json()["assessed"] == ["Maths GCSE"]
    with tenant_context(org):
        subject = TutorSubject.objects.get(tutor=tutor)
        assert subject.competency == "assessed"
        assert "Maths screening" in subject.evidence
        assert subject.approved is False
    again = api.post(f"/api/v1/me/subject-tests/{maths_test.pk}", {"answers": {}}, format="json")
    assert again.status_code == 422
    staff = client_for(org, admin).get(f"/api/v1/tutors/{tutor.pk}/subject-tests").json()
    assert [(a["title"], a["passed"]) for a in staff] == [("Maths screening", True)]


def test_a_failed_test_waits_before_a_retake(org, tutor, maths_test):
    from tutortrack.people.services import set_tutor_subjects

    with tenant_context(org):
        set_tutor_subjects(tutor, [{"subject": "Maths", "level": ""}])
    api = client_for(org, tutor.membership.user)
    failed = api.post(f"/api/v1/me/subject-tests/{maths_test.pk}", {"answers": {}}, format="json")
    assert failed.json()["passed"] is False
    [entry] = api.get("/api/v1/me/subject-tests").json()
    assert (entry["status"], entry["can_take"]) == ("failed", False)
    assert entry["retake_at"]
    retake = api.post(f"/api/v1/me/subject-tests/{maths_test.pk}", {"answers": {}}, format="json")
    assert retake.json()["code"] == "retake_too_soon"
    with tenant_context(org):
        assert TutorSubject.objects.get(tutor=tutor).competency == "claimed"


def test_tests_for_other_subjects_are_hidden(org, tutor, maths_test):
    from tutortrack.people.services import set_tutor_subjects

    with tenant_context(org):
        set_tutor_subjects(tutor, [{"subject": "French", "level": ""}])
    api = client_for(org, tutor.membership.user)
    assert api.get("/api/v1/me/subject-tests").json() == []
    assert api.get(f"/api/v1/me/subject-tests/{maths_test.pk}").status_code == 404


def test_offboarding_catalogue_matches_auto_checks():
    assert {i["key"] for i in catalogue.OFFBOARDING if i["auto"]} == {
        "jobs",
        "lessons",
        "access",
        "final_pay",
    }


# --- cross-tenant isolation -----------------------------------------------------------------


class TestProbationReviewIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/probation-reviews"

    def make_object(self, organisation: Any) -> ProbationReview:
        with tenant_context(organisation):
            tutor = TutorProfileFactory(organisation=organisation, status="active")
            return ProbationReview.objects.create(tutor=tutor, due_on=date.today())


class TestPerformanceNoteIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/performance-notes"

    def make_object(self, organisation: Any) -> PerformanceNote:
        with tenant_context(organisation):
            tutor = TutorProfileFactory(organisation=organisation, status="active")
            return PerformanceNote.objects.create(tutor=tutor, body="Note")


def test_offboarding_of_another_organisations_tutor_is_404(org, other_org, admin):
    with tenant_context(other_org):
        theirs = TutorProfileFactory(organisation=other_org, status="active")
    api = client_for(org, admin)
    assert api.get(f"/api/v1/tutors/{theirs.pk}/offboarding").status_code == 404
    assert api.get(f"/api/v1/tutors/{theirs.pk}/subject-tests").status_code == 404
