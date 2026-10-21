"""Gap G5c (FR-21-8): resources shared into an online lesson's classroom."""

from __future__ import annotations

import pytest

from tutortrack.calendar_sync import meetings
from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.testing import client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.learning import services as learning
from tutortrack.learning.models import Resource, ResourceActivity
from tutortrack.learning.tests.factories import ResourceFactory

from .conftest import make_lesson
from .test_video import family_user

pytestmark = pytest.mark.django_db


def online_lesson(org, people):
    lesson = make_lesson(org, people, online=True)
    with tenant_context(org):
        meetings.reconcile(lesson.pk)
    return lesson


def test_staff_share_reaches_the_room_for_tutor_and_family(org, people):
    """FR-21-8: a resource attached to an online lesson is in its classroom, and everyone
    in the room can open it."""
    lesson = online_lesson(org, people)
    with tenant_context(org):
        sheet = ResourceFactory(
            organisation=org,
            title="Fractions worksheet",
            visibility=Resource.Visibility.STAFF,
            url="https://example.com/fractions",
        )
        hidden = ResourceFactory(organisation=org, title="Not shared")
        learning.share_resource(sheet, lessons=[lesson], message="For today")
    tutor = client_for(org, people["user"])
    room = tutor.get(f"/api/v1/lessons/{lesson.pk}/classroom").json()
    assert [(r["title"], r["kind"], r["message"]) for r in room["resources"]] == [
        ("Fractions worksheet", "link", "For today")
    ]
    opened = tutor.post(f"/api/v1/lessons/{lesson.pk}/classroom/resources/{sheet.pk}/open")
    assert opened.status_code == 200, opened.content
    assert opened.json() == {
        "url": "https://example.com/fractions",
        "expires_in": None,
        "kind": "link",
    }
    family = client_for(org, family_user(org, people))
    assert (
        family.post(f"/api/v1/lessons/{lesson.pk}/classroom/resources/{sheet.pk}/open").json()[
            "url"
        ]
        == "https://example.com/fractions"
    )
    with tenant_context(org):
        assert ResourceActivity.objects.filter(resource=sheet).count() == 2
    not_shared = family.post(f"/api/v1/lessons/{lesson.pk}/classroom/resources/{hidden.pk}/open")
    assert not_shared.status_code == 404
    stranger = client_for(org, MembershipFactory(organisation=org, role="client").user)
    gone = stranger.post(f"/api/v1/lessons/{lesson.pk}/classroom/resources/{sheet.pk}/open")
    assert gone.status_code == 404


def test_tutor_shares_into_the_room_and_the_family_is_sent_there(org, people):
    lesson = online_lesson(org, people)
    family_user(org, people)
    with tenant_context(org):
        mine = ResourceFactory(
            organisation=org, owner=people["tutor"], visibility=Resource.Visibility.PRIVATE
        )
    tutor = client_for(org, people["user"])
    shared = tutor.post(
        f"/api/v1/learning/resources/{mine.pk}/share",
        {"lessons": [str(lesson.pk)]},
        format="json",
    )
    assert shared.status_code in (200, 201), shared.content
    ids = [r["id"] for r in tutor.get(f"/api/v1/lessons/{lesson.pk}/classroom").json()["resources"]]
    assert ids == [str(mine.pk)]
    dispatch_batch()  # resource.shared → the family's notice links to the classroom
    with tenant_context(org):
        notice = Message.objects.filter(type_key="resource_shared", channel="email").first()
    assert notice is not None
    assert f"/portal/classroom/{lesson.pk}" in notice.body
