"""E19-T08: client shortlist sharing (FR-19-5): signed expiring links, minimal tutor cards,
the family's choice feeding the offer flow, and permissions."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.matching import services, sharing
from tutortrack.matching.models import OfferBatch, ShortlistShare
from tutortrack.people.models import TutorQualification
from tutortrack.people.tests.factories import ContactFactory
from tutortrack.tenancy import settings_service

from .test_matching import api_as, make_job, make_tutor, maths  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


@pytest.fixture
def shortlisted(org, maths):  # noqa: F811
    subject, level, _service = maths
    job = make_job(org, maths)
    contact = ContactFactory(
        organisation=org, client=job.client, first_name="Priya", email="priya@example.com"
    )
    with tenant_context(org):
        job.client.primary_contact = contact
        job.client.save(update_fields=["primary_contact"])
    first = make_tutor(
        org, subject, level=level, first_name="Nia", last_name="Adeyemi",
        phone="+44 7700 900123", headline="Maths specialist", bio_public="Patient and clear.",
        years_experience=6,
    )  # fmt: skip
    second = make_tutor(org, subject, level=level, first_name="Sam", last_name="Okafor")
    with tenant_context(org):
        TutorQualification.objects.create(tutor=first, title="BSc Mathematics", year=2015)
        services.shortlist_add(job, first)
        services.shortlist_add(job, second)
    return {"job": job, "contact": contact, "tutors": [first, second]}


def share(org, shortlisted, capture, **kwargs):
    with tenant_context(org), capture(execute=True):
        return sharing.share(shortlisted["job"], **kwargs)


def test_sharing_sends_the_family_a_signed_link(
    org, shortlisted, django_capture_on_commit_callbacks
):
    record, _token = share(org, shortlisted, django_capture_on_commit_callbacks, message="Hello")
    with tenant_context(org):
        assert record.tutors == [str(t.pk) for t in shortlisted["tutors"]] or set(
            record.tutors
        ) == {str(t.pk) for t in shortlisted["tutors"]}
        assert record.contact_id == shortlisted["contact"].pk
        message = Message.objects.get(type_key="shortlist_shared")
        assert "/shortlists/" in message.body
        assert OutboxEvent.objects.filter(event_type="shortlist.shared").count() == 1
    assert record.expires_at > now() + timedelta(days=13)


def test_public_page_shows_minimal_tutor_cards(
    org, shortlisted, django_capture_on_commit_callbacks
):
    _record, token = share(org, shortlisted, django_capture_on_commit_callbacks)
    body = client_for(org).get(f"/api/v1/public/shortlists/{token}").json()
    assert body["status"] == "active"
    assert body["job"]["students"] == ["Arjun"]
    nia = next(t for t in body["tutors"] if t["name"] == "Nia A.")
    assert nia["headline"] == "Maths specialist"
    assert nia["qualifications"][0]["title"] == "BSc Mathematics"
    assert nia["years_experience"] == 6
    dumped = json.dumps(body)
    for secret in ("Adeyemi", "Okafor", "Patel", "7700", "@example.com", "Downing", "score"):
        assert secret not in dumped, secret
    with tenant_context(org):
        assert ShortlistShare.objects.get().viewed_at is not None


def test_choosing_a_tutor_starts_an_offer_and_tells_staff(
    org, shortlisted, django_capture_on_commit_callbacks
):
    from tutortrack.identity.tests.factories import MembershipFactory

    MembershipFactory(organisation=org, role="coordinator")
    _record, token = share(org, shortlisted, django_capture_on_commit_callbacks)
    chosen = shortlisted["tutors"][1]
    public = client_for(org)
    with django_capture_on_commit_callbacks(execute=True):
        response = public.post(
            f"/api/v1/public/shortlists/{token}",
            {"tutor": str(chosen.pk), "note": "Tuesdays please"},
            format="json",
        )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "chosen"
    assert response.json()["chosen_tutor"] == str(chosen.pk)
    with tenant_context(org):
        record = ShortlistShare.objects.get()
        assert (record.chosen_tutor_id, record.client_note) == (chosen.pk, "Tuesdays please")
        batch = OfferBatch.objects.get(job=shortlisted["job"])
        assert record.offer_batch_id == batch.pk
        assert list(batch.offers.values_list("tutor_id", flat=True)) == [chosen.pk]
        assert Message.objects.filter(type_key="staff_shortlist_choice").exists()
        event = OutboxEvent.objects.get(event_type="shortlist.tutor_chosen")
        assert event.payload["data"]["offer_batch_id"] == str(batch.pk)
    again = public.post(
        f"/api/v1/public/shortlists/{token}", {"tutor": str(chosen.pk)}, format="json"
    )
    assert again.status_code == 422
    assert again.json()["code"] == "chosen"


def test_choice_without_automatic_offer(org, shortlisted, django_capture_on_commit_callbacks):
    with tenant_context(org):
        settings_service.update_settings("matching", {"matching.share_choice_starts_offer": False})
    _record, token = share(org, shortlisted, django_capture_on_commit_callbacks)
    with tenant_context(org):
        sharing.choose(token, tutor_id=str(shortlisted["tutors"][0].pk))
        assert not OfferBatch.objects.exists()
        assert ShortlistShare.objects.get().status == "chosen"


def test_only_shared_tutors_can_be_chosen(
    org,
    shortlisted,
    maths,  # noqa: F811
    django_capture_on_commit_callbacks,
):
    subject, level, _service = maths
    _record, token = share(
        org, shortlisted, django_capture_on_commit_callbacks, tutors=[shortlisted["tutors"][0]]
    )
    other = make_tutor(org, subject, level=level)
    response = client_for(org).post(
        f"/api/v1/public/shortlists/{token}", {"tutor": str(other.pk)}, format="json"
    )
    assert response.status_code == 422
    assert len(client_for(org).get(f"/api/v1/public/shortlists/{token}").json()["tutors"]) == 1


def test_expired_revoked_and_foreign_links(
    org, other_org, shortlisted, django_capture_on_commit_callbacks
):
    record, token = share(org, shortlisted, django_capture_on_commit_callbacks)
    public = client_for(org)
    assert client_for(other_org).get(f"/api/v1/public/shortlists/{token}").status_code == 404
    assert public.get("/api/v1/public/shortlists/garbage").status_code == 404
    with tenant_context(org):
        ShortlistShare.objects.filter(pk=record.pk).update(expires_at=now() - timedelta(hours=1))
    assert public.get(f"/api/v1/public/shortlists/{token}").json()["status"] == "expired"
    expired = public.post(
        f"/api/v1/public/shortlists/{token}",
        {"tutor": str(shortlisted["tutors"][0].pk)},
        format="json",
    )
    assert expired.status_code == 422
    with tenant_context(org):
        ShortlistShare.objects.filter(pk=record.pk).update(expires_at=now() + timedelta(days=1))
        sharing.revoke(record)
    assert public.get(f"/api/v1/public/shortlists/{token}").status_code == 404


def test_staff_api_shares_lists_and_revokes(org, shortlisted, django_capture_on_commit_callbacks):
    coordinator = api_as(org, "coordinator")
    job = shortlisted["job"]
    with django_capture_on_commit_callbacks(execute=True):
        created = coordinator.post(
            "/api/v1/shortlist-shares",
            {"job": str(job.pk), "tutors": [str(shortlisted["tutors"][0].pk)], "days": 3},
            format="json",
        )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["state"] == "active"
    assert "/shortlists/" in body["link"]
    listed = coordinator.get("/api/v1/shortlist-shares", {"job": str(job.pk)}).json()["results"]
    assert [r["id"] for r in listed] == [body["id"]]
    revoked = coordinator.post(f"/api/v1/shortlist-shares/{body['id']}/revoke").json()
    assert (revoked["state"], revoked["link"]) == ("revoked", "")
    nothing = coordinator.post(
        "/api/v1/shortlist-shares", {"job": str(make_job(org, maths_of(job)).pk)}, format="json"
    )
    assert nothing.status_code == 422  # nobody shortlisted
    tutor = api_as(org, "tutor")
    assert (
        tutor.post("/api/v1/shortlist-shares", {"job": str(job.pk)}, format="json").status_code
        == 403
    )


def maths_of(job):
    return (job.subject, job.level, job.service)


class TestShortlistShareIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/shortlist-shares"

    def make_object(self, organisation):
        from tutortrack.catalogue.tests.factories import (
            LevelFactory,
            ServiceFactory,
            SubjectFactory,
        )

        with tenant_context(organisation):
            subject = SubjectFactory(organisation=organisation, name="Maths")
            level = LevelFactory(organisation=organisation, subject=subject, name="GCSE")
            service = ServiceFactory(organisation=organisation, subject=subject, level=level)
        job = make_job(organisation, (subject, level, service))
        tutor = make_tutor(organisation, subject, level=level)
        with tenant_context(organisation):
            services.shortlist_add(job, tutor)
            record, _token = sharing.share(job)
        return record


def test_shares_are_in_dsar_exports_and_erased(
    org, shortlisted, django_capture_on_commit_callbacks
):
    from tutortrack.matching import privacy
    from tutortrack.privacy import registry

    _record, token = share(org, shortlisted, django_capture_on_commit_callbacks)
    with tenant_context(org):
        settings_service.update_settings("matching", {"matching.share_choice_starts_offer": False})
        sharing.choose(token, tutor_id=str(shortlisted["tutors"][0].pk), note="Call Priya")
        person = registry.resolve("people.client", str(shortlisted["job"].client_id))
        [section] = privacy.export(person)
        assert section.records[0]["note"] == "Call Priya"
        ctx = registry.ErasureContext(labels={}, financial_cutoff=now())
        ctx.prepare_scrub(person, "[erased]")
        privacy.erase(person, ctx)
        assert ShortlistShare.objects.get().client_note == ""
