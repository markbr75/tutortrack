"""Gap batch G4 (E13): realtime notifications over SSE, template overrides per language
and branch, a direct channel to students, digests, account emails on comms templates,
Mailchimp/Brevo unsubscribes flowing back, the new notification types and push for
messages."""

from __future__ import annotations

import asyncio
import json
import threading
import time as clock
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core import mail

from tutortrack.comms import (
    account_emails,
    digests,
    g4_types,
    marketing_inbound,
    realtime,
    registry,
    services,
    students,
)
from tutortrack.comms.marketing_providers import FAKE_AUDIENCES
from tutortrack.comms.models import (
    CommunicationPreference,
    DigestPreference,
    InAppNotification,
    Message,
    Suppression,
)
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, StudentFactory
from tutortrack.privacy import services as privacy
from tutortrack.tenancy import settings_service
from tutortrack.tenancy.tests.factories import BranchFactory

from .test_comms import family, lesson_at, messages  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db
LONDON = ZoneInfo("Europe/London")


@pytest.fixture
def admin(org):
    membership = MembershipFactory(organisation=org, role="admin")
    return client_for(org, membership.user), membership.user


def set_setting(org, key, value):
    with tenant_context(org):
        settings_service.update_settings(key.split(".")[0], {key: value})


# --- 1. realtime notifications (FR-13-1/8) ------------------------------------------------------


def _next_message(listener):
    for _ in range(20):
        message = listener.get_message(timeout=0.1)
        if message is not None:
            return message
    raise AssertionError("nothing was published")


def _collect(content, until: float = 3.0) -> list[str]:
    out = []
    deadline = clock.monotonic() + until
    for chunk in content:
        out.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        if clock.monotonic() > deadline:
            break
    return out


def test_stream_needs_a_signed_in_member(org, other_org):
    from rest_framework.test import APIClient

    anonymous = APIClient()
    response = anonymous.get(
        "/api/v1/notifications/stream", HTTP_HOST="brightminds.tutortrack.test"
    )
    assert response.status_code in {401, 403}
    outsider = UserFactory()
    MembershipFactory(organisation=other_org, user=outsider)
    assert client_for(org, outsider).get("/api/v1/notifications/stream").status_code == 403


def test_new_notifications_are_published_to_the_users_channel(
    org, admin, fake_redis, django_capture_on_commit_callbacks
):
    _api, user = admin
    listener = fake_redis.pubsub(ignore_subscribe_messages=True)
    listener.subscribe(realtime.channel_name(org.pk, user.pk))
    with tenant_context(org), django_capture_on_commit_callbacks(execute=True):
        services.test_send("task_assigned", "in_app", user=user)
    payload = json.loads(_next_message(listener)["data"])
    assert payload["event"] == "notification"
    assert payload["data"]["type_key"] == "task_assigned"
    with tenant_context(org), django_capture_on_commit_callbacks(execute=True):
        services.mark_read(user)
    assert json.loads(_next_message(listener)["data"])["event"] == "read"


def test_stream_delivers_only_its_own_users_organisation(
    org, other_org, admin, fake_redis, settings
):
    settings.COMMS = {**settings.COMMS, "SSE_MAX_SECONDS": 2, "SSE_HEARTBEAT_SECONDS": 1}
    api, user = admin
    MembershipFactory(organisation=other_org, user=user)  # the same person, another tenant
    response = api.get("/api/v1/notifications/stream", HTTP_ACCEPT="text/event-stream")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")
    assert response["Cache-Control"].startswith("no-cache")

    def publish() -> None:
        clock.sleep(0.4)
        for org_id, title in ((other_org.pk, "Not for this stream"), (org.pk, "Lesson moved")):
            fake_redis.publish(
                realtime.channel_name(org_id, user.pk),
                json.dumps({"event": "notification", "data": {"title": title}}),
            )

    threading.Thread(target=publish, daemon=True).start()
    body = "".join(_collect(response.streaming_content))
    assert body.startswith("retry: ")
    assert 'event: ready\ndata: {"unread": 0}' in body
    assert "Lesson moved" in body
    assert "Not for this stream" not in body
    assert ": keep-alive" in body


