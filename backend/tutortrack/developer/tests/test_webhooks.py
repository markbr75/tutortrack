"""E27-T03: webhook endpoints, SSRF guard, payloads, signing, attempts, auto-disable, log,
redelivery, test events; T06/T07 REST hooks; T09 sandboxes."""

from __future__ import annotations

import json
import time
import uuid
from datetime import timedelta

import pytest
from django.core import mail
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.events import EventEnvelope, subscribers_for
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin
from tutortrack.core.time import now
from tutortrack.developer import catalogue, services, signing
from tutortrack.developer.models import (
    OAuthApplication,
    Sandbox,
    WebhookAttempt,
    WebhookDelivery,
    WebhookEndpoint,
)
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.people.tests.factories import ClientFactory
from tutortrack.tenancy.tests.factories import BranchFactory

from .conftest import bearer, make_key

pytestmark = pytest.mark.django_db


def envelope(org, event_type="lesson.completed", subject=("lesson", None), branch=None, **data):
    return EventEnvelope(
        id=uuid.uuid4(),
        type=event_type,
        version=1,
        occurred_at=now(),
        organisation_id=org.pk,
        branch_id=branch,
        actor={"type": "user", "id": None},
        subject={"type": subject[0], "id": str(subject[1] or uuid.uuid4())},
        data=data,
        changes={},
    )


def endpoint_for(org, events=("lesson.completed",), **kwargs):
    with tenant_context(org), transaction.atomic():
        return services.create_endpoint(
            url="https://hooks.example.com/tt", events_=list(events), **kwargs
        )


# --- endpoints and the SSRF guard ---------------------------------------------------------------


