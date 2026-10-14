"""E05-T12: the people map (geocoded students and tutors), geocoding providers and the
"geocode missing" action."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from unittest import mock

import pytest

from tutortrack.core import geo
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.models import Address
from tutortrack.people.tests.factories import (
    AddressFactory,
    ClientFactory,
    StudentFactory,
    TutorProfileFactory,
)

pytestmark = pytest.mark.django_db

URL = "/api/v1/people/map"


def placed(org, **kwargs):
    return AddressFactory(
        organisation=org, lat=Decimal("51.464123"), lng=Decimal("-0.163456"), **kwargs
    )


def test_map_lists_geocoded_students_and_tutors_rounded_without_addresses(org, admin_api):
    family = ClientFactory(organisation=org, billing_address=placed(org, postcode="SW11 1AA"))
    student = StudentFactory(
        organisation=org, client=family, subjects=[{"subject": "Maths", "level": "GCSE"}]
    )
    tutor = TutorProfileFactory(
        organisation=org, status="active", address=placed(org, postcode="SW4 7AA"),
        travel_radius_km=5,
    )  # fmt: skip
    StudentFactory(organisation=org)  # no address: counted as missing
    body = admin_api.get(URL).json()
    by_id = {p["id"]: p for p in body["points"]}
    assert by_id[str(student.pk)]["kind"] == "student"
    assert (by_id[str(student.pk)]["lat"], by_id[str(student.pk)]["lng"]) == (51.464, -0.163)
    assert by_id[str(student.pk)]["area"] == "SW11"
    assert by_id[str(student.pk)]["subjects"] == ["Maths"]
    assert by_id[str(tutor.pk)]["travel_radius_km"] == 5
    assert by_id[str(tutor.pk)]["area"] == "SW4"
    assert "High Street" not in json.dumps(body)  # never the street address
    assert body["missing"] == {"student": 1, "tutor": 0}


def test_lesson_address_wins_over_the_family_address(org, admin_api):
    family = ClientFactory(organisation=org, billing_address=placed(org, postcode="SW11 1AA"))
    lesson_place = AddressFactory(
        organisation=org, postcode="N1 9GU", lat=Decimal("51.53"), lng=Decimal("-0.12")
    )
    StudentFactory(organisation=org, client=family, lesson_address=lesson_place)
    [point] = admin_api.get(URL, {"kind": "student"}).json()["points"]
    assert point["area"] == "N1"


def test_map_filters_by_kind_status_and_subject(org, admin_api):
    family = ClientFactory(organisation=org, billing_address=placed(org))
    StudentFactory(organisation=org, client=family, status="active",
                   subjects=[{"subject": "Maths"}])  # fmt: skip
    StudentFactory(organisation=org, client=family, status="waiting",
                   subjects=[{"subject": "French"}])  # fmt: skip
    TutorProfileFactory(organisation=org, address=placed(org))
    assert {p["kind"] for p in admin_api.get(URL, {"kind": "tutor"}).json()["points"]} == {"tutor"}
    waiting = admin_api.get(URL, {"kind": "student", "status": "waiting"}).json()["points"]
    assert [p["subjects"] for p in waiting] == [["French"]]
    maths = admin_api.get(URL, {"subject": "maths"}).json()["points"]
    assert [p["subjects"] for p in maths] == [["Maths"]]


def test_map_respects_permissions(org):
    family = ClientFactory(organisation=org, billing_address=placed(org))
    StudentFactory(organisation=org, client=family)
    membership = MembershipFactory(organisation=org, role="tutor")
    mine = TutorProfileFactory(
        organisation=org, membership=membership, email=membership.user.email,
        address=placed(org),
    )  # fmt: skip
    TutorProfileFactory(organisation=org, address=placed(org))
    tutor_api = client_for(org, membership.user)
    response = tutor_api.get(URL)
    assert response.status_code == 200
    ids = {p["id"] for p in response.json()["points"]}
    assert str(mine.pk) in ids
    # A tutor sees no students that aren't on their jobs, and no other tutors.
    assert all(p["kind"] == "tutor" and p["id"] == str(mine.pk) for p in response.json()["points"])
    client_user = MembershipFactory(organisation=org, role="client").user
    assert client_for(org, client_user).get(URL).status_code == 403


class TestPeopleMapIsolation(TenantIsolationTestMixin):
    list_url = URL

    def make_object(self, organisation):
        family = ClientFactory(organisation=organisation, billing_address=placed(organisation))
        return StudentFactory(organisation=organisation, client=family)

    def detail_url(self, obj):
        return f"/api/v1/students/{obj.pk}"

    def test_list_only_returns_own_organisation(self, org, other_org):
        mine = self.make_object(org)
        theirs = self.make_object(other_org)
        from tutortrack.identity.tests.factories import UserFactory

        body = client_for(org, UserFactory(is_superuser=True)).get(self.list_url).json()
        ids = {p["id"] for p in body["points"]}
        assert str(mine.pk) in ids
        assert str(theirs.pk) not in ids


def test_geocode_missing_queues_the_people_the_map_cannot_place(
    org, admin_api, settings, django_capture_on_commit_callbacks
):
    settings.GEOCODER = "tutortrack.core.geo.FakeGeocoder"
    geo.geocoder.cache_clear()
    try:
        family = ClientFactory(
            organisation=org, billing_address=AddressFactory(organisation=org, postcode="E1 6AN")
        )
        StudentFactory(organisation=org, client=family)
        TutorProfileFactory(
            organisation=org, address=AddressFactory(organisation=org, postcode="N1 9GU")
        )
        TutorProfileFactory(organisation=org, address=placed(org))  # already placed
        with django_capture_on_commit_callbacks(execute=True):
            response = admin_api.post(URL + "/geocode", {}, format="json")
        assert response.json() == {"queued": 2}
        body = admin_api.get(URL).json()
        assert body["missing"] == {"student": 0, "tutor": 0}
        assert len(body["points"]) == 3
    finally:
        geo.geocoder.cache_clear()


def test_geocode_missing_needs_edit_permission(org):
    viewer = MembershipFactory(organisation=org, role="client").user
    assert client_for(org, viewer).post(URL + "/geocode", {}, format="json").status_code == 403


# --- providers ----------------------------------------------------------------------------------


def test_fake_geocoder_is_stable_and_offline():
    fake = geo.FakeGeocoder()
    first = fake.geocode("1 High Street, London, SW11 1AA", "GB")
    assert first == fake.geocode("1  high street, London, SW11 1AA", "gb")
    assert first != fake.geocode("2 High Street, London, SW11 1AA", "GB")
    assert Decimal("51.30") <= first.lat <= Decimal("51.70")
    assert Decimal("-0.50") <= first.lng <= Decimal("0.20")
    assert fake.geocode("   ") is None


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def test_mapbox_geocoder_goes_through_safe_urlopen(settings):
    settings.MAPBOX_ACCESS_TOKEN = "test-token"
    body = json.dumps({"features": [{"center": [-0.1634567, 51.4641239]}]}).encode()
    with mock.patch("tutortrack.core.net.safe_urlopen", return_value=_Response(body)) as opened:
        point = geo.MapboxGeocoder().geocode("1 High Street, London", "GB")
    url = opened.call_args.args[0]
    assert url.startswith("https://api.mapbox.com/geocoding/v5/mapbox.places/")
    assert "country=gb" in url
    assert point == geo.GeoPoint(Decimal("51.464124"), Decimal("-0.163457"))


def test_google_geocoder_goes_through_safe_urlopen(settings):
    settings.GOOGLE_MAPS_API_KEY = "test-key"
    body = json.dumps(
        {"status": "OK", "results": [{"geometry": {"location": {"lat": 53.8, "lng": -1.55}}}]}
    ).encode()
    with mock.patch("tutortrack.core.net.safe_urlopen", return_value=_Response(body)) as opened:
        point = geo.GoogleGeocoder().geocode("Leeds", "GB")
    assert opened.call_args.args[0].startswith("https://maps.googleapis.com/")
    assert point == geo.GeoPoint(Decimal("53.800000"), Decimal("-1.550000"))


def test_rounded_and_area():
    assert geo.rounded(Decimal("51.4646"), Decimal("-0.1635")) == (51.465, -0.164)
    assert geo.area_of(Address(postcode="sw11 1aa")) == "SW11"
    assert geo.area_of(Address(postcode="SW111AA")) == "SW11"
    assert geo.area_of(Address(city="Leeds")) == "Leeds"
    assert geo.area_of(None) == ""
