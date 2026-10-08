from datetime import timedelta
from unittest import mock

import pytest

from tutortrack.core.models import IdempotencyRecord
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now

from .factories import GadgetFactory, WidgetFactory
from .testapp import api as testapp_api

pytestmark = pytest.mark.django_db

WIDGETS = "/api/v1/test/widgets"


# --- problem details ----------------------------------------------------------------------------


def test_validation_errors_are_problem_details(api):
    response = api.post(WIDGETS, {"price": {"amount": "1", "currency": "GBP"}}, format="json")
    assert response.status_code == 400
    assert response["Content-Type"] == "application/problem+json"
    body = response.json()
    assert body["type"].endswith("/validation-error")
    assert body["status"] == 400
    assert "name" in body["errors"]
    assert body["request_id"] == response["X-Request-ID"]


def test_domain_errors_map_to_problem_details(api):
    response = api.get("/api/v1/test/domain-error")
    assert response.status_code == 422
    body = response.json()
    assert body["type"].endswith("/business-rule-violation")
    assert body["detail"] == "Lessons cannot overlap."
    assert body["code"] == "overlap"


def test_not_found_is_problem_details(api):
    response = api.get(f"{WIDGETS}/00000000-0000-7000-8000-000000000000")
    assert response.status_code == 404
    assert response["Content-Type"] == "application/problem+json"


def test_unauthenticated_is_problem_details(org):
    response = client_for(org).get(WIDGETS)
    assert response.status_code == 403
    assert response.json()["type"].endswith("/not-authenticated")


# --- request id ---------------------------------------------------------------------------------


def test_request_id_is_generated_or_propagated(api):
    generated = api.get(WIDGETS)["X-Request-ID"]
    assert len(generated) == 32
    assert api.get(WIDGETS, HTTP_X_REQUEST_ID="trace-abc-123")["X-Request-ID"] == "trace-abc-123"
    assert api.get(WIDGETS, HTTP_X_REQUEST_ID="bad id!")["X-Request-ID"] != "bad id!"


# --- pagination, sparse fields, expansion -------------------------------------------------------


def test_cursor_pagination_newest_first(api, org):
    widgets = [WidgetFactory(organisation=org) for _ in range(5)]
    first = api.get(WIDGETS, {"page_size": 2}).json()
    assert [r["id"] for r in first["results"]] == [str(w.pk) for w in widgets[::-1][:2]]
    assert first["next"]
    second = api.get(first["next"]).json()
    assert [r["id"] for r in second["results"]] == [str(w.pk) for w in widgets[::-1][2:4]]


def test_page_size_is_capped(api, org):
    for _ in range(3):
        WidgetFactory(organisation=org)
    assert len(api.get(WIDGETS, {"page_size": 5000}).json()["results"]) == 3


def test_sparse_fields(api, org):
    WidgetFactory(organisation=org)
    row = api.get(WIDGETS, {"fields": "name"}).json()["results"][0]
    assert set(row) == {"id", "name"}


def test_expand(api, org):
    gadget = GadgetFactory(organisation=org, name="Projector")
    widget = WidgetFactory(organisation=org, gadget=gadget)
    plain = api.get(f"{WIDGETS}/{widget.pk}").json()
    assert plain["gadget"] == str(gadget.pk)
    expanded = api.get(f"{WIDGETS}/{widget.pk}", {"expand": "gadget"}).json()
    assert expanded["gadget"] == {"id": str(gadget.pk), "name": "Projector"}