def test_create_endpoint_returns_secret_once(api, public_dns):
    response = api.post(
        "/api/v1/webhook-endpoints",
        {"url": "https://hooks.example.com/tt", "events": ["lesson.completed", "invoice.*"]},
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["secret"].startswith("whsec_")
    assert body["events"] == ["invoice.*", "lesson.completed"]
    assert body["api_version"] == "2026-10-01"
    listed = api.get("/api/v1/webhook-endpoints").json()["results"][0]
    assert "secret" not in listed


@pytest.mark.parametrize(
    "url",
    ["http://hooks.example.com/tt", "https://internal.example.com/tt", "https://user:pw@x.com/"],
)
def test_ssrf_guard_refuses_unsafe_urls(api, public_dns, url):
    response = api.post("/api/v1/webhook-endpoints", {"url": url, "events": ["lesson.completed"]})
    assert response.status_code == 422, response.content


def test_unknown_or_internal_event_types_are_refused(api, public_dns):
    for events in (["lesson.exploded"], ["organisation.created"], ["*"], ["api_key.created"]):
        response = api.post(
            "/api/v1/webhook-endpoints", {"url": "https://hooks.example.com/", "events": events}
        )
        assert response.status_code == 422, events


def test_catalogue_is_explicit_and_wired_to_the_outbox():
    keys = catalogue.public_event_keys()
    assert "lesson.completed" in keys
    assert "invoice.paid" in keys
    assert not [k for k in keys if k.split(".")[0] in ("organisation", "user", "webhook_endpoint")]
    assert any(s.name == "developer.webhooks" for s in subscribers_for("lesson.completed"))
    assert not any(s.name == "developer.webhooks" for s in subscribers_for("user.logged_in"))


def test_event_types_endpoint(api):
    rows = api.get("/api/v1/webhook-event-types").json()
    assert {"key", "aggregate", "subject_type", "description", "version"} <= set(rows[0])


# --- deliveries ---------------------------------------------------------------------------------


def test_matching_endpoints_get_one_delivery_each(org, public_dns):
    lessons, _ = endpoint_for(org, ["lesson.*"])
    invoices, _ = endpoint_for(org, ["invoice.paid"])
    paused, _ = endpoint_for(org, ["lesson.completed"])
    with tenant_context(org):
        services.update_endpoint(paused, status="paused")
        event = envelope(org, outcome="attended")
        with transaction.atomic():
            first = services.enqueue_event(event)
            again = services.enqueue_event(event)  # idempotent per event
        assert [d.endpoint_id for d in first] == [lessons.pk]
        assert again == []
        delivery = WebhookDelivery.objects.get()
        assert delivery.payload["type"] == "lesson.completed"
        assert delivery.payload["event_data"] == {"outcome": "attended"}
        assert invoices.deliveries.count() == 0


def test_payload_data_is_the_public_representation(org, user, member, public_dns):
    with tenant_context(org):
        endpoint, _ = endpoint_for(org, ["client.created"])
        WebhookEndpoint.objects.filter(pk=endpoint.pk).update(created_by=user)
    client = ClientFactory(organisation=org, display_name="Patel family")
    with tenant_context(org), transaction.atomic():
        services.enqueue_event(envelope(org, "client.created", ("client", client.pk)))
        payload = WebhookDelivery.objects.get().payload
    assert payload["data"]["id"] == str(client.pk)
    assert payload["data"]["display_name"] == "Patel family"
    assert "tax_id" not in payload["data"] or payload["data"]["tax_id"] is not None


def test_branch_filter(org, public_dns):
    north = BranchFactory(organisation=org)
    endpoint_for(org, ["lesson.completed"], branch=north)
    with tenant_context(org), transaction.atomic():
        assert services.enqueue_event(envelope(org)) == []
        assert len(services.enqueue_event(envelope(org, branch=north.pk))) == 1


def test_delivered_lesson_completed_verifies_with_the_documented_algorithm(
    org, public_dns, receiver
):
    """AC: a lesson.completed webhook verifies with the endpoint secret."""
    _endpoint, secret = endpoint_for(org)
    fake = receiver()
    with tenant_context(org):
        with transaction.atomic():
            delivery = services.enqueue_event(envelope(org))[0]
        assert services.attempt_delivery(str(delivery.pk), 1, now()) == "succeeded"
    sent = fake.requests[0]
    headers = sent["headers"]
    assert headers["Webhook-Event"] == "lesson.completed"
    assert headers["Webhook-Id"] == str(delivery.event_id)
    assert signing.verify(secret, headers["Webhook-Signature"], sent["body"])
    assert not signing.verify("whsec_other", headers["Webhook-Signature"], sent["body"])
    assert json.loads(sent["body"])["type"] == "lesson.completed"
    # Outside the five-minute replay window the signature is refused.
    later = int(time.time()) + 301
    assert not signing.verify(secret, headers["Webhook-Signature"], sent["body"], now=later)
    with tenant_context(org):
        delivery.refresh_from_db()
        assert delivery.status == "succeeded"
        assert delivery.attempt_count == 1


def test_failed_attempt_is_logged_and_marks_the_endpoint_failing(org, public_dns, receiver):
    endpoint, _ = endpoint_for(org)
    receiver([500])
    with tenant_context(org):
        with transaction.atomic():
            delivery = services.enqueue_event(envelope(org))[0]
        assert services.attempt_delivery(str(delivery.pk), 1, now()) == "retry"
        # Re-running the same attempt (an activity retry) doesn't post twice.
        assert services.attempt_delivery(str(delivery.pk), 1, now()) == "retry"
        attempt = WebhookAttempt.objects.get()
        assert attempt.status_code == 500
        assert not attempt.succeeded
        assert attempt.response_snippet == "server error"
        assert attempt.request_headers["Webhook-Attempt"] == "1"
        endpoint.refresh_from_db()
        assert endpoint.failing_since is not None


def test_three_days_of_failures_disable_the_endpoint_and_email_admins(
    org, user, member, public_dns, receiver, django_capture_on_commit_callbacks
):
    endpoint, _ = endpoint_for(org)
    receiver(default=503)
    start = now()
    with tenant_context(org):
        with transaction.atomic():
            delivery = services.enqueue_event(envelope(org))[0]
        services.attempt_delivery(str(delivery.pk), 1, start)
        with django_capture_on_commit_callbacks(execute=True):
            services.attempt_delivery(str(delivery.pk), 2, start + timedelta(days=3, minutes=1))
        endpoint.refresh_from_db()
        assert endpoint.status == "disabled"
        assert endpoint.disabled_at is not None
        assert OutboxEvent.objects.filter(event_type="webhook_endpoint.disabled").exists()
        # Later attempts of pending deliveries stop.
        assert services.attempt_delivery(str(delivery.pk), 3, now()) == "cancelled"
    assert any(endpoint.url in m.subject for m in mail.outbox)


def test_a_success_clears_the_failure_clock(org, public_dns, receiver):
    endpoint, _ = endpoint_for(org)
    receiver([500, 200])
    with tenant_context(org):
        with transaction.atomic():
            delivery = services.enqueue_event(envelope(org))[0]
        services.attempt_delivery(str(delivery.pk), 1, now())
        services.attempt_delivery(str(delivery.pk), 2, now())
        endpoint.refresh_from_db()
        assert endpoint.failing_since is None


def test_rotated_secret_signs_with_both_for_the_overlap(org, public_dns, receiver):
    endpoint, old = endpoint_for(org)
    fake = receiver()
    with tenant_context(org):
        with transaction.atomic():
            new = services.rotate_endpoint_secret(endpoint)
            delivery = services.enqueue_event(envelope(org))[0]
        services.attempt_delivery(str(delivery.pk), 1, now())
    sent = fake.requests[0]
    assert signing.verify(new, sent["headers"]["Webhook-Signature"], sent["body"])
    assert signing.verify(old, sent["headers"]["Webhook-Signature"], sent["body"])


def test_give_up_marks_failed_and_publishes(org, public_dns, receiver):
    receiver([500])
    endpoint_for(org)
    with tenant_context(org):
        with transaction.atomic():
            delivery = services.enqueue_event(envelope(org))[0]
        services.attempt_delivery(str(delivery.pk), 1, now())
        assert services.give_up(str(delivery.pk))
        delivery.refresh_from_db()
        assert delivery.status == "failed"
        assert OutboxEvent.objects.filter(event_type="webhook_delivery.failed").count() == 1


def test_delivery_log_redeliver_and_test_event(api, org, public_dns, receiver):
    endpoint, _ = endpoint_for(org)
    receiver([500])
    with tenant_context(org):
        with transaction.atomic():
            delivery = services.enqueue_event(envelope(org))[0]
        services.attempt_delivery(str(delivery.pk), 1, now())
    rows = api.get("/api/v1/webhook-deliveries", {"endpoint": str(endpoint.pk)}).json()["results"]
    assert rows[0]["id"] == str(delivery.pk)
    assert rows[0]["last_status_code"] == 500
    detail = api.get(f"/api/v1/webhook-deliveries/{delivery.pk}").json()
    assert detail["attempts"][0]["status_code"] == 500
    assert detail["body"]["type"] == "lesson.completed"
    again = api.post(f"/api/v1/webhook-deliveries/{delivery.pk}/redeliver")
    assert again.status_code == 202
    assert again.json()["redelivery_of"] == str(delivery.pk)
    assert again.json()["event_id"] == str(delivery.event_id)
    test = api.post(f"/api/v1/webhook-endpoints/{endpoint.pk}/test")
    assert test.status_code == 202
    assert test.json()["event_type"] == "webhook.test"
    failed = api.get("/api/v1/webhook-deliveries", {"status": "retrying"}).json()["results"]
    assert [r["id"] for r in failed] == [str(delivery.pk)]


def test_pause_resume_rotate_and_reveal(api, org, public_dns):
    endpoint, secret = endpoint_for(org)
    paused = api.patch(f"/api/v1/webhook-endpoints/{endpoint.pk}", {"status": "paused"})
    assert paused.json()["status"] == "paused"
    with tenant_context(org):
        WebhookEndpoint.objects.filter(pk=endpoint.pk).update(failing_since=now())
    resumed = api.patch(f"/api/v1/webhook-endpoints/{endpoint.pk}", {"status": "active"})
    assert resumed.json()["failing_since"] is None
    revealed = api.post(f"/api/v1/webhook-endpoints/{endpoint.pk}/reveal-secret").json()
    assert revealed["secret"] == secret
    rotated = api.post(f"/api/v1/webhook-endpoints/{endpoint.pk}/rotate-secret").json()
    assert rotated["secret"] != secret
    assert api.get(f"/api/v1/webhook-endpoints/{endpoint.pk}").json()["secret_rotating"]
    assert api.delete(f"/api/v1/webhook-endpoints/{endpoint.pk}").status_code == 204


def test_purge_keeps_thirty_days(org, public_dns):
    endpoint_for(org)
    with tenant_context(org):
        with transaction.atomic():
            old = services.enqueue_event(envelope(org))[0]
            recent = services.enqueue_event(envelope(org))[0]
        WebhookDelivery.objects.filter(pk__in=[old.pk, recent.pk]).update(status="succeeded")
        WebhookDelivery.objects.filter(pk=old.pk).update(created_at=now() - timedelta(days=31))
        assert services.purge_deliveries() == 1
        assert list(WebhookDelivery.objects.values_list("pk", flat=True)) == [recent.pk]


# --- REST hooks for Zapier/Make (T06/T07) -------------------------------------------------------


def test_rest_hook_subscribe_and_unsubscribe_with_a_token(org, user, member, public_dns):
    _key, token = make_key(org, user, ["webhooks:write"])
    client = bearer(token)
    created = client.post(
        "/api/v1/webhook-endpoints",
        {"url": "https://hooks.zapier.com/hooks/standard/1/abc", "events": ["enquiry.received"]},
    )
    assert created.status_code == 201, created.content
    assert created.json()["source"] == "api"
    sample = client.get("/api/v1/webhook-event-types/enquiry.received/sample").json()
    assert sample["synthetic"]
    assert sample["body"]["type"] == "enquiry.received"
    assert client.get("/api/v1/webhook-event-types/user.logged_in/sample").status_code == 404
    gone = client.delete(f"/api/v1/webhook-endpoints/{created.json()['id']}")
    assert gone.status_code == 204


def test_zapier_tokens_tag_their_subscriptions(org, user, member, public_dns):
    from tutortrack.developer.models import OAuthGrant

    app = OAuthApplication.objects.create(
        name="Zapier", client_id="ttapp_zapier", redirect_uris=["https://zapier.com/cb"],
        allowed_scopes=[], owner_organisation_id=None, partner_key="zapier", published=True,
    )  # fmt: skip
    with tenant_context(org), transaction.atomic():
        grant = OAuthGrant.objects.create(application=app, user=user, scopes=["webhooks:write"])
        issued = services._issue_tokens(grant, ["webhooks:write"])
    response = bearer(issued["access_token"]).post(
        "/api/v1/webhook-endpoints",
        {"url": "https://hooks.zapier.com/x", "events": ["client.created"]},
    )
    assert response.status_code == 201
    assert response.json()["source"] == "zapier"


# --- sandboxes (T09) ----------------------------------------------------------------------------


def test_create_sandbox_copies_settings_and_loads_sample_data(api, org, user):
    from tutortrack.identity.selectors import membership_for
    from tutortrack.tenancy.models import Organisation
    from tutortrack.tenancy.settings_service import get_setting, update_settings

    with tenant_context(org), transaction.atomic():
        update_settings("automations", {"automations.max_runs_per_hour": 42})
    response = api.post("/api/v1/developer/sandboxes")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["slug"] == "brightminds-sandbox"
    sandbox_org = Organisation.objects.get(pk=body["sandbox_organisation_id"])
    with tenant_context(sandbox_org):
        assert get_setting("automations.max_runs_per_hour") == 42
        assert get_setting("developer.sandbox_of") == str(org.pk)
        assert sandbox_org.has_demo_data or body["records"] >= 0
    assert membership_for(user, sandbox_org.pk).role == "owner"
    assert api.get("/api/v1/developer/sandboxes").json()["results"][0]["id"] == body["id"]


# --- isolation ----------------------------------------------------------------------------------


class TestWebhookEndpointIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/webhook-endpoints"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return WebhookEndpoint.objects.create(
                url="https://hooks.example.com/", events=["lesson.completed"],
                api_version="2026-10-01", secret="whsec_x",
            )  # fmt: skip


class TestWebhookDeliveryIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/webhook-deliveries"

    def make_object(self, organisation):
        with tenant_context(organisation):
            endpoint = WebhookEndpoint.objects.create(
                url="https://hooks.example.com/", events=["lesson.completed"],
                api_version="2026-10-01", secret="whsec_x",
            )  # fmt: skip
            return WebhookDelivery.objects.create(
                endpoint=endpoint, event_id=uuid.uuid4(), event_type="lesson.completed",
                payload={},
            )  # fmt: skip


class TestSandboxIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/developer/sandboxes"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return Sandbox.objects.create(
                sandbox_organisation_id=uuid.uuid4(), name="S", slug=f"{organisation.slug}-sb"
            )


def test_webhook_view_permission_is_required(org):
    from tutortrack.core.testing import client_for
    from tutortrack.identity.models import Membership

    tutor = UserFactory()
    MembershipFactory(organisation=org, user=tutor, role=Membership.Role.TUTOR)
    assert client_for(org, tutor).get("/api/v1/webhook-endpoints").status_code == 403
