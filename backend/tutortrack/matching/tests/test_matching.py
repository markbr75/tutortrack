"""E19-T01..T06, T09: matching search, shortlists, offers, job board, cover, analytics."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tutortrack.catalogue.tests.factories import LevelFactory, ServiceFactory, SubjectFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.jobs import services as jobs
from tutortrack.jobs.models import JobTutor
from tutortrack.matching import engine, selectors, services
from tutortrack.matching.models import (
    CoverRequest,
    JobOffer,
    JobPosting,
    JobPostingApplication,
    OfferBatch,
    Shortlist,
)
from tutortrack.people.models import Address, TutorSubject
from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory
from tutortrack.recruitment.models import ComplianceRecord, RequirementType
from tutortrack.scheduling import services as scheduling
from tutortrack.scheduling.models import (
    AvailabilityTemplate,
    AvailabilityWindow,
    LessonSeries,
)

pytestmark = pytest.mark.django_db
LONDON = (Decimal("51.501000"), Decimal("-0.141900"))  # Westminster
NEAR = (Decimal("51.507400"), Decimal("-0.127800"))  # ~1.2 km away
FAR = (Decimal("52.205300"), Decimal("0.121800"))  # Cambridge, ~80 km


@pytest.fixture
def maths(org):
    with tenant_context(org):
        subject = SubjectFactory(organisation=org, name="Maths")
        level = LevelFactory(organisation=org, subject=subject, name="GCSE")
        service = ServiceFactory(organisation=org, subject=subject, level=level)
    return subject, level, service


def make_tutor(
    org, subject, *, level=None, approved=True, status="active", point=NEAR, radius=None,
    online=True, in_person=True, member=False, **fields,
):  # fmt: skip
    with tenant_context(org):
        address = (
            Address.objects.create(lat=point[0], lng=point[1], postcode="SW1A 2AA")
            if point
            else None
        )
        membership = MembershipFactory(organisation=org, role="tutor") if member else None
        tutor = TutorProfileFactory(
            organisation=org, status=status, address=address, travel_radius_km=radius,
            delivers_online=online, delivers_in_person=in_person, membership=membership, **fields,
        )  # fmt: skip
        TutorSubject.objects.create(
            tutor=tutor,
            subject=subject.name,
            catalogue_subject=subject,
            catalogue_level=level,
            approved=approved,
            competency="approved" if approved else "claimed",
        )
    return tutor


def available(org, tutor, weekday, start=time(9), end=time(21)):
    with tenant_context(org):
        template = AvailabilityTemplate.objects.create(
            tutor=tutor, effective_from=date(2020, 1, 1), timezone=org.timezone
        )
        AvailabilityWindow.objects.create(
            template=template, weekday=weekday, start_time=start, end_time=end
        )


def make_job(org, maths, *, online=False, schedule=None, student=None, **fields):
    subject, level, service = maths
    with tenant_context(org):
        client = ClientFactory(organisation=org)
        if student is None:
            address = Address.objects.create(
                lat=LONDON[0], lng=LONDON[1], postcode="SW1A 1AA", line1="10 Downing Street"
            )
            student = StudentFactory(
                organisation=org, client=client, first_name="Arjun", last_name="Patel",
                lesson_address=address,
            )  # fmt: skip
        return jobs.create_job(
            client=student.client,
            service=service,
            subject=subject,
            level=level,
            students=[{"student": student}],
            status="seeking_tutor",
            online=online,
            default_schedule=schedule or [{"weekday": 0, "time": "16:00", "duration_minutes": 60}],
            start_date=now().date() + timedelta(days=1),
            **fields,
        )


def search(org, job, **kwargs):
    with tenant_context(org):
        return engine.search(engine.criteria_for_job(job), **kwargs)


def ids(matches):
    return [m.tutor.pk for m in matches]


def api_as(org, role):
    membership = MembershipFactory(organisation=org, role=role)
    return client_for(org, membership.user)


# --- FR-19-1 hard filters -----------------------------------------------------------------------


def test_only_approved_compliant_tutors_match_unless_include_restricted(org, maths):
    """AC: no approved subject or an expired check means never in the results, even with
    no filters, unless a permitted user includes restricted tutors."""
    subject, level, _service = maths
    good = make_tutor(org, subject, level=level)
    unapproved = make_tutor(org, subject, approved=False)
    restricted = make_tutor(org, subject, status="restricted")
    lapsed = make_tutor(org, subject)
    with tenant_context(org):
        dbs = RequirementType.objects.create(key="dbs", name="DBS", blocking=True, mandatory=True)
        ComplianceRecord.objects.create(
            tutor=lapsed, requirement=dbs, status="verified",
            expiry_date=now().date() - timedelta(days=1),
        )  # fmt: skip
        found = engine.search(engine.Criteria())
    assert ids(found) == [good.pk]
    job = make_job(org, maths)
    assert ids(search(org, job)) == [good.pk]
    everyone = search(org, job, include_restricted=True)
    assert set(ids(everyone)) == {good.pk, unapproved.pk, restricted.pk, lapsed.pk}
    flagged = {m.tutor.pk: m for m in everyone}
    assert not flagged[good.pk].restricted
    assert flagged[unapproved.pk].restricted
    assert "Subject not approved" in flagged[unapproved.pk].reasons
    assert flagged[lapsed.pk].reasons == ["A required check has lapsed"]


def test_include_restricted_needs_permission(org, maths):
    job = make_job(org, maths)
    body = {"job": str(job.pk), "include_restricted": True}
    coordinator = api_as(org, "coordinator")
    assert coordinator.post("/api/v1/matching/search", body, format="json").status_code == 403
    admin = api_as(org, "admin")
    response = admin.post("/api/v1/matching/search", body, format="json")
    assert response.status_code == 200, response.content
    assert (
        coordinator.post("/api/v1/matching/search", {"job": str(job.pk)}, format="json").status_code
        == 200
    )


def test_mode_radius_exclusions_branch_and_current_tutors(org, maths):
    subject, level, _service = maths
    near = make_tutor(org, subject, level=level)
    far = make_tutor(org, subject, point=FAR, radius=20)
    far_but_online = make_tutor(org, subject, point=FAR, radius=20)
    online_only = make_tutor(org, subject, in_person=False)
    excluded = make_tutor(org, subject)
    on_job = make_tutor(org, subject)
    with tenant_context(org):
        from tutortrack.tenancy.models import Branch

        other_branch = Branch.objects.create(name="North", timezone=org.timezone)
    wrong_branch = make_tutor(org, subject)
    wrong_branch.branches.add(other_branch)
    job = make_job(org, maths)
    with tenant_context(org):
        job.students.first().student.excluded_tutors.add(excluded)
        jobs.add_tutor(job, tutor=on_job, offer=True)
    in_person = ids(search(org, job))
    assert in_person == [near.pk]
    online_job = make_job(org, maths, online=True)
    found = set(ids(search(org, online_job)))
    assert {near.pk, far.pk, far_but_online.pk, online_only.pk, excluded.pk} <= found
    assert wrong_branch.pk not in found
    with tenant_context(org):
        either = engine.criteria_for_job(job)
        either.mode = "either"
        either.exclude = set()
        flexible = set(ids(engine.search(either)))
    assert far_but_online.pk in flexible
    assert online_only.pk in flexible


def test_ad_hoc_criteria_from_input(org, maths, monkeypatch):
    subject, level, _service = maths
    tutor = make_tutor(org, subject, level=level, languages=["French"])
    make_tutor(org, subject, level=level, languages=["German"], pay_rate_amount=Decimal("40"))

    class Geo:
        def geocode(self, address, country=""):
            from tutortrack.core.geo import GeoPoint

            return GeoPoint(LONDON[0], LONDON[1])

    monkeypatch.setattr("tutortrack.core.geo.geocoder", lambda: Geo())
    with tenant_context(org):
        c = engine.criteria_from_input(
            {"subject": subject.pk, "level": level.pk, "mode": "in_person",
             "postcode": "SW1A 1AA", "languages": ["French"]}
        )  # fmt: skip
        assert (c.lat, c.area, c.subject_name) == (LONDON[0], "SW1A", "Maths")
        assert ids(engine.search(c)) == [tutor.pk]
        c.languages = []
        c.max_pay_rate = Decimal("30")
        assert ids(engine.search(c)) == [tutor.pk]


# --- FR-19-1 scoring and availability (T01/T02) ------------------------------------------------


def test_scoring_breakdown_ranks_free_tutor_first(org, maths):
    subject, level, _service = maths
    free = make_tutor(org, subject, level=level, years_experience=8, max_weekly_hours=20)
    busy = make_tutor(org, subject, level=level, years_experience=8, max_weekly_hours=20)
    unknown = make_tutor(org, subject, level=level, point=None)
    available(org, free, weekday=0)
    available(org, busy, weekday=2)  # wrong day
    job = make_job(org, maths)
    found = search(org, job)
    assert ids(found)[0] == free.pk
    rows = {m.tutor.pk: m for m in found}
    assert set(rows[free.pk].breakdown) == set(engine.FACTORS)
    assert rows[free.pk].breakdown["availability"]["score"] == 1.0
    assert rows[free.pk].slot_fit == [1.0]
    assert rows[busy.pk].breakdown["availability"]["score"] == 0.0
    assert rows[unknown.pk].breakdown["availability"]["known"] is False
    assert rows[unknown.pk].breakdown["distance"]["known"] is False
    assert rows[free.pk].distance_km is not None
    assert rows[free.pk].distance_km < 2
    assert rows[free.pk].breakdown["fairness"]["score"] == 1.0  # never assigned


def test_lesson_clash_lowers_availability(org, maths):
    subject, level, _service = maths
    tutor = make_tutor(org, subject, level=level)
    available(org, tutor, weekday=0)
    job = make_job(org, maths)
    with tenant_context(org):
        c = engine.criteria_for_job(job)
        start_day = c.start_date + timedelta(days=(0 - c.start_date.weekday()) % 7)
        start = datetime.combine(start_day, time(16), tzinfo=ZoneInfo(org.timezone))
        other = make_job(org, maths)
        scheduling.create_lesson(
            job=other, start=start, end=start + timedelta(hours=1), tutors=[{"tutor": tutor}]
        )
        match = engine.search(c)[0]
    assert match.slot_fit == [0.75]  # one of the next four Mondays is taken


def test_weights_setting_changes_score(org, maths):
    subject, level, _service = maths
    make_tutor(org, subject, level=level)
    api = api_as(org, "admin")
    response = api.get("/api/v1/matching/settings")
    assert response.json()["weights"]["availability"] == 30
    bad = api.put("/api/v1/matching/settings", {"weights": {"luck": 5}}, format="json")
    assert bad.status_code == 422 or bad.status_code == 400
    weights = dict.fromkeys(engine.FACTORS, 0) | {"fairness": 100}
    response = api.put("/api/v1/matching/settings", {"weights": weights}, format="json")
    assert response.status_code == 200, response.content
    job = make_job(org, maths)
    assert search(org, job)[0].score == Decimal("100.0")


def test_search_api_records_query_and_shortlist(org, maths):
    subject, level, _service = maths
    tutor = make_tutor(org, subject, level=level)
    job = make_job(org, maths)
    api = api_as(org, "coordinator")
    response = api.post("/api/v1/matching/search", {"job": str(job.pk)}, format="json")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["results"][0]["tutor"]["id"] == str(tutor.pk)
    assert body["origin"] == {"lat": 51.501, "lng": -0.1419}
    assert body["results"][0]["point"] == {"lat": 51.51, "lng": -0.13}
    created = api.post(
        "/api/v1/shortlists", {"job": str(job.pk), "tutor": str(tutor.pk)}, format="json"
    )
    assert created.status_code == 201, created.content
    assert created.json()["score"] is not None
    listed = api.get(f"/api/v1/shortlists?job={job.pk}").json()
    assert [row["tutor"] for row in listed] == [str(tutor.pk)]
    again = api.post("/api/v1/matching/search", {"job": str(job.pk)}, format="json").json()
    assert again["results"][0]["shortlisted"] is True
    assert api.delete(f"/api/v1/shortlists/{listed[0]['id']}").status_code == 204


# --- FR-19-2 offers (T03/T04) -------------------------------------------------------------------


def _events(org, kind):
    with tenant_context(org):
        return list(OutboxEvent.objects.filter(event_type=kind).order_by("occurred_at"))


def test_offer_brief_is_anonymised_and_acceptance_assigns_tutor(org, maths):
    subject, level, _service = maths
    first = make_tutor(org, subject, level=level, member=True)
    second = make_tutor(org, subject, level=level, member=True)
    job = make_job(org, maths, notes_for_tutor="Bring past papers")
    with tenant_context(org):
        batch = services.start_offers(job, [first, second], mode="simultaneous")
        assert batch.brief["students"] == ["Arjun P."]
        assert batch.brief["area"] == "SW1A"
        assert "Downing" not in str(batch.brief)
        assert "Patel" not in str(batch.brief)
        assert batch.brief["notes"] == "Bring past papers"
        offers = list(batch.offers.order_by("cascade_order"))
        sent = services.send_offers(
            str(batch.pk), [str(o.pk) for o in offers], now() + timedelta(hours=24)
        )
        assert len(sent) == 2
    assert len(_events(org, "job_offer.batch_started")) == 1
    assert len(_events(org, "job_offer.sent")) == 2
    tutor_api = client_for(org, second.membership.user)
    inbox = tutor_api.get("/api/v1/me/job-offers").json()
    assert [row["status"] for row in inbox] == ["sent"]
    response = tutor_api.post(f"/api/v1/me/job-offers/{offers[1].pk}/accept", {}, format="json")
    assert response.status_code == 200, response.content
    with tenant_context(org):
        state = services.offer_state(str(batch.pk), [str(o.pk) for o in offers])
        assert state["accepted"] == [str(offers[1].pk)]
        assert services.fill(str(batch.pk), str(offers[1].pk)) == "filled"
        job.refresh_from_db()
        assert job.status == "active"
        assert JobTutor.objects.get(job=job, status="active").tutor == second
        assert LessonSeries.objects.filter(job=job).count() == 1
        offers[0].refresh_from_db()
        assert offers[0].status == JobOffer.Status.WITHDRAWN
        batch.refresh_from_db()
        assert batch.status == OfferBatch.Status.FILLED
        assert services.fill(str(batch.pk), str(offers[1].pk)) == "closed"  # idempotent


def test_decline_with_reason_and_expiry(org, maths):
    subject, level, _service = maths
    tutor = make_tutor(org, subject, level=level, member=True)
    job = make_job(org, maths)
    with tenant_context(org):
        batch = services.start_offers(job, [tutor])
        offer = batch.offers.get()
        services.send_offers(str(batch.pk), [str(offer.pk)], now() + timedelta(hours=1))
    api = client_for(org, tutor.membership.user)
    response = api.post(
        f"/api/v1/me/job-offers/{offer.pk}/decline", {"reason": "Too far"}, format="json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["decline_reason"] == "Too far"
    assert (
        api.post(f"/api/v1/me/job-offers/{offer.pk}/accept", {}, format="json").status_code == 422
    )
    assert _events(org, "job_offer.declined")[0].payload["data"]["reason"] == "Too far"
    with tenant_context(org):
        assert services.exhaust(str(batch.pk))
        batch.refresh_from_db()
        assert batch.status == "exhausted"


def test_start_offers_rules(org, maths):
    subject, level, _service = maths
    tutor = make_tutor(org, subject, level=level)
    restricted = make_tutor(org, subject, level=level, status="restricted")
    job = make_job(org, maths)
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation):
            services.start_offers(job, [restricted])
        services.start_offers(job, [tutor])
        with pytest.raises(BusinessRuleViolation):
            services.start_offers(job, [tutor])  # offers still out
    api = api_as(org, "coordinator")
    batches = api.get(f"/api/v1/job-offer-batches?job={job.pk}").json()["results"]
    assert len(batches) == 1
    assert batches[0]["offers"][0]["status"] == "queued"
    cancelled = api.post(f"/api/v1/job-offer-batches/{batches[0]['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.content
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["offers"][0]["status"] == "withdrawn"


def test_admin_confirmation(org, maths):
    subject, level, _service = maths
    tutor = make_tutor(org, subject, level=level)
    job = make_job(org, maths)
    with tenant_context(org):
        batch = services.start_offers(job, [tutor], admin_confirms=True)
        offer = batch.offers.get()
        services.send_offers(str(batch.pk), [str(offer.pk)], now() + timedelta(hours=1))
        services.respond(offer, accept=True)
        assert services.request_confirmation(str(batch.pk), str(offer.pk))
    api = api_as(org, "coordinator")
    response = api.post(
        f"/api/v1/job-offer-batches/{batch.pk}/decide", {"approve": True}, format="json"
    )
    assert response.status_code == 200, response.content
    with tenant_context(org):
        assert services.offer_state(str(batch.pk), [str(offer.pk)])["confirmed"] == [str(offer.pk)]
        assert services.fill(str(batch.pk), str(offer.pk)) == "filled"


# --- FR-19-3 job board (T05) --------------------------------------------------------------------


def test_job_board_publish_apply_select(org, maths):
    subject, level, _service = maths
    good = make_tutor(org, subject, level=level, member=True)
    other = make_tutor(org, subject, level=level, member=True)
    unapproved = make_tutor(org, subject, approved=False, member=True)
    available(org, good, weekday=0)
    job = make_job(org, maths)
    staff = api_as(org, "coordinator")
    response = staff.post("/api/v1/job-postings", {"job": str(job.pk)}, format="json")
    assert response.status_code == 201, response.content
    posting_id = response.json()["id"]
    assert response.json()["title"] == "Maths GCSE"
    assert response.json()["eligible_count"] == 2
    assert client_for(org, unapproved.membership.user).get("/api/v1/me/job-postings").json() == []
    good_api = client_for(org, good.membership.user)
    listed = good_api.get("/api/v1/me/job-postings").json()
    assert [p["id"] for p in listed] == [posting_id]
    assert listed[0]["applied"] is None
    applied = good_api.post(
        f"/api/v1/me/job-postings/{posting_id}/apply",
        {"message": "I'd love to", "proposed_availability": [{"weekday": 0, "time": "16:00"}]},
        format="json",
    )
    assert applied.status_code == 201, applied.content
    assert applied.json()["applied"] == "applied"
    client_for(org, other.membership.user).post(
        f"/api/v1/me/job-postings/{posting_id}/apply", {}, format="json"
    )
    detail = staff.get(f"/api/v1/job-postings/{posting_id}").json()
    assert [a["tutor"] for a in detail["applications"]] == [str(good.pk), str(other.pk)]
    chosen = detail["applications"][0]["id"]
    response = staff.post(f"/api/v1/job-postings/{posting_id}/applications/{chosen}/select")
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "filled"
    assert {a["status"] for a in response.json()["applications"]} == {"selected", "rejected"}
    with tenant_context(org):
        assert JobTutor.objects.get(job=job, status="active").tutor == good
    assert good_api.get("/api/v1/me/job-postings").json() == []


# --- FR-19-4 cover (T06) ------------------------------------------------------------------------


def _lesson_for(org, job, tutor, days=3):
    with tenant_context(org):
        start = (now() + timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
        return scheduling.create_lesson(
            job=job, start=start, end=start + timedelta(hours=1), tutors=[{"tutor": tutor}]
        ).lesson


def test_cover_notifies_free_tutors_and_acceptance_moves_lessons(org, maths):
    subject, level, _service = maths
    away = make_tutor(org, subject, level=level, member=True)
    cover = make_tutor(org, subject, level=level, member=True)
    not_free = make_tutor(org, subject, level=level, member=True)
    job = make_job(org, maths)
    with tenant_context(org):
        jobs.add_tutor(job, tutor=away)
    lesson = _lesson_for(org, job, away)
    with tenant_context(org):
        local = lesson.start.astimezone(ZoneInfo(org.timezone))
    available(org, cover, weekday=local.weekday(), start=time(0), end=time(23, 59))
    available(org, not_free, weekday=(local.weekday() + 1) % 7)
    api = client_for(org, away.membership.user)
    response = api.post(
        "/api/v1/me/cover-requests", {"lessons": [str(lesson.pk)], "reason": "Ill"}, format="json"
    )
    assert response.status_code == 201, response.content
    request_id = response.json()["id"]
    with tenant_context(org):
        assert services.notify_cover(request_id) == 1
        request = CoverRequest.objects.get(pk=request_id)
        assert request.notified == [str(cover.pk)]
    refused = client_for(org, not_free.membership.user).post(
        f"/api/v1/me/cover-requests/{request_id}/accept"
    )
    assert refused.status_code == 404
    cover_api = client_for(org, cover.membership.user)
    assert [r["id"] for r in cover_api.get("/api/v1/me/cover-requests").json()] == [request_id]
    accepted = cover_api.post(f"/api/v1/me/cover-requests/{request_id}/accept")
    assert accepted.status_code == 200, accepted.content
    assert accepted.json()["status"] == "filled"
    with tenant_context(org):
        assert [t.tutor for t in lesson.tutors.all()] == [cover]
        assert JobTutor.objects.get(job=job, status="active").tutor == away  # only these dates
    assert len(_events(org, "cover_request.filled")) == 1


def test_cover_rules_and_unfilled(org, maths):
    subject, level, _service = maths
    away = make_tutor(org, subject, level=level)
    job = make_job(org, maths)
    lesson = _lesson_for(org, job, away)
    with tenant_context(org):
        request = services.create_cover([lesson], reason="Holiday")
        with pytest.raises(BusinessRuleViolation):
            services.create_cover([lesson])  # already open
        assert services.notify_cover(str(request.pk)) == 0
        assert services.mark_unfilled(str(request.pk))
        request.refresh_from_db()
        assert request.status == "unfilled"
        soon = _lesson_for(org, job, away, days=0)
    with tenant_context(org), pytest.raises(BusinessRuleViolation):
        services.create_cover([soon])  # within the cut-off (or already started)
    staff = api_as(org, "coordinator")
    listed = staff.get("/api/v1/cover-requests?status=unfilled").json()["results"]
    assert [r["id"] for r in listed] == [str(request.pk)]


# --- FR-19-6 analytics (T09) --------------------------------------------------------------------


def test_analytics(org, maths):
    subject, level, _service = maths
    tutor = make_tutor(org, subject, level=level)
    make_job(org, maths)
    filled = make_job(org, maths)
    with tenant_context(org):
        batch = services.start_offers(filled, [tutor])
        offer = batch.offers.get()
        services.send_offers(str(batch.pk), [str(offer.pk)], now() + timedelta(hours=1))
        services.respond(offer, accept=True)
        services.fill(str(batch.pk), str(offer.pk))
        services.run_search(engine.Criteria(subject_id=str(LevelFactory(
            organisation=org, subject=SubjectFactory(organisation=org, name="Latin")
        ).subject_id), subject_name="Latin"))  # fmt: skip
        data = selectors.analytics()
    assert data["time_to_match"]["jobs"] == 1
    assert data["offers"][0]["accepted"] == 1
    assert data["offers"][0]["acceptance_rate"] == 1.0
    assert data["unmatched"] == [{"subject": "Maths", "area": "SW1A", "jobs": 1, "oldest_days": 0}]
    assert data["empty_searches"][0]["searches"] == 1
    response = api_as(org, "admin").get("/api/v1/matching/analytics?days=30")
    assert response.status_code == 200, response.content
    assert response.json()["days"] == 30


# --- tenant isolation ---------------------------------------------------------------------------


def _job_in(org):
    with tenant_context(org):
        subject = SubjectFactory(organisation=org)
        service = ServiceFactory(organisation=org, subject=subject)
        student = StudentFactory(organisation=org)
        return jobs.create_job(
            client=student.client, service=service, students=[{"student": student}],
            subject=subject, status="seeking_tutor",
        )  # fmt: skip


class TestShortlistIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/shortlists"

    def make_object(self, organisation):
        job = _job_in(organisation)
        with tenant_context(organisation):
            return Shortlist.objects.create(
                job=job, tutor=TutorProfileFactory(organisation=organisation)
            )


class TestOfferBatchIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/job-offer-batches"

    def make_object(self, organisation):
        job = _job_in(organisation)
        with tenant_context(organisation):
            return OfferBatch.objects.create(job=job, currency=job.currency)


class TestJobPostingIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/job-postings"

    def make_object(self, organisation):
        job = _job_in(organisation)
        with tenant_context(organisation):
            return JobPosting.objects.create(job=job, title="Maths", published_at=now())


class TestCoverRequestIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/cover-requests"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return CoverRequest.objects.create(
                original_tutor=TutorProfileFactory(organisation=organisation),
                deadline=now() + timedelta(days=1),
            )


def test_posting_application_unique(org, maths):
    subject, level, _service = maths
    tutor = make_tutor(org, subject, level=level)
    job = make_job(org, maths)
    with tenant_context(org):
        posting = services.publish_posting(job)
        services.apply_to_posting(posting, tutor, message="Hi")
        with pytest.raises(BusinessRuleViolation):
            services.apply_to_posting(posting, tutor)
        application = JobPostingApplication.objects.get()
        services.withdraw_application(application)
        services.apply_to_posting(posting, tutor, message="Again")
        application.refresh_from_db()
        assert application.status == "applied"
        assert application.message == "Again"