def test_stream_says_when_realtime_is_unavailable(monkeypatch):
    class Broken:
        def pubsub(self, **kwargs):
            raise ConnectionError("redis down")

    monkeypatch.setattr("tutortrack.core.redis.get_redis", lambda: Broken())
    frames = list(realtime.sync_stream("comms:inapp:x:y", unread=3, seconds=1, beat=1))
    assert "event: unavailable" in frames[-1]


def test_async_stream_for_asgi(monkeypatch):
    import fakeredis

    server = fakeredis.FakeServer()
    monkeypatch.setattr(realtime, "async_client", lambda: fakeredis.FakeAsyncRedis(server=server))

    async def run() -> list[str]:
        stream = realtime.async_stream("comms:inapp:o:u", unread=1, seconds=2, beat=5)
        frames = [await stream.__anext__()]

        async def publish() -> None:
            await asyncio.sleep(0.3)
            await fakeredis.FakeAsyncRedis(server=server).publish(
                "comms:inapp:o:u", json.dumps({"event": "read", "data": {"count": 2}})
            )

        task = asyncio.create_task(publish())
        async for frame in stream:
            frames.append(frame)
        await task
        return frames

    frames = asyncio.run(run())
    assert '"unread": 1' in frames[0]
    assert any(f.startswith("event: read") for f in frames)


# --- 2. template overrides per language and branch (FR-13-3) ------------------------------------


def test_overrides_resolve_by_language_then_branch(org):
    with tenant_context(org):
        north = BranchFactory(organisation=org, name="North")
        services.save_template("lesson_booked", "email", subject="Org", body="org")
        services.save_template("lesson_booked", "email", subject="FR", body="fr", locale="fr")
        services.save_template(
            "lesson_booked", "email", subject="North", body="n", branch_id=north.pk
        )
        services.save_template(
            "lesson_booked",
            "email",
            subject="North FR",
            body="nfr",
            locale="fr-FR",
            branch_id=north.pk,
        )
        pick = services.template_for
        assert pick("lesson_booked", "email", "en-GB").subject == "Org"
        assert pick("lesson_booked", "email", "fr-CA").subject == "FR"
        assert pick("lesson_booked", "email", "", north.pk).subject == "North"
        assert pick("lesson_booked", "email", "fr-FR", north.pk).subject == "North FR"
        assert pick("lesson_booked", "email", "fr-BE", north.pk).subject == "FR"
        services.revert_template("lesson_booked", "email", locale="fr")
        assert pick("lesson_booked", "email", "fr-CA").subject == "Org"
        with pytest.raises(BusinessRuleViolation):
            services.save_template(
                "lesson_booked", "email", subject="x", body="y", locale="fr; drop"
            )


def test_a_french_speaking_contact_gets_the_french_template(org, family):  # noqa: F811
    with tenant_context(org):
        family["contact"].language = "fr"
        family["contact"].save()
        services.save_template(
            "lesson_booked", "email", subject="Cours réservé", body="Bonjour", locale="fr"
        )
    lesson_at(org, family, now() + timedelta(days=3))
    with tenant_context(org):
        from tutortrack.comms.catalogue import load_lesson
        from tutortrack.scheduling.models import Lesson

        lesson = load_lesson(str(Lesson.objects.get().pk))
        services.notify("lesson_booked", lesson, key="fr-test")
    sent = messages(org, type_key="lesson_booked", recipient_type="contact")
    assert sent[-1].subject == "Cours réservé"


def test_template_api_scopes_and_variants(org, admin):
    api, _user = admin
    with tenant_context(org):
        north = BranchFactory(organisation=org, name="North")
    url = "/api/v1/message-templates/lesson_booked/email"
    saved = api.put(f"{url}?locale=de", {"subject": "Hallo", "body": "Hallo"}, format="json")
    assert saved.status_code == 200, saved.json()
    assert saved.json()["locale"] == "de"
    assert saved.json()["customised"] is True
    api.put(f"{url}?branch={north.pk}", {"subject": "N", "body": "n"}, format="json")
    assert api.get(url).json()["customised"] is False  # the any-language slot is untouched
    variants = api.get(f"{url}/variants").json()
    assert {(v["locale"], v["branch_name"]) for v in variants} == {("de", ""), ("", "North")}
    api.delete(f"{url}?locale=de")
    assert len(api.get(f"{url}/variants").json()) == 1


class TestTemplateVariantIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/message-templates/lesson_booked/email/variants"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return services.save_template(
                "lesson_booked", "email", subject="S", body="B", locale="it"
            )

    def test_detail_of_other_organisation_is_404(self, org, other_org):
        """There is no detail: another organisation's branch can't be addressed."""
        with tenant_context(other_org):
            theirs = BranchFactory(organisation=other_org)
        api = client_for(org, self.acting_user(org))
        response = api.put(
            f"/api/v1/message-templates/lesson_booked/email?branch={theirs.pk}",
            {"subject": "x", "body": "y"},
            format="json",
        )
        assert response.status_code == 422


# --- 3. a direct channel to students (FR-13-2/5) ------------------------------------------------


def _student(org, family, age, *, login=True):  # noqa: F811
    today = now().date()
    user = UserFactory(email=f"student{age}@example.com") if login else None
    return StudentFactory(
        organisation=org,
        client=family["client"],
        first_name=f"Kid{age}",
        date_of_birth=today.replace(year=today.year - age) - timedelta(days=2),
        user=user,
    )


def test_students_get_lesson_messages_only_when_allowed(org, family):  # noqa: F811
    teen = _student(org, family, 15)
    child = _student(org, family, 11)
    with tenant_context(org):
        assert students.student_recipient(teen) is None  # off by default
    set_setting(org, "comms.student_direct", "teens")
    with tenant_context(org):
        r = students.student_recipient(teen)
        assert r.kind == "student"
        assert r.email == "student15@example.com"
        assert r.user_id
        assert students.student_recipient(child) is None  # under 13: guardians only
        unknown = StudentFactory(organisation=org, client=family["client"], date_of_birth=None)
        assert students.student_recipient(unknown) is None
    set_setting(org, "comms.student_direct", "adults")
    with tenant_context(org):
        assert students.student_recipient(teen) is None


def test_lesson_booked_reaches_a_teen_but_never_marketing(org, family):  # noqa: F811
    set_setting(org, "comms.student_direct", "teens")
    teen = _student(org, family, 16)
    with tenant_context(org):
        from tutortrack.scheduling import services as scheduling

        start = (now() + timedelta(days=4)).replace(minute=0, second=0, microsecond=0)
        lesson = scheduling.create_lesson(
            start=start,
            end=start + timedelta(hours=1),
            service=family["service"],
            attendees=[{"student": teen}],
            tutors=[{"tutor": family["tutor"]}],
            timezone="Europe/London",
            override_conflicts=True,
        ).lesson
        from tutortrack.comms.catalogue import load_lesson

        services.notify("lesson_booked", load_lesson(str(lesson.pk)), key="teen")
        mine = Message.objects.filter(recipient_type="student", recipient_id=str(teen.pk))
        assert (
            mine.filter(channel="email", status="queued").exists()
            or mine.filter(channel="email", status="sent").exists()
        )
        r = students.student_recipient(teen)
        marketing = services.queue_message(
            type_key="broadcast_marketing",
            channel="email",
            recipient=r,
            subject="Offer",
            body="Buy",
            dedupe_key="mkt-teen",
            category="marketing",
        )
        assert marketing.status == Message.Status.SUPPRESSED
        assert "no_marketing" in marketing.error or "aadc" in marketing.error


def test_nothing_goes_straight_to_an_under_13(org, family):  # noqa: F811
    child = _student(org, family, 10)
    with tenant_context(org):
        r = registry.Recipient(
            kind="student", id=str(child.pk), name="Kid", first_name="Kid", email="kid@example.com"
        )
        message = services.queue_message(
            type_key="inbox_reply",
            channel="email",
            recipient=r,
            subject="Hi",
            body="Hi",
            dedupe_key="child-direct",
        )
        assert message.status == Message.Status.SUPPRESSED
        assert message.error == "children:guardians_only"


# --- 4. digests (FR-13-2/7) ---------------------------------------------------------------------