def test_money_fields_serialize_as_objects(api):
    response = api.post(
        WIDGETS,
        {"name": "Maths", "price": {"amount": "40.00", "currency": "GBP"}},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["price"] == {"amount": "40.00", "currency": "GBP"}


# --- ETag / If-Match ----------------------------------------------------------------------------


def test_etag_prevents_lost_updates(api, org):
    widget = WidgetFactory(organisation=org, name="v1")
    etag = api.get(f"{WIDGETS}/{widget.pk}")["ETag"]
    assert etag.startswith('W/"')

    ok = api.patch(f"{WIDGETS}/{widget.pk}", {"name": "v2"}, format="json", HTTP_IF_MATCH=etag)
    assert ok.status_code == 200
    assert ok["ETag"] != etag

    stale = api.patch(f"{WIDGETS}/{widget.pk}", {"name": "v3"}, format="json", HTTP_IF_MATCH=etag)
    assert stale.status_code == 412
    assert stale.json()["type"].endswith("/precondition-failed")


def test_if_match_required_when_configured(api, org, monkeypatch):
    monkeypatch.setattr(testapp_api.WidgetViewSet, "require_if_match", True)
    widget = WidgetFactory(organisation=org)
    response = api.patch(f"{WIDGETS}/{widget.pk}", {"name": "x"}, format="json")
    assert response.status_code == 428


# --- idempotency --------------------------------------------------------------------------------


@pytest.fixture
def reset_calls():
    testapp_api.CALLS["count"] = 0


ECHO = "/api/v1/test/echo"


def test_idempotent_replay_returns_stored_response_without_rerunning(api, reset_calls):
    first = api.post(ECHO, {"value": 7}, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    second = api.post(ECHO, {"value": 7}, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json() == {"value": 7, "call": 1}
    assert second["Idempotent-Replayed"] == "true"
    assert testapp_api.CALLS["count"] == 1


def test_reusing_a_key_with_a_different_body_is_rejected(api, reset_calls):
    api.post(ECHO, {"value": 1}, format="json", HTTP_IDEMPOTENCY_KEY="k2")
    response = api.post(ECHO, {"value": 2}, format="json", HTTP_IDEMPOTENCY_KEY="k2")
    assert response.status_code == 422
    assert response.json()["type"] == "idempotency-key-reused"


def test_in_progress_key_returns_conflict(api, user, org, reset_calls):
    from tutortrack.core.idempotency import _request_hash  # noqa: F401 - documents the hash

    IdempotencyRecord.objects.create(
        organisation_id=org.pk,
        principal=f"user:{user.pk}",
        key="k3",
        request_hash="whatever",
        expires_at=now() + timedelta(hours=1),
    )
    with mock.patch("tutortrack.core.idempotency._request_hash", return_value="whatever"):
        response = api.post(ECHO, {"value": 1}, format="json", HTTP_IDEMPOTENCY_KEY="k3")
    assert response.status_code == 409


def test_server_errors_are_not_stored(api, reset_calls):
    api.post(f"{ECHO}?status=503", {"value": 1}, format="json", HTTP_IDEMPOTENCY_KEY="k4")
    retry = api.post(f"{ECHO}?status=503", {"value": 1}, format="json", HTTP_IDEMPOTENCY_KEY="k4")
    assert testapp_api.CALLS["count"] == 2
    assert "Idempotent-Replayed" not in retry


def test_keys_are_scoped_per_user(org, reset_calls):
    from tutortrack.identity.tests.factories import UserFactory

    a, b = client_for(org, UserFactory()), client_for(org, UserFactory())
    a.post(ECHO, {"value": 1}, format="json", HTTP_IDEMPOTENCY_KEY="same")
    b.post(ECHO, {"value": 1}, format="json", HTTP_IDEMPOTENCY_KEY="same")
    assert testapp_api.CALLS["count"] == 2


def test_expired_records_are_purged(org, user):
    from tutortrack.core.tasks import purge_expired_idempotency_records

    IdempotencyRecord.objects.create(
        principal="p", key="old", request_hash="h", expires_at=now() - timedelta(seconds=1)
    )
    IdempotencyRecord.objects.create(
        principal="p", key="new", request_hash="h", expires_at=now() + timedelta(hours=1)
    )
    assert purge_expired_idempotency_records() == 1
    assert list(IdempotencyRecord.objects.values_list("key", flat=True)) == ["new"]


# --- health -------------------------------------------------------------------------------------


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_reports_each_dependency(client, fake_redis, s3):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok", "redis": "ok", "storage": "ok"}


def test_readyz_returns_503_when_a_dependency_is_down(client, fake_redis):
    with mock.patch("tutortrack.core.api.health.s3_client", side_effect=ConnectionError):
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["storage"].startswith("error")


# --- schema -------------------------------------------------------------------------------------


def test_openapi_schema_is_served(api):
    response = api.get("/api/v1/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json")
    assert response.status_code == 200
    assert "/api/v1/files/uploads" in response.json()["paths"]


class TestWidgetIsolation(TenantIsolationTestMixin):
    list_url = WIDGETS

    def make_object(self, organisation):
        return WidgetFactory(organisation=organisation)
