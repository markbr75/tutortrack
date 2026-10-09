"""E29-T03: global audit search and export, sensitive reads, login history, alerts."""

from __future__ import annotations

import csv
import io

import pytest
from django.core import mail

from tutortrack.core import audit
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.core.testing import client_for
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory

from .factories import WidgetFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(org):
    return MembershipFactory(organisation=org, role="owner", user__email="owner@example.com").user


def record(org, actor, name, action="update"):
    from tutortrack.core.context import request_context

    widget = WidgetFactory(organisation=org, name=name)
    with tenant_context(org), request_context(user_id=actor.pk):
        return audit.record(widget, action)


def test_search_by_actor_text_and_action(org, owner):
    other = UserFactory(email="coord@example.com")
    record(org, owner, "Maths lesson")
    record(org, other, "Science lesson", action="delete")
    api = client_for(org, owner)

    by_actor = api.get("/api/v1/audit", {"actor_email": "COORD@example.com"}).json()["results"]
    assert [r["object_repr"] for r in by_actor] == ["Science lesson"]
    assert by_actor[0]["actor_email"] == "coord@example.com"
    by_text = api.get("/api/v1/audit", {"q": "maths"}).json()["results"]
    assert [r["object_repr"] for r in by_text] == ["Maths lesson"]
    by_action = api.get("/api/v1/audit", {"action": "delete"}).json()["results"]
    assert len(by_action) == 1


def test_export_is_csv_audited_and_formula_safe(org, owner):
    record(org, owner, "=HYPERLINK(evil)")
    response = client_for(org, owner).get("/api/v1/audit/export")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0][0] == "created_at"
    assert any(row[4] == "'=HYPERLINK(evil)" for row in rows[1:])
    with tenant_context(org):
        assert AuditEntry.objects.filter(action="export", object_repr="audit log").exists()


def test_export_needs_permission(org):
    coordinator = MembershipFactory(organisation=org, role="coordinator").user
    assert client_for(org, coordinator).get("/api/v1/audit/export").status_code == 403


def test_repeated_exports_alert_the_owners(
    org, owner, settings, django_capture_on_commit_callbacks
):
    from tutortrack.core.events.dispatcher import dispatch_batch

    settings.MASS_EXPORT_ALERT_THRESHOLD = 3
    api = client_for(org, owner)
    for _ in range(4):
        api.get("/api/v1/audit/export")
    assert OutboxEvent.objects.filter(event_type="security.alert").count() == 1  # once per window
    dispatch_batch()
    assert [m.to for m in mail.outbox] == [["owner@example.com"]]
    assert "exported data many times" in mail.outbox[0].body


def test_tax_id_is_hidden_from_viewers_and_reads_are_logged(org, owner):
    from tutortrack.tenancy.models import Organisation

    o = Organisation.objects.get(pk=org.pk)
    o.tax_number = "UTR 999"
    o.save()
    assert client_for(org, owner).get("/api/v1/organisation").json()["tax_number"] == "UTR 999"
    with tenant_context(org):
        assert AuditEntry.objects.filter(action="read", changes={"reason": "tax id"}).count() == 1
    manager = MembershipFactory(organisation=org, role="branch_manager").user
    assert "tax_number" not in client_for(org, manager).get("/api/v1/organisation").json()


def test_login_history(org, owner):
    from rest_framework.test import APIClient

    from tutortrack.identity.tests.factories import TEST_PASSWORD

    member = MembershipFactory(organisation=org, role="tutor", user__email="t@example.com")
    client = APIClient(HTTP_HOST="brightminds.tutortrack.test")
    client.post("/api/v1/auth/login", {"email": "t@example.com", "password": "x"}, format="json")
    client.post(
        "/api/v1/auth/login", {"email": "t@example.com", "password": TEST_PASSWORD}, format="json"
    )
    mine = client.get("/api/v1/me/logins").json()
    assert [e["success"] for e in mine] == [True, False]

    admin_view = client_for(org, owner).get(f"/api/v1/memberships/{member.pk}/logins")
    assert admin_view.status_code == 200
    assert len(admin_view.json()) == 2
    tutor_view = client.get(f"/api/v1/memberships/{member.pk}/logins")
    assert tutor_view.status_code == 403