def test_due_follows_the_persons_timezone_and_day():
    choice = digests.Choice("weekly_schedule", "Weekly", True, True, time(18, 0), 6, False)
    sunday_6pm_london = datetime(2026, 11, 1, 18, 20, tzinfo=LONDON)
    assert digests.due(sunday_6pm_london, LONDON, choice) == date(2026, 11, 1)
    assert digests.due(sunday_6pm_london - timedelta(minutes=30), LONDON, choice) is None
    assert digests.due(sunday_6pm_london + timedelta(hours=1), LONDON, choice) is None
    assert digests.due(sunday_6pm_london - timedelta(days=1), LONDON, choice) is None
    tokyo = ZoneInfo("Asia/Tokyo")
    daily = digests.Choice("tutor_agenda", "Agenda", True, True, time(7, 0), None, False)
    assert digests.due(datetime(2026, 11, 2, 7, 5, tzinfo=tokyo), tokyo, daily)
    off = digests.Choice("tutor_agenda", "Agenda", False, True, time(7, 0), None, False)
    assert digests.due(datetime(2026, 11, 2, 7, 5, tzinfo=tokyo), tokyo, off) is None


def _agenda_moment(org, family, *, hour=7, minute=10):  # noqa: F811
    """A lesson at 16:00 London today and the moment the agenda is due."""
    day = now().astimezone(LONDON).date() + timedelta(days=1)
    lesson_at(org, family, datetime.combine(day, time(16, 0), tzinfo=LONDON))
    return datetime.combine(day, time(hour, minute), tzinfo=LONDON)


def test_tutor_agenda_is_sent_once_at_their_time(org, family):  # noqa: F811
    family["tutor_user"].timezone = "Europe/London"
    family["tutor_user"].save()
    moment = _agenda_moment(org, family)
    with tenant_context(org):
        assert digests.run(moment)["tutor_agenda"] == 0  # off until the organisation opts in
        services.update_setting("tutor_daily_agenda", enabled=True, channels=["email"])
        assert digests.run(moment - timedelta(hours=2))["tutor_agenda"] == 0
        assert digests.run(moment)["tutor_agenda"] == 1
        assert digests.run(moment + timedelta(minutes=15))["tutor_agenda"] == 0  # deduped
    (sent,) = messages(org, type_key="tutor_daily_agenda")
    assert "16:00" in sent.body
    assert "Maths" in sent.body


def test_a_tutor_can_choose_their_agenda_time_or_switch_it_off(org, family):  # noqa: F811
    api = client_for(org, family["tutor_user"])
    rows = api.get("/api/v1/digest-preferences/mine").json()
    assert [r["kind"] for r in rows] == ["tutor_agenda", "message_digest"]
    assert rows[0]["send_time"] == "07:00"
    assert rows[0]["org_enabled"] is False
    saved = api.put(
        "/api/v1/digest-preferences/mine",
        [{"kind": "tutor_agenda", "enabled": True, "send_time": "06:30"}],
        format="json",
    )
    assert saved.status_code == 200, saved.json()
    assert saved.json()[0]["send_time"] == "06:30"
    refused = api.put(
        "/api/v1/digest-preferences/mine", [{"kind": "weekly_schedule"}], format="json"
    )
    assert refused.status_code == 422
    moment = _agenda_moment(org, family, hour=6, minute=40)
    with tenant_context(org):
        services.update_setting("tutor_daily_agenda", enabled=True, channels=["email"])
        assert digests.run(moment)["tutor_agenda"] == 1
        DigestPreference.objects.filter(kind="tutor_agenda").update(enabled=False)
        assert digests.run(moment + timedelta(days=1))["tutor_agenda"] == 0


def test_weekly_schedule_goes_to_families_on_their_day(org, family):  # noqa: F811
    day = now().astimezone(LONDON).date()
    sunday = day + timedelta(days=(6 - day.weekday()) % 7 or 7)
    lesson_at(org, family, datetime.combine(sunday + timedelta(days=2), time(16), tzinfo=LONDON))
    moment = datetime.combine(sunday, time(18, 5), tzinfo=LONDON)
    with tenant_context(org):
        services.update_setting("client_weekly_schedule", enabled=True, channels=["email"])
        assert digests.run(moment - timedelta(days=1))["weekly_schedule"] == 0
        assert digests.run(moment)["weekly_schedule"] == 1
    (sent,) = messages(org, type_key="client_weekly_schedule")
    assert sent.to == "priya@example.com"


