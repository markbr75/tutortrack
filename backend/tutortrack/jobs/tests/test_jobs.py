"""E07-T01..T06: jobs, students, tutors, status machine, summary, hours cap, quick setup."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from tutortrack.catalogue.tests.factories import LevelFactory, ServiceFactory, SubjectFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for, result_ids
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.jobs import lessons, selectors, services
from tutortrack.jobs.models import Job, JobStatusHistory, JobTutor
from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory

pytestmark = pytest.mark.django_db


def gbp(amount):
    return {"amount": amount, "currency": "GBP"}


def api_as(org, role):
    membership = MembershipFactory(organisation=org, role=role)
    return client_for(org, membership.user), membership


@pytest.fixture
def admin_api(org):
    return api_as(org, "admin")[0]


@pytest.fixture
def family(org):
    client = ClientFactory(organisation=org)
    student = StudentFactory(organisation=org, client=client, first_name="Arjun", last_name="Patel")
    return client, student


def make_job(org, *, tutor=None, status="draft", **fields):
    with tenant_context(org):
        client = fields.pop("client", None) or ClientFactory(organisation=org)
        student = fields.pop("student", None) or StudentFactory(organisation=org, client=client)
        service = fields.pop("service", None) or ServiceFactory(organisation=org)
        return services.create_job(
            client=client,
            service=service,
            students=[{"student": student}],
            tutors=[{"tutor": tutor}] if tutor else [],
            status=status,
            **fields,
        )


def events(org, kind):
    with tenant_context(org):
        return [
            e.payload["data"]
            for e in OutboxEvent.objects.filter(event_type=kind).order_by("occurred_at")
        ]


# --- creation (FR-07-1) -------------------------------------------------------------------------


def test_create_job_with_reference_and_auto_name(org, admin_api, family):
    client, student = family
    maths = SubjectFactory(organisation=org, name="Maths")
    gcse = LevelFactory(organisation=org, subject=maths, name="GCSE")
    service = ServiceFactory(organisation=org, subject=maths, level=gcse)
    response = admin_api.post(
        "/api/v1/jobs",
        {
            "client": str(client.pk),
            "service": str(service.pk),
            "student_inputs": [{"student": str(student.pk)}],
            "charge_rate": gbp("42.00"),
            "default_schedule": [{"weekday": 0, "time": "16:30"}],
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["reference"] == "JOB-000001"
    assert body["name"] == "GCSE Maths \N{EN DASH} Arjun Patel"
    assert (body["status"], body["currency"]) == ("draft", "GBP")
    assert body["students"][0]["student_name"] == "Arjun Patel"
    assert body["default_schedule"] == [{"weekday": 0, "time": "16:30"}]
    assert events(org, "job.created")[0]["reference"] == "JOB-000001"
    second = make_job(org)
    assert second.reference == "JOB-000002"


def test_students_must_belong_to_the_client_and_fit_the_service(org, tenant, family):
    client, student = family
    stranger = StudentFactory(organisation=org)
    service = ServiceFactory(organisation=org)
    with pytest.raises(BusinessRuleViolation, match="belong to the job's client"):
        services.create_job(client=client, service=service, students=[{"student": stranger}])
    sibling = StudentFactory(organisation=org, client=client)
    with pytest.raises(BusinessRuleViolation, match="at most 1"):
        services.create_job(
            client=client, service=service, students=[{"student": student}, {"student": sibling}]
        )
    with pytest.raises(BusinessRuleViolation, match="at least one student"):
        services.create_job(client=client, service=service, students=[])


def test_rate_overrides_must_use_job_currency(org, tenant, family):
    client, student = family
    with pytest.raises(BusinessRuleViolation, match="GBP"):
        services.create_job(
            client=client,
            service=ServiceFactory(organisation=org),
            students=[{"student": student, "charge_rate_override": Money("40", "EUR")}],
        )


# --- tutors (FR-07-3) ---------------------------------------------------------------------------


def test_assigning_a_tutor_activates_a_seeking_job(org, admin_api):
    job = make_job(org, status="seeking_tutor")
    tutor = TutorProfileFactory(organisation=org, status="active")
    response = admin_api.post(
        f"/api/v1/jobs/{job.pk}/tutors",
        {"tutor": str(tutor.pk), "pay_rate_override": gbp("27.00")},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["pay_rate_override"] == {"amount": "27.0000", "currency": "GBP"}
    assert admin_api.get(f"/api/v1/jobs/{job.pk}").json()["status"] == "active"
    assert events(org, "job.tutor_assigned")[0]["tutor_id"] == str(tutor.pk)


def test_offer_is_accepted_by_the_tutor(org):
    membership = MembershipFactory(organisation=org, role="tutor")
    tutor = TutorProfileFactory(organisation=org, membership=membership, status="active")
    job = make_job(org, status="seeking_tutor")
    with tenant_context(org):
        link = services.add_tutor(job, tutor=tutor, offer=True)
        job.refresh_from_db()
    assert job.status == "seeking_tutor"
    tutor_api = client_for(org, membership.user)
    assert tutor_api.get(f"/api/v1/jobs/{job.pk}").status_code == 200  # offered tutors see it
    response = tutor_api.post(
        f"/api/v1/jobs/{job.pk}/tutors/{link.pk}/respond", {"accept": True}, format="json"
    )
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "active"
    with tenant_context(org):
        job.refresh_from_db()
    assert job.status == "active"


def test_unavailable_tutor_rejected(org, tenant):
    job = make_job(org)
    with pytest.raises(BusinessRuleViolation, match="isn't available"):
        services.add_tutor(job, tutor=TutorProfileFactory(organisation=org, status="inactive"))


def test_removing_the_last_tutor_returns_job_to_seeking(org, tenant):
    tutor = TutorProfileFactory(organisation=org, status="active")
    job = make_job(org, tutor=tutor, status="active")
    link = job.tutors.get()
    services.remove_tutor(link, end_date=date(2026, 11, 1))
    job.refresh_from_db()
    assert job.status == "seeking_tutor"
    assert (link.status, link.end_date) == ("ended", date(2026, 11, 1))


def test_replace_tutor_with_preview(org, admin_api, monkeypatch):
    old = TutorProfileFactory(organisation=org, status="active")
    new = TutorProfileFactory(organisation=org, status="active")
    job = make_job(org, tutor=old, status="active")
    with tenant_context(org):
        link = job.tutors.get()

    class FakeLessons(lessons._NoLessons):
        def future_lessons(self, job, tutor, from_date, new_tutor):
            from datetime import UTC, datetime

            return [
                lessons.AffectedLesson("l1", datetime(2026, 11, 2, 16, tzinfo=UTC)),
                lessons.AffectedLesson("l2", datetime(2026, 11, 9, 16, tzinfo=UTC), "Busy"),
            ]

    monkeypatch.setattr(lessons, "_provider", FakeLessons())
    url = f"/api/v1/jobs/{job.pk}/tutors/{link.pk}/replace"
    payload = {"tutor": str(new.pk), "effective_date": "2026-11-01"}
    preview = admin_api.post(url, {**payload, "dry_run": True}, format="json").json()
    assert (len(preview["lessons"]), preview["conflicts"], preview["new_assignment"]) == (
        2,
        1,
        None,
    )
    with tenant_context(org):
        assert job.tutors.get(status="active").tutor_id == old.pk
    done = admin_api.post(url, payload, format="json").json()
    assert done["new_assignment"]["tutor"] == str(new.pk)
    with tenant_context(org):
        link.refresh_from_db()
    assert (link.status, link.end_date) == ("ended", date(2026, 10, 31))
    assert events(org, "job.tutor_replaced")[0]["effective_date"] == "2026-11-01"


# --- status (FR-07-4) ---------------------------------------------------------------------------


def test_status_machine(org, admin_api):
    job = make_job(org)
    url = f"/api/v1/jobs/{job.pk}/status"
    assert admin_api.post(url, {"status": "active"}, format="json").status_code == 422
    assert admin_api.post(url, {"status": "paused"}, format="json").status_code == 422
    with tenant_context(org):
        services.add_tutor(job, tutor=TutorProfileFactory(organisation=org, status="active"))
    assert admin_api.post(url, {"status": "active"}, format="json").status_code == 200
    paused = admin_api.post(
        url, {"status": "paused", "reason": "Summer", "future_lessons": "cancel"}, format="json"
    )
    assert paused.json()["status"] == "paused"
    change = events(org, "job.status_changed")[-1]
    assert (change["to_status"], change["future_lessons"], change["reason"]) == (
        "paused",
        "cancel",
        "Summer",
    )
    admin_api.post(url, {"status": "cancelled"}, format="json")
    assert events(org, "job.status_changed")[-1]["future_lessons"] == "cancel"
    assert (
        admin_api.patch(f"/api/v1/jobs/{job.pk}", {"goals": "x"}, format="json").status_code == 422
    )
    with tenant_context(org):
        history = list(JobStatusHistory.objects.filter(job=job).values_list("to_status", flat=True))
    assert history == ["draft", "active", "paused", "cancelled"]


def test_completing_declines_open_offers(org, tenant):
    tutor = TutorProfileFactory(organisation=org, status="active")
    job = make_job(org, tutor=tutor, status="active")
    offered = services.add_tutor(
        job, tutor=TutorProfileFactory(organisation=org, status="active"), offer=True
    )
    services.change_status(job, "completed")
    offered.refresh_from_db()
    assert offered.status == JobTutor.Status.DECLINED


# --- permissions and visibility (AC FR-07-1) ------------------------------------------------------


def test_tutor_sees_own_jobs_without_charge_rates_or_internal_notes(org):
    tutor_api, membership = api_as(org, "tutor")
    tutor = TutorProfileFactory(organisation=org, membership=membership, status="active")
    mine = make_job(
        org, tutor=tutor, status="active", charge_rate=Money("42", "GBP"), notes_internal="secret"
    )
    make_job(org)
    listed = tutor_api.get("/api/v1/jobs")
    assert result_ids(listed) == {str(mine.pk)}
    body = tutor_api.get(f"/api/v1/jobs/{mine.pk}").json()
    assert "charge_rate" not in body
    assert "notes_internal" not in body
    assert "charge_rate_override" not in body["students"][0]
    assert tutor_api.get(f"/api/v1/jobs/{mine.pk}/summary").status_code == 403
    # Through the job, the tutor now sees the student (E05 own scope).
    student_id = body["students"][0]["student"]
    assert result_ids(tutor_api.get("/api/v1/students")) == {student_id}


def test_summary_shows_expected_margin(org, admin_api):
    tutor = TutorProfileFactory(organisation=org, status="active")
    job = make_job(org, tutor=tutor, status="active", charge_rate=Money("42", "GBP"))
    body = admin_api.get(f"/api/v1/jobs/{job.pk}/summary").json()
    assert body["per_lesson"] == {
        "charge": gbp("42.00"),
        "pay": gbp("25.00"),
        "margin": gbp("17.00"),
        "margin_percent": "40.5",
    }
    assert body["trace"][0] == "job rate £42.00/h"
    coordinator, _m = api_as(org, "coordinator")
    limited = coordinator.get(f"/api/v1/jobs/{job.pk}/summary").json()
    assert limited["per_lesson"] == {"charge": gbp("42.00")}


def test_bill_to_client_is_charged(org, tenant):
    school = ClientFactory(organisation=org, type="organisation", display_name="Leeds Academy")
    job = make_job(org, bill_to=school)
    context = selectors.rate_context(job)
    assert context.attendees[0].client_id == str(school.pk)


# --- hours cap (FR-07-5) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scheduled", "extra", "block", "level"),
    [
        ("10", "2", True, "ok"),
        ("15", "1", True, "warning"),
        ("19", "2", True, "blocked"),
        ("19", "2", False, "warning"),
    ],
)
def test_hours_cap(org, tenant, monkeypatch, scheduled, extra, block, level):
    from tutortrack.tenancy.settings_service import update_settings

    if not block:
        update_settings("jobs", {"jobs.block_at_hours_cap": False})

    class Scheduled(lessons._NoLessons):
        def hours_scheduled(self, job, start, end):
            return Decimal(scheduled)

    monkeypatch.setattr(lessons, "_provider", Scheduled())
    job = make_job(org, hours_cap=Decimal("20"), hours_cap_period="month")
    check = services.check_hours(job, extra_hours=Decimal(extra), on=date(2026, 11, 15))
    assert check.level == level
    assert (check.period_start, check.period_end) == (date(2026, 11, 1), date(2026, 11, 30))
    services.notify_hours(job, check)
    services.notify_hours(job, check)
    sent = OutboxEvent.objects.filter(event_type="job.hours_cap_reached").count()
    assert sent == (0 if level == "ok" else 1)


# --- quick setup and duplicate (FR-07-2) --------------------------------------------------------


def test_quick_setup_with_and_without_tutor(org, admin_api, family):
    _client, student = family
    service = ServiceFactory(organisation=org)
    tutor = TutorProfileFactory(organisation=org, status="active")
    response = admin_api.post(
        "/api/v1/jobs/quick-setup",
        {
            "student": str(student.pk),
            "service": str(service.pk),
            "tutor": str(tutor.pk),
            "charge_rate": gbp("40.00"),
            "schedule": [{"weekday": 2, "time": "17:00", "duration_minutes": 45}],
            "start_date": "2026-11-04",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "active"
    assert body["default_schedule"] == [{"weekday": 2, "time": "17:00", "duration_minutes": 45}]
    assert body["tutors"][0]["tutor"] == str(tutor.pk)
    seeking = admin_api.post(
        "/api/v1/jobs/quick-setup",
        {"student": str(student.pk), "service": str(service.pk)},
        format="json",
    )
    assert seeking.json()["status"] == "seeking_tutor"
    bad = admin_api.post(
        "/api/v1/jobs/quick-setup",
        {
            "student": str(student.pk),
            "service": str(service.pk),
            "schedule": [{"weekday": 9, "time": "25:00"}],
        },
        format="json",
    )
    assert bad.status_code == 400


def test_duplicate_job_for_new_year(org, admin_api):
    tutor = TutorProfileFactory(organisation=org, status="active")
    job = make_job(org, tutor=tutor, status="active", charge_rate=Money("42", "GBP"))
    response = admin_api.post(
        f"/api/v1/jobs/{job.pk}/duplicate", {"start_date": "2027-09-01"}, format="json"
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["reference"] != job.reference
    assert (body["status"], body["start_date"], body["charge_rate"]["amount"]) == (
        "draft",
        "2027-09-01",
        "42.0000",
    )
    assert body["tutors"][0]["status"] == "offered"


def test_list_filters(org, admin_api):
    tutor = TutorProfileFactory(organisation=org, status="active")
    active = make_job(org, tutor=tutor, status="active")
    seeking = make_job(org, status="seeking_tutor")
    assert result_ids(admin_api.get("/api/v1/jobs?status=seeking_tutor")) == {str(seeking.pk)}
    assert result_ids(admin_api.get(f"/api/v1/jobs?tutor={tutor.pk}")) == {str(active.pk)}
    assert result_ids(admin_api.get(f"/api/v1/jobs?q={active.reference}")) == {str(active.pk)}


class TestJobIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/jobs"

    def make_object(self, organisation):
        return make_job(organisation)


def test_job_model_str(org, tenant):
    job = make_job(org)
    assert str(job).startswith("JOB-")
    assert Job.objects.count() == 1
