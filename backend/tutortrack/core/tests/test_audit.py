import pytest
from django.db import ProgrammingError, connection, transaction

from tutortrack.core import audit
from tutortrack.core.context import request_context
from tutortrack.core.models import AuditEntry
from tutortrack.core.testing import TenantIsolationTestMixin, client_for

from .factories import WidgetFactory

pytestmark = pytest.mark.django_db


def test_track_records_field_diff_with_request_context(tenant, user):
    widget = WidgetFactory(organisation=tenant, name="Old")
    ctx = request_context(user_id=user.pk, ip="10.0.0.1", request_id="req-1", user_agent="pytest")
    with ctx, audit.track(widget) as tracker:
        widget.name = "New"
        widget.save()

    entry = tracker.entry
    assert entry is not None
    assert entry.action == "update"
    assert entry.changes == {"name": ["Old", "New"]}
    assert entry.actor_id == user.pk
    assert entry.organisation_id == tenant.pk
    assert entry.object_type == "testapp.widget"
    assert entry.object_id == str(widget.pk)
    assert (entry.ip, entry.request_id, entry.user_agent) == ("10.0.0.1", "req-1", "pytest")


def test_no_entry_when_nothing_changed(tenant):
    widget = WidgetFactory(organisation=tenant)
    with audit.track(widget) as tracker:
        widget.save()
    assert tracker.entry is None


def test_sensitive_fields_are_redacted(tenant):
    widget = WidgetFactory(organisation=tenant, secret_note="old secret")
    with audit.track(widget) as tracker:
        widget.secret_note = "new secret"
        widget.save()
    assert tracker.entry.changes == {"secret_note": ["[REDACTED]", "[REDACTED]"]}

    created = audit.record_create(widget)
    assert created.changes["secret_note"] == [None, "[REDACTED]"]


def test_impersonator_is_recorded(tenant, user, superuser):
    widget = WidgetFactory(organisation=tenant)
    with request_context(user_id=user.pk, impersonator_id=superuser.pk):
        entry = audit.record(widget, "view_as")
    assert entry.impersonator_id == superuser.pk


def test_audit_entries_cannot_be_updated_or_deleted(tenant):
    entry = audit.record(WidgetFactory(organisation=tenant), "create")
    with pytest.raises(ProgrammingError, match="append-only"), transaction.atomic():
        AuditEntry.objects.filter(pk=entry.pk).update(action="tampered")
    with pytest.raises(ProgrammingError, match="append-only"), transaction.atomic():
        AuditEntry.objects.filter(pk=entry.pk).delete()


def test_retention_purge_can_delete_when_explicitly_enabled(tenant):
    entry = audit.record(WidgetFactory(organisation=tenant), "create")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL tutortrack.audit_purge = 'on'")
        AuditEntry.objects.filter(pk=entry.pk).delete()
    assert not AuditEntry.objects.filter(pk=entry.pk).exists()


# --- API ----------------------------------------------------------------------------------------


def test_audit_api_filters_by_object(org, admin_api):
    a, b = WidgetFactory(organisation=org), WidgetFactory(organisation=org)
    audit.record(a, "create")
    audit.record(b, "create")
    response = admin_api.get(
        "/api/v1/audit", {"object_type": "testapp.widget", "object_id": str(a.pk)}
    )
    assert response.status_code == 200
    assert [r["object_id"] for r in response.json()["results"]] == [str(a.pk)]


def test_audit_api_requires_permission(org, user):
    response = client_for(org, user).get("/api/v1/audit")
    assert response.status_code == 403
    assert response["Content-Type"] == "application/problem+json"


def test_audit_api_requires_organisation(superuser):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_login(superuser)
    assert client.get("/api/v1/audit").status_code == 403


class TestAuditIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/audit"

    def make_object(self, organisation):
        return audit.record(WidgetFactory(organisation=organisation), "create")
