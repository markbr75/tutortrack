"""E15-T09: portal messaging through the E13 inbox (families, students and tutors), and
booking a makeup lesson with a makeup credit."""

from __future__ import annotations

import pytest

from tutortrack.comms import inbox
from tutortrack.comms.models import Message, Thread, ThreadMessage
from tutortrack.core.context import tenant_context
from tutortrack.core.testing import client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.tenancy import settings_service

from .test_portal import lesson_for, make_household, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db


def set_portal(org, **values):
    with tenant_context(org):
        settings_service.update_settings("portal", {f"portal.{k}": v for k, v in values.items()})


def test_families_message_the_business(org, world):  # noqa: F811
    a = world["a"]
    me = a["api"].get("/api/v1/portal/me").json()
    assert me["features"]["messages"] is True
    assert me["features"]["message_tutors"] is False
    started = a["api"].post(
        "/api/v1/portal/threads",
        {"subject": "Thursday", "body": "Can Arjun start at 5pm?"},
        format="json",
    )
    assert started.status_code == 201, started.json()
    thread_id = started.json()["id"]
    assert started.json()["messages"][0]["mine"] is True
    staff = MembershipFactory(organisation=org, role="admin").user
    with tenant_context(org):
        thread = Thread.objects.get(pk=thread_id)
        assert (thread.kind, thread.client_id) == ("client", a["client"].pk)
        inbox.add_note(thread, staff, body="Check tutor availability")
        inbox.reply(thread, staff, body="Yes, see you at 5!", channel="chat")
        # The family is told by email that a reply is waiting.
        assert Message.objects.filter(type_key="conversation_message_family").exists()
    listed = a["api"].get("/api/v1/portal/threads").json()
    assert listed[0]["unread"] == 1
    detail = a["api"].get(f"/api/v1/portal/threads/{thread_id}").json()
    # Internal notes never reach the portal.
    assert [m["body"] for m in detail["messages"]] == [
        "Can Arjun start at 5pm?",
        "Yes, see you at 5!",
    ]
    assert detail["messages"][1]["from_business"] is True
    assert a["api"].get("/api/v1/portal/threads").json()[0]["unread"] == 0
    posted = a["api"].post(
        f"/api/v1/portal/threads/{thread_id}/messages", {"body": "Thanks!"}, format="json"
    )
    assert posted.status_code == 201


def test_households_cannot_see_each_others_conversations(org, world):  # noqa: F811
    a, b = world["a"], world["b"]
    theirs = b["api"].post("/api/v1/portal/threads", {"body": "Private"}, format="json").json()
    assert a["api"].get(f"/api/v1/portal/threads/{theirs['id']}").status_code == 404
    assert (
        a["api"]
        .post(f"/api/v1/portal/threads/{theirs['id']}/messages", {"body": "x"}, format="json")
        .status_code
        == 404
    )
    assert a["api"].get("/api/v1/portal/threads").json() == []


def test_messaging_can_be_turned_off(org, world):  # noqa: F811
    set_portal(org, allow_messaging=False)
    a = world["a"]
    assert a["api"].get("/api/v1/portal/me").json()["features"]["messages"] is False
    assert a["api"].get("/api/v1/portal/threads").status_code == 403


def test_families_and_tutors_message_each_other_when_allowed(org, world):  # noqa: F811
    a = world["a"]
    member = MembershipFactory(organisation=org, role="tutor")
    tutor = world["tutor"]
    with tenant_context(org):
        type(tutor).objects.filter(pk=tutor.pk).update(membership=member)
    lesson_for(org, world, [a["students"][0]])
    stranger = TutorProfileFactory(organisation=org, status="active")
    blocked = a["api"].post(
        "/api/v1/portal/threads", {"body": "Hi", "tutor": str(tutor.pk)}, format="json"
    )
    assert blocked.status_code == 403  # tutor messaging is off by default
    set_portal(org, allow_messaging_tutors=True)
    tutors = a["api"].get("/api/v1/portal/messaging/tutors").json()
    assert [t["id"] for t in tutors] == [str(tutor.pk)]
    not_theirs = a["api"].post(
        "/api/v1/portal/threads", {"body": "Hi", "tutor": str(stranger.pk)}, format="json"
    )
    assert not_theirs.status_code == 404
    started = a["api"].post(
        "/api/v1/portal/threads",
        {"subject": "Homework", "body": "Is chapter 3 due?", "tutor": str(tutor.pk)},
        format="json",
    )
    assert started.status_code == 201
    assert started.json()["with_name"] == tutor.full_name
    # The tutor sees it in their portal and answers.
    tutor_api = client_for(org, member.user)
    rows = tutor_api.get("/api/v1/tutor/threads").json()
    assert [r["id"] for r in rows] == [started.json()["id"]]
    answered = tutor_api.post(
        f"/api/v1/tutor/threads/{rows[0]['id']}/messages", {"body": "Yes, Friday."}, format="json"
    )
    assert answered.status_code == 201
    with tenant_context(org):
        assert Message.objects.filter(type_key="conversation_message_tutor").exists()
        assert Message.objects.filter(type_key="conversation_message_family").exists()
    # Staff see every message (safeguarding).
    staff = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    staff_rows = staff.get("/api/v1/threads?kind=tutor_family").json()["results"]
    assert len(staff_rows) == 1
    # Tutors message the families they teach.
    families = tutor_api.get("/api/v1/tutor/messaging/families").json()
    assert [f["id"] for f in families] == [str(a["client"].pk)]
    office = tutor_api.post("/api/v1/tutor/threads", {"body": "Running late"}, format="json")
    assert office.json()["kind"] == "tutor"


def test_students_message_only_when_allowed(org):
    from tutortrack.people import services as people
    from tutortrack.people.tests.factories import ClientFactory, StudentFactory

    client = ClientFactory(organisation=org)
    student = StudentFactory(organisation=org, client=client, first_name="Maya")
    member = MembershipFactory(organisation=org, role="student")
    with tenant_context(org):
        people.link_portal_user("people.student", str(student.pk), member.user)
    api = client_for(org, member.user)
    assert api.get("/api/v1/portal/me").json()["features"]["messages"] is False
    set_portal(org, allow_student_messaging=True)
    started = api.post("/api/v1/portal/threads", {"body": "Can I get extra help?"}, format="json")
    assert started.status_code == 201, started.json()
    assert len(api.get("/api/v1/portal/threads").json()) == 1
    with tenant_context(org):
        entry = ThreadMessage.objects.get()
        assert entry.author_type == "student"
