"""E16-T09: Web Push subscriptions, the push channel in the notification pipeline, VAPID
signing and encryption, expired devices, and the tutor's own channel preferences."""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import timedelta

import http_ece
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.db import connection

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.comms import channels, registry, services
from tutortrack.comms.management.commands.generate_vapid_keys import generate
from tutortrack.comms.models import Message, PushSubscription
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)
from tutortrack.scheduling import services as scheduling

pytestmark = pytest.mark.django_db

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123:secret-token"


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Browser:
    """A browser's push keys (what ``PushSubscription.toJSON()`` sends)."""

    def __init__(self, endpoint: str = ENDPOINT) -> None:
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.endpoint = endpoint
        public = self.private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        self.json = {"endpoint": endpoint, "keys": {"p256dh": b64(public), "auth": b64(self.auth)}}

    def decrypt(self, body: bytes) -> dict:
        plain = http_ece.decrypt(body, private_key=self.private, auth_secret=self.auth)
        return json.loads(plain)


@pytest.fixture(autouse=True)
def fake_push():
    channels.push_provider.cache_clear()
    provider = channels.push_provider()
    yield provider
    channels.push_provider.cache_clear()


@pytest.fixture
def tutor(org):
    membership = MembershipFactory(organisation=org, role="tutor")
    profile = TutorProfileFactory(
        organisation=org, status="active", first_name="Nia", email="nia@example.com",
        membership=membership,
    )  # fmt: skip
    return {"profile": profile, "user": membership.user, "api": client_for(org, membership.user)}


def subscribe(api, browser=None, **extra):
    browser = browser or Browser()
    return api.post("/api/v1/push-subscriptions", {**browser.json, **extra}, format="json")


def moved_lesson(org, tutor):
    client = ClientFactory(organisation=org)
    ContactFactory(organisation=org, client=client, email="p@example.com", is_primary=True)
    student = StudentFactory(organisation=org, client=client)
    service = ServiceFactory(organisation=org)
    start = (now() + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    with tenant_context(org):
        return scheduling.create_lesson(
            start=start, end=start + timedelta(hours=1), service=service,
            attendees=[{"student": student}], tutors=[{"tutor": tutor["profile"]}],
            timezone="Europe/London", override_conflicts=True,
        ).lesson  # fmt: skip


# --- subscriptions --------------------------------------------------------------------------


def test_subscribe_stores_the_endpoint_and_keys_encrypted(org, tutor):
    browser = Browser()
    response = subscribe(tutor["api"], browser, device="Pixel 8")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["push_service"] == "fcm.googleapis.com"
    assert body["device"] == "Pixel 8"
    assert "endpoint" not in body
    assert "keys" not in body
    with tenant_context(org):
        with connection.cursor() as cursor:
            cursor.execute("SELECT endpoint, p256dh, auth FROM comms_pushsubscription")
            stored = cursor.fetchone()
        assert ENDPOINT not in stored[0]
        assert browser.json["keys"]["p256dh"] != stored[1]
        row = PushSubscription.objects.get()
        assert (row.endpoint, row.user_id) == (ENDPOINT, tutor["user"].pk)
        event = OutboxEvent.objects.get(event_type="push_subscription.added")
    assert ENDPOINT not in json.dumps(event.payload)


def test_subscribing_again_refreshes_the_same_device(org, tutor):
    first = subscribe(tutor["api"]).json()
    second = subscribe(tutor["api"]).json()  # new keys, same endpoint
    assert first["id"] == second["id"]
    with tenant_context(org):
        assert PushSubscription.objects.count() == 1
        assert OutboxEvent.objects.filter(event_type="push_subscription.added").count() == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/x",  # not https
        "https://evil.example.com/push",  # not a push service
        "https://fcm.googleapis.com:8443/x",  # odd port
        "https://user:pw@fcm.googleapis.com/x",
    ],
)
def test_only_known_push_services_are_accepted(tutor, endpoint):
    response = subscribe(tutor["api"], Browser(endpoint))
    assert response.status_code in {400, 422}, response.content


def test_invalid_browser_keys_are_rejected(tutor):
    browser = Browser()
    browser.json["keys"]["p256dh"] = b64(b"short")
    assert subscribe(tutor["api"], browser).status_code in {400, 422}


def test_people_only_see_and_remove_their_own_devices(org, tutor):
    mine = subscribe(tutor["api"]).json()
    other = MembershipFactory(organisation=org, role="tutor").user
    other_api = client_for(org, other)
    assert other_api.get("/api/v1/push-subscriptions").json()["results"] == []
    assert other_api.get(f"/api/v1/push-subscriptions/{mine['id']}").status_code == 404
    assert other_api.delete(f"/api/v1/push-subscriptions/{mine['id']}").status_code == 404
    assert tutor["api"].delete(f"/api/v1/push-subscriptions/{mine['id']}").status_code == 204
    with tenant_context(org):
        assert not PushSubscription.objects.exists()
        removed = OutboxEvent.objects.get(event_type="push_subscription.removed")
    assert removed.payload["data"]["reason"] == "removed"


class TestPushSubscriptionIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/push-subscriptions"
    user = None

    def acting_user(self, organisation):
        if TestPushSubscriptionIsolation.user is None:
            TestPushSubscriptionIsolation.user = UserFactory(is_superuser=True)
        return TestPushSubscriptionIsolation.user

    def make_object(self, organisation):
        browser = Browser(f"https://fcm.googleapis.com/fcm/send/{organisation.pk}")
        with tenant_context(organisation):
            return services.subscribe_push(
                self.acting_user(organisation), endpoint=browser.endpoint,
                p256dh=browser.json["keys"]["p256dh"], auth=browser.json["keys"]["auth"],
            )  # fmt: skip

    @pytest.fixture(autouse=True)
    def _fresh_user(self):
        TestPushSubscriptionIsolation.user = None
        yield
        TestPushSubscriptionIsolation.user = None


def test_config_gives_the_vapid_public_key(tutor, settings):
    settings.WEB_PUSH = {**settings.WEB_PUSH, "VAPID_PUBLIC_KEY": ""}
    assert tutor["api"].get("/api/v1/push-subscriptions/config").json()["enabled"] is False
    public, _private = generate()
    settings.WEB_PUSH = {**settings.WEB_PUSH, "VAPID_PUBLIC_KEY": public}
    config = tutor["api"].get("/api/v1/push-subscriptions/config").json()
    assert config == {"enabled": True, "vapid_public_key": public}


def test_test_push_reaches_each_device(tutor, fake_push):
    assert tutor["api"].post("/api/v1/push-subscriptions/test").status_code in {400, 422}
    subscribe(tutor["api"])
    response = tutor["api"].post("/api/v1/push-subscriptions/test")
    assert response.json() == {"delivered": 1}
    assert fake_push.outbox[0]["payload"]["title"] == "Notifications are on"


# --- the push channel -------------------------------------------------------------------------


def test_push_is_a_channel_wherever_in_app_is():
    lesson_changed = registry.get("lesson_changed")
    assert "push" in lesson_changed.channels
    assert "push" in lesson_changed.default_channels
    assert "push" in registry.get("task_assigned").channels
    assert "push" not in registry.get("task_assigned").default_channels
    assert "push" not in registry.get("invoice_issued").channels  # email-only stays so
    assert "push" in registry.get("payout_paid").default_channels


def test_lesson_change_pushes_to_the_tutors_phone(org, tutor, fake_push):
    subscribe(tutor["api"])
    lesson = moved_lesson(org, tutor)
    with tenant_context(org):
        messages = services.notify("lesson_changed", lesson, key="move-1", immediate=True)
        push = [m for m in messages if m.channel == "push"]
        assert len(push) == 1
        assert push[0].status == Message.Status.SENT
        # The same occurrence never pushes twice.
        again = services.notify("lesson_changed", lesson, key="move-1", immediate=True)
        assert not [m for m in again if m.channel == "push"]
    assert len(fake_push.outbox) == 1
    sent = fake_push.outbox[0]
    assert sent["payload"]["url"] == f"/portal/tutor/lessons/{lesson.pk}"
    assert sent["payload"]["title"] == "Lesson moved"
    assert sent["urgency"] == "high"
    assert len(sent["topic"]) == 32


def test_nobody_without_a_device_gets_a_push_message(org, tutor, fake_push):
    lesson = moved_lesson(org, tutor)
    with tenant_context(org):
        messages = services.notify("lesson_changed", lesson, key="move-2", immediate=True)
    assert "push" not in {m.channel for m in messages}
    assert fake_push.outbox == []


def test_expired_devices_are_forgotten(org, tutor, fake_push):
    subscribe(tutor["api"])
    fake_push.gone.add(ENDPOINT)
    lesson = moved_lesson(org, tutor)
    with tenant_context(org):
        messages = services.notify("lesson_changed", lesson, key="move-3", immediate=True)
        push = next(m for m in messages if m.channel == "push")
        assert push.status == Message.Status.FAILED
        assert ENDPOINT not in push.error
        assert not PushSubscription.objects.exists()
        removed = OutboxEvent.objects.get(event_type="push_subscription.removed")
    assert removed.payload["data"]["reason"] == "expired"


def test_tutor_can_turn_push_off_per_category(org, tutor, fake_push):
    subscribe(tutor["api"])
    mine = tutor["api"].get("/api/v1/communication-preferences/mine").json()["preferences"]
    scheduling_row = next(r for r in mine if r["category"] == "scheduling")
    assert "push" in scheduling_row["available"]
    assert "push" in scheduling_row["channels"]
    response = tutor["api"].put(
        "/api/v1/communication-preferences/mine",
        {"preferences": [{"category": "scheduling", "channels": ["email", "in_app"]}]},
        format="json",
    )
    assert response.status_code == 200, response.content
    row = next(r for r in response.json()["preferences"] if r["category"] == "scheduling")
    assert row["channels"] == ["email", "in_app"]
    lesson = moved_lesson(org, tutor)
    with tenant_context(org):
        messages = services.notify("lesson_changed", lesson, key="move-4", immediate=True)
    assert "push" not in {m.channel for m in messages}
    bad = tutor["api"].put(
        "/api/v1/communication-preferences/mine",
        {"preferences": [{"category": "staff", "channels": ["push"]}]},
        format="json",
    )
    assert bad.status_code in {400, 422}