def test_message_digest_lists_unread_messages(org, admin):
    _api, user = admin
    user.timezone = "Europe/London"
    user.save()
    with tenant_context(org):
        InAppNotification.objects.create(
            user=user, type_key="inbox_new_message", title="New message from Priya", body="Hello"
        )
        services.update_setting("message_digest", enabled=True, channels=["email"])
        local = now().astimezone(LONDON)
        moment = datetime.combine(local.date(), time(17, 10), tzinfo=LONDON)
        if moment < now():
            InAppNotification.objects.update(created_at=moment - timedelta(hours=1))
        assert digests.run(moment)["message_digest"] == 1
    (sent,) = messages(org, type_key="message_digest")
    assert "New message from Priya" in sent.body


class TestDigestPreferenceIsolation:
    def test_mine_never_shows_another_organisations_rows(self, org, other_org):
        user = UserFactory()
        MembershipFactory(organisation=org, user=user)
        MembershipFactory(organisation=other_org, user=user)
        with tenant_context(other_org):
            DigestPreference.objects.create(
                person_type="user", person_id=str(user.pk), kind="message_digest", enabled=False
            )
        rows = client_for(org, user).get("/api/v1/digest-preferences/mine").json()
        assert rows[0]["enabled"] is True
        assert rows[0]["customised"] is False


# --- 5. account emails on comms templates (E02/E03) ---------------------------------------------


def test_account_emails_inside_an_organisation_are_branded_logged_and_hide_links(org):
    user = UserFactory(first_name="Sam")
    MembershipFactory(organisation=org, user=user)
    from tutortrack.identity.tasks import send_magic_link

    url = "https://brightminds.tutortrack.test/login/magic?token=SECRET123"
    send_magic_link(user_id=str(user.pk), url=url, organisation_id=str(org.pk))
    (email,) = mail.outbox
    assert url in email.body
    assert email.alternatives  # branded HTML
    with tenant_context(org):
        logged = Message.objects.get(type_key="account_magic_link")
        assert "SECRET123" not in logged.body
        assert account_emails.HIDDEN in logged.body
        services.save_template(
            "account_magic_link",
            "email",
            subject="Sign in to {{ organisation.name }}",
            body="Hi {{ recipient.first_name }}: {{ link }}",
        )
    send_magic_link(user_id=str(user.pk), url=url, organisation_id=str(org.pk))
    assert mail.outbox[1].subject == "Sign in to Bright Minds"
    assert mail.outbox[1].body == f"Hi Sam: {url}"


def test_platform_account_emails_use_the_platform_template(org):
    user = UserFactory(first_name="Sam")
    from tutortrack.identity.tasks import send_password_reset

    send_password_reset(user_id=str(user.pk), url="https://app.tutortrack.test/reset?t=1")
    (email,) = mail.outbox
    assert email.subject == "Reset your password"
    assert "https://app.tutortrack.test/reset?t=1" in email.body
    with tenant_context(org):
        assert not Message.objects.filter(type_key="account_password_reset").exists()


def test_account_emails_can_be_edited_but_not_switched_off(org, admin):
    api, _user = admin
    row = next(
        r
        for r in api.get("/api/v1/notification-settings").json()
        if r["key"] == "account_password_reset"
    )
    assert row["locked"] is True
    response = api.put(
        "/api/v1/notification-settings/account_password_reset",
        {"enabled": False, "channels": ["email"]},
        format="json",
    )
    assert response.status_code == 422


# --- 6. Mailchimp/Brevo unsubscribes (FR-13-9) --------------------------------------------------


def _consented_contact(org, email):
    client = ClientFactory(organisation=org, display_name=email)
    contact = ContactFactory(organisation=org, client=client, first_name="Pat", email=email)
    with tenant_context(org):
        privacy.ensure_default_types()
        privacy.record_consent(
            subject_type="people.contact",
            subject_id=str(contact.pk),
            key="marketing-email",
            granted=True,
            method="staff",
        )
    return contact


@pytest.fixture
def mailchimp(org, admin):
    FAKE_AUDIENCES.clear()
    api, _user = admin
    created = api.post(
        "/api/v1/integrations/connections",
        {"provider": "mailchimp", "level": "organisation", "api_key": "abc123-us21"},
        format="json",
    ).json()
    api.put("/api/v1/marketing-sync/mailchimp/audiences", {"audience_id": "aud1"}, format="json")
    row = api.get("/api/v1/marketing-sync").json()[0]
    return api, created["id"], row["webhook_url"]


