"""E22-T06..T09: online meetings (built-in rooms, Zoom, Teams, Google Meet, Lessonspace),
provider defaults, and role-specific join links in portals and reminders."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import transaction

from tutortrack.calendar_sync import meetings
from tutortrack.calendar_sync.models import MeetingPreference, OnlineMeeting
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations import services as integrations
from tutortrack.integrations.providers import ProviderError, fake
from tutortrack.scheduling import services as scheduling
from tutortrack.scheduling.external import join_link
from tutortrack.scheduling.models import Lesson
from tutortrack.tenancy.settings_service import update_settings

from .conftest import connect, make_lesson, settle

pytestmark = pytest.mark.django_db


def reconcile(org, lesson) -> str:
    with tenant_context(org):
        outcome = meetings.reconcile(lesson.pk)
        lesson.refresh_from_db()
        return outcome


def meeting(org, lesson) -> OnlineMeeting:
    with tenant_context(org):
        return OnlineMeeting.objects.select_related("connection").get(lesson=lesson)


def soon():
    """Now, rounded up to the next 5 minutes (lesson times snap to 5-minute steps)."""
    current = now().replace(second=0, microsecond=0)
    return current + timedelta(minutes=5 - current.minute % 5)


def setting(org, **values) -> None:
    with tenant_context(org), transaction.atomic():
        update_settings("integrations", {f"integrations.{k}": v for k, v in values.items()})


def test_online_lessons_get_a_built_in_room_without_any_account(org, people):
    lesson = make_lesson(org, people, online=True)
    assert reconcile(org, lesson) == "created"
    found = meeting(org, lesson)
    assert found.provider == "builtin"
    assert found.status == "active"
    assert lesson.meeting_url == found.join_url
    assert lesson.meeting_provider == "builtin"
    assert OutboxEvent.objects.filter(event_type="online_meeting.created").exists()
    assert reconcile(org, lesson) == "unchanged"


def test_in_person_lessons_and_manual_links_are_left_alone(org, people):
    in_person = make_lesson(org, people)
    assert reconcile(org, in_person) == "skipped"
    manual = make_lesson(
        org, people, start=in_person.start + timedelta(days=1), online=True,
        meeting_url="https://meet.example.com/our-room",
    )  # fmt: skip
    assert reconcile(org, manual) == "skipped"
    assert manual.meeting_url == "https://meet.example.com/our-room"


def test_zoom_with_the_tutors_account_and_role_specific_links(org, people):
    setting(org, video_provider="zoom", zoom_passcode=True)
    connect(org, people["user"], provider="zoom")
    settle(org)
    lesson = make_lesson(org, people, online=True)
    reconcile(org, lesson)
    found = meeting(org, lesson)
    assert found.provider == "zoom"
    assert found.connection.user == people["user"]
    assert found.passcode == "123456"
    with tenant_context(org):
        host = join_link(lesson, "host")
        guest = join_link(lesson, "participant")
        window = 10
    assert host.url == found.host_url != guest.url == found.join_url
    assert host.opens_at == lesson.start - timedelta(minutes=window)


def test_reschedule_updates_and_cancel_deletes_the_meeting(org, people):
    lesson = make_lesson(org, people, online=True)
    reconcile(org, lesson)
    later = lesson.start + timedelta(hours=1)
    with tenant_context(org), transaction.atomic():
        scheduling.update_lesson(lesson, start=later, end=later + timedelta(hours=1))
    assert reconcile(org, lesson) == "updated"
    assert meeting(org, lesson).provisioned_start == later
    with tenant_context(org), transaction.atomic():
        scheduling.cancel_lesson(Lesson.objects.get(pk=lesson.pk))
    assert reconcile(org, lesson) == "deleted"
    assert meeting(org, lesson).status == "deleted"
    assert fake.meeting_state("builtin", meeting(org, lesson).external_id) is None


def test_switching_off_online_removes_the_room_and_link(org, people):
    lesson = make_lesson(org, people, online=True)
    reconcile(org, lesson)
    with tenant_context(org), transaction.atomic():
        scheduling.update_lesson(Lesson.objects.get(pk=lesson.pk), online=False)
    assert reconcile(org, lesson) == "deleted"
    assert lesson.meeting_url == ""


def test_provider_resolution_order(org, people):
    """Lesson → job → tutor preference → service → organisation default."""
    lesson = make_lesson(org, people, online=True)
    with tenant_context(org):
        assert meetings.resolve_provider(lesson)[0] == "builtin"
    setting(org, video_provider_by_service={str(people["service"].pk): "teams"})
    with tenant_context(org):
        assert meetings.resolve_provider(lesson)[0] == "teams"
        MeetingPreference.objects.create(user=people["user"], provider="zoom")
        assert meetings.resolve_provider(lesson)[0] == "zoom"
        lesson.meeting_provider = "google_meet"
        assert meetings.resolve_provider(lesson)[0] == "google_meet"


def test_without_an_account_the_built_in_room_is_used(org, people):
    setting(org, video_provider="teams")
    lesson = make_lesson(org, people, online=True)
    reconcile(org, lesson)
    assert meeting(org, lesson).provider == "builtin"


@pytest.mark.parametrize(("video", "account"), [("teams", "microsoft"), ("google_meet", "google")])
def test_teams_and_meet_use_the_tutors_microsoft_or_google_account(org, people, video, account):
    setting(org, video_provider=video)
    connect(org, people["user"], provider=account)
    settle(org)
    lesson = make_lesson(org, people, online=True)
    reconcile(org, lesson)
    found = meeting(org, lesson)
    assert found.provider == video
    assert found.connection.provider == account


def test_lessonspace_gives_each_student_their_own_link(org, people):
    with tenant_context(org):
        admin = MembershipFactory(organisation=org, role="admin").user
        integrations.connect_with_credentials(
            admin, provider="lessonspace", level="organisation", api_key="ls-key"
        )
    settle(org)
    setting(org, video_provider="lessonspace")
    lesson = make_lesson(org, people, online=True)
    reconcile(org, lesson)
    found = meeting(org, lesson)
    student = str(people["student"].pk)
    assert found.provider == "lessonspace"
    assert found.connection.level == "organisation"
    with tenant_context(org):
        mine = join_link(lesson, "participant", student)
    assert mine.url == found.attendee_urls[student] != found.join_url


def test_a_personal_zoom_room_can_be_the_default(org, people):
    setting(org, video_provider="zoom")
    connect(org, people["user"], provider="zoom")
    settle(org)
    with tenant_context(org):
        MeetingPreference.objects.create(user=people["user"], provider="zoom",
                                         use_personal_room=True)  # fmt: skip
    lesson = make_lesson(org, people, online=True)
    with tenant_context(org):
        spec = meetings.spec_for(lesson, "zoom", MeetingPreference.objects.get())
    assert spec.options["use_personal_room"] is True
    assert spec.options["waiting_room"] is True


def test_provider_failures_propagate_for_retry_and_final_failure_tells_staff(
    org, people, django_capture_on_commit_callbacks
):
    from tutortrack.comms.models import InAppNotification

    lesson = make_lesson(org, people, online=True)
    fake.fail("builtin", times=1)
    with tenant_context(org), pytest.raises(ProviderError):
        meetings.reconcile(lesson.pk)
    with tenant_context(org):
        assert not OnlineMeeting.objects.filter(lesson=lesson).exists()  # rolled back
        coordinator = MembershipFactory(organisation=org, role="coordinator").user
        with django_capture_on_commit_callbacks(execute=True):
            assert meetings.mark_failed(lesson.pk, "builtin is unavailable")
        assert OnlineMeeting.objects.get(lesson=lesson).status == "failed"
        assert InAppNotification.objects.filter(user=coordinator).exists()


# --- T09 join links ------------------------------------------------------------------------------


def test_portal_and_tutor_views_show_role_specific_links_with_timed_enablement(org, people):
    from tutortrack.portal import tutor as tutor_portal

    setting(org, join_window_minutes=15)
    lesson = make_lesson(org, people, start=soon() + timedelta(minutes=5), online=True)
    reconcile(org, lesson)
    found = meeting(org, lesson)
    with tenant_context(org):
        day = tutor_portal.today(people["tutor"], people["user"])
    row = next(r for r in day["lessons"] if r["id"] == str(lesson.pk))
    assert row["join_url"] == found.host_url
    assert row["join_opens_at"] == lesson.start - timedelta(minutes=15)
    api = client_for(org, people["user"])
    body = api.get(f"/api/v1/lessons/{lesson.pk}/join").json()
    assert body["role"] == "host"
    assert body["open"] is True
    assert body["url"] == found.host_url
    later = make_lesson(org, people, start=soon() + timedelta(days=2), online=True)
    reconcile(org, later)
    assert api.get(f"/api/v1/lessons/{later.pk}/join").json()["open"] is False
    in_person = make_lesson(org, people, start=soon() + timedelta(days=3))
    assert api.get(f"/api/v1/lessons/{in_person.pk}/join").status_code == 204


def test_family_portal_lesson_card_gets_the_participant_link(org, people):
    from tutortrack.portal.household import Household
    from tutortrack.portal.selectors import lesson_card

    lesson = make_lesson(org, people, online=True)
    reconcile(org, lesson)
    with tenant_context(org):
        household = Household(role="client", students=[people["student"]])
        card = lesson_card(Lesson.objects.get(pk=lesson.pk), household)
    assert card["join_url"] == meeting(org, lesson).attendee_urls[str(people["student"].pk)]
    assert card["join_opens_at"] == lesson.start - timedelta(minutes=10)


def test_reminders_carry_each_recipients_own_join_link(org, people):
    from tutortrack.comms import catalogue

    lesson = make_lesson(org, people, online=True)
    reconcile(org, lesson)
    found = meeting(org, lesson)
    with tenant_context(org):
        deliveries = catalogue.lesson_deliveries(catalogue.load_lesson(str(lesson.pk)))
    links = {d.recipient.kind: d.context["lesson"]["join_url"] for d in deliveries}
    assert links["tutor"] == found.host_url
    assert links.get("contact", found.join_url) == found.join_url


def test_meeting_preference_api(org, people):
    api = client_for(org, people["user"])
    assert api.get("/api/v1/me/meeting-preference").json() == {
        "provider": "",
        "use_personal_room": False,
    }
    response = api.put("/api/v1/me/meeting-preference", {"provider": "zoom"}, format="json")
    assert response.status_code == 200
    assert response.json()["provider"] == "zoom"
    bad = api.put("/api/v1/me/meeting-preference", {"provider": "skype"}, format="json")
    assert bad.status_code == 400


def test_staff_can_reprovision_a_meeting(org, people, monkeypatch):
    started = []
    monkeypatch.setattr(
        "tutortrack.core.workflows.ops.start_now", lambda *a, **k: started.append(k["id"])
    )
    lesson = make_lesson(org, people, online=True)
    admin = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    with transaction.atomic():  # on_commit runs at the end of the block in tests
        pass
    response = admin.post("/api/v1/online-meetings/provision", {"lesson": str(lesson.pk)},
                          format="json")  # fmt: skip
    assert response.status_code == 202
    tutor = client_for(org, people["user"])
    assert tutor.post("/api/v1/online-meetings/provision", {"lesson": str(lesson.pk)},
                      format="json").status_code == 403  # fmt: skip


class TestOnlineMeetingIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/online-meetings"

    def make_object(self, organisation):
        from tutortrack.catalogue.tests.factories import ServiceFactory
        from tutortrack.people.tests.factories import ClientFactory, StudentFactory

        with tenant_context(organisation):
            client = ClientFactory(organisation=organisation)
            student = StudentFactory(organisation=organisation, client=client)
            start = soon() + timedelta(days=2)
            with transaction.atomic():
                lesson = scheduling.create_lesson(
                    start=start, end=start + timedelta(hours=1),
                    service=ServiceFactory(organisation=organisation),
                    attendees=[{"student": student}], online=True,
                ).lesson  # fmt: skip
            return OnlineMeeting.objects.create(
                lesson=lesson, provider="builtin", status="active",
                join_url="https://x.test/r",
            )  # fmt: skip