def test_pay_sent_pushes_to_the_tutor(org, tutor, fake_push):
    from django.test import TestCase

    from tutortrack.comms import handlers
    from tutortrack.core.events import EventEnvelope, publish
    from tutortrack.core.money import Money
    from tutortrack.payroll.events import PayoutPaid
    from tutortrack.payroll.models import Payout, PayRun

    subscribe(tutor["api"])
    today = now().date()
    with tenant_context(org):
        run = PayRun.objects.create(number="PR-1", period_start=today, period_end=today)
        payout = Payout.objects.create(
            pay_run=run, tutor=tutor["profile"], currency="GBP", amount=Money("240.00", "GBP"),
            method="manual", status="paid", reference="PAY-0042",
        )  # fmt: skip
        with TestCase.captureOnCommitCallbacks(execute=True):
            from django.db import transaction

            with transaction.atomic():
                publish(PayoutPaid(subject_id=payout.pk, tutor_id=str(payout.tutor_id),
                                   pay_run_id=str(run.pk),
                                   amount={"amount": "240.00", "currency": "GBP"}))  # fmt: skip
            row = OutboxEvent.objects.get(event_type="payout.paid")
            handlers.payout_paid(EventEnvelope.from_payload(row.payload))
    pushed = [p["payload"] for p in fake_push.outbox]
    assert pushed[0]["title"] == "You've been paid"
    assert "240.00" in pushed[0]["body"]
    assert pushed[0]["url"] == "/portal/tutor/earnings"


def test_push_uses_the_in_app_wording_by_default(org):
    with tenant_context(org):
        subject, body = services.preview("payout_paid", "push")
    assert subject == "You've been paid"
    assert "240" in body


# --- the real sender: VAPID + aes128gcm through safe_urlopen ------------------------------------


class _Response:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_web_push_encrypts_signs_and_posts_safely(settings, monkeypatch):
    public, private = generate()
    settings.WEB_PUSH = {**settings.WEB_PUSH, "VAPID_PUBLIC_KEY": public,
                         "VAPID_PRIVATE_KEY": private}  # fmt: skip
    channels.push_provider.cache_clear()
    sent = {}

    def fake_urlopen(url, *, data, headers, method, timeout):
        sent.update(url=url, data=data, headers=headers, method=method)
        return _Response()

    monkeypatch.setattr("tutortrack.core.net.safe_urlopen", fake_urlopen)
    browser = Browser()
    provider = channels.push_provider()
    assert isinstance(provider, channels.WebPush)
    target = channels.PushTarget(ENDPOINT, **browser.json["keys"])
    result = provider.send(target, b'{"title": "Hi"}', ttl=60, urgency="high", topic="t1")
    assert result.ok
    assert sent["method"] == "POST"
    assert sent["url"] == ENDPOINT
    assert sent["headers"]["Content-Encoding"] == "aes128gcm"
    assert sent["headers"]["TTL"] == "60"
    assert sent["headers"]["Urgency"] == "high"
    assert sent["headers"]["Authorization"].startswith("vapid t=")
    assert f"k={public}" in sent["headers"]["Authorization"]
    assert browser.decrypt(sent["data"]) == {"title": "Hi"}


def test_web_push_refuses_unknown_hosts_without_leaking_the_url(settings, monkeypatch):
    _public, private = generate()
    settings.WEB_PUSH = {**settings.WEB_PUSH, "VAPID_PRIVATE_KEY": private}
    channels.push_provider.cache_clear()
    monkeypatch.setattr(
        "tutortrack.core.net.safe_urlopen", lambda *a, **k: pytest.fail("must not connect")
    )
    secret = "https://169.254.169.254/latest/meta-data?token=s3cret"
    target = channels.PushTarget(secret, **Browser().json["keys"])
    with pytest.raises(channels.ChannelError) as exc:
        channels.push_provider().send(target, b"{}", ttl=1, urgency="normal", topic="")
    assert "s3cret" not in str(exc.value)
    assert "169.254" not in str(exc.value)


def test_endpoints_are_never_logged(org, tutor, fake_push, caplog):
    caplog.set_level(logging.DEBUG)
    subscribe(tutor["api"])
    lesson = moved_lesson(org, tutor)
    with tenant_context(org):
        services.notify("lesson_changed", lesson, key="move-5", immediate=True)
    assert "secret-token" not in caplog.text