def _path(url):
    return url.split("tutortrack", 1)[-1].split("/api/v1", 1)[1]


def test_mailchimp_unsubscribe_webhook_withdraws_consent(org, mailchimp):
    _api, _connection, url = mailchimp
    contact = _consented_contact(org, "pat@example.com")
    from django.test import Client

    hook = Client()  # Mailchimp posts form-encoded data
    path = "/api/v1" + _path(url)
    assert hook.get(path).status_code == 200  # Mailchimp's URL check
    assert hook.post(path.replace("mailchimp", "brevo"), {}).status_code == 403
    assert hook.post(path[:-3] + "xyz", {}).status_code == 403
    other_list = {"type": "unsubscribe", "data[email]": "pat@example.com", "data[list_id]": "aud2"}
    assert hook.post(path, other_list).status_code == 200
    with tenant_context(org):
        assert privacy.is_granted("people.contact", str(contact.pk), "marketing-email")
    done = hook.post(path, {**other_list, "data[list_id]": "aud1"})
    assert done.status_code == 200, done.content
    with tenant_context(org):
        assert not privacy.is_granted("people.contact", str(contact.pk), "marketing-email")
        pref = CommunicationPreference.objects.get(person_id=str(contact.pk), category="marketing")
        assert "email" not in pref.channels
        assert not Suppression.objects.exists()  # service emails still go


def test_cleaned_and_spam_reports_suppress_the_address(org, mailchimp):
    _api, _connection, url = mailchimp
    contact = _consented_contact(org, "dead@example.com")
    from django.test import Client

    path = "/api/v1" + _path(url)
    Client().post(
        path,
        {
            "type": "cleaned",
            "data[email]": "dead@example.com",
            "data[list_id]": "aud1",
            "data[reason]": "hard",
        },
    )
    with tenant_context(org):
        assert Suppression.objects.get(address="dead@example.com").reason == "mailchimp_cleaned"
        assert privacy.is_granted("people.contact", str(contact.pk), "marketing-email")
        changed = marketing_inbound.apply("brevo", "dead@example.com", marketing_inbound.SPAM)
        assert changed == 0  # already suppressed, so no longer opted in


def test_brevo_webhook_json(org, admin):
    api, _user = admin
    created = api.post(
        "/api/v1/integrations/connections",
        {"provider": "brevo", "level": "organisation", "api_key": "xkeysib-123"},
        format="json",
    ).json()
    contact = _consented_contact(org, "bee@example.com")
    with tenant_context(org):
        path = marketing_inbound.webhook_url("brevo", created["id"]).split("tutortrack", 1)[-1]
    from rest_framework.test import APIClient

    response = APIClient().post(
        "/api/v1" + path.split("/api/v1", 1)[1],
        {"event": "unsubscribed", "email": "bee@example.com", "list_id": [7]},
        format="json",
    )
    assert response.status_code == 200
    with tenant_context(org):
        assert not privacy.is_granted("people.contact", str(contact.pk), "marketing-email")


def test_sync_now_reads_unsubscribes_back_first(org, mailchimp):
    api, _connection, _url = mailchimp
    contact = _consented_contact(org, "left@example.com")
    assert api.post("/api/v1/marketing-sync/mailchimp/sync").json()["upserted"] == 1
    (audience,) = [a["aud1"] for a in FAKE_AUDIENCES.values()]
    audience["left@example.com"]["status"] = "unsubscribed"  # they left in Mailchimp
    result = api.post("/api/v1/marketing-sync/mailchimp/sync").json()
    assert result["opted_out"] == 1
    assert result["upserted"] == 0
    assert audience["left@example.com"]["status"] == "unsubscribed"  # not re-subscribed
    with tenant_context(org):
        assert not privacy.is_granted("people.contact", str(contact.pk), "marketing-email")


# --- 7. new notification types (FR-13-2) --------------------------------------------------------


def test_new_types_are_registered_with_templates():
    for key in (
        "card_expiring",
        "client_statement",
        "low_attendance",
        "expense_approved",
        "expense_rejected",
        "booking_declined",
        "package_low",
    ):
        t = registry.get(key)
        source = services.defaults.default_template(key, t.default_channels[0])
        assert source is not None, key
        services.render.render(source[1], dict(t.sample), timezone="Europe/London")


def test_card_expiry_and_statement_checks_run_once_a_day(org, family, monkeypatch):  # noqa: F811
    with tenant_context(org):
        monkeypatch.setattr(g4_types, "expiring_cards", lambda today: [_fake_card(family)])
        moment = datetime.combine(now().astimezone(LONDON).date(), time(9, 5), tzinfo=LONDON)
        assert g4_types.run_daily(moment - timedelta(hours=2)) == {"cards": 0, "statements": 0}
        assert g4_types.run_daily(moment)["cards"] == 1
        assert g4_types.run_daily(moment + timedelta(minutes=15))["cards"] == 0
    (sent,) = messages(org, type_key="card_expiring")
    assert "4242" in sent.body


def _fake_card(family):  # noqa: F811
    class Card:
        pk = "card-1"
        brand = "Visa"
        last4 = "4242"
        exp_month = 11
        exp_year = 2026
        client = family["client"]
        branch_id = None

    return Card()


def test_statement_covers_last_month():
    assert g4_types._statement_period(date(2026, 11, 1)) == (date(2026, 10, 1), date(2026, 10, 31))


def test_low_attendance_alerts_staff_once_a_week(org, family, admin):  # noqa: F811
    from tutortrack.core.events import EventEnvelope
    from tutortrack.scheduling.models import LessonAttendee

    set_setting(org, "comms.low_attendance_lessons", 2)
    first = lesson_at(org, family, now() - timedelta(days=9))
    second = lesson_at(org, family, now() - timedelta(days=2))
    with tenant_context(org):
        from tutortrack.scheduling.models import Lesson

        Lesson.objects.filter(pk__in=[first.pk, second.pk]).update(status="completed")
        LessonAttendee.objects.filter(lesson=first).update(outcome="no_show")
        LessonAttendee.objects.filter(lesson=second).update(outcome="present")
        assert g4_types.attendance_rate(family["student"], 2) == (50, 2)
        event = EventEnvelope(
            id=uuid.uuid4(),
            type="lesson.completed",
            version=1,
            occurred_at=now(),
            organisation_id=org.pk,
            branch_id=None,
            actor={},
            subject={"type": "lesson", "id": str(second.pk)},
            data={},
            changes={},
        )
        g4_types.low_attendance(event)
        g4_types.low_attendance(event)
    alerts = messages(org, type_key="low_attendance")
    assert len(alerts) == 1
    assert "50%" in alerts[0].subject


def test_booking_declined_tells_the_new_family(org, family, monkeypatch):  # noqa: F811
    class Hold:
        pk = "hold-1"
        client_id = None
        client = None
        start = now() + timedelta(days=2)
        timezone = "Europe/London"
        contact = {"first_name": "Lee", "email": "lee@example.com"}

        class service:
            name = "Maths 1:1"

    with tenant_context(org):
        services.notify("booking_declined", (Hold(), "declined"), key="hold-1")
    (sent,) = messages(org, type_key="booking_declined")
    assert sent.to == "lee@example.com"
    assert "Maths 1:1" in sent.body


# --- 13. push for tutor messages (FR-16-9) ------------------------------------------------------


def test_conversation_messages_push_by_default():
    for key in ("conversation_message_tutor", "conversation_message_family", "inbox_new_message"):
        assert key in registry.PUSH_BY_DEFAULT
        assert "push" in registry.get(key).default_channels


def test_digest_preferences_are_exported_and_erased(org, family):  # noqa: F811
    from tutortrack.comms import privacy as comms_privacy

    with tenant_context(org):
        DigestPreference.objects.create(
            person_type="contact",
            person_id=str(family["contact"].pk),
            kind="weekly_schedule",
            enabled=False,
        )

        class Person:
            emails: set[str] = set()
            phones: set[str] = set()

            def of(self, subject_type):
                return [str(family["contact"].pk)] if subject_type == "people.contact" else []

        sections = {s.key: s for s in comms_privacy.export(Person())}
        assert sections["comms.digests"].records[0]["kind"] == "weekly_schedule"
