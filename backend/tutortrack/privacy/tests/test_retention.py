"""E29-T07: retention policies, legal holds and the purge (FR-29-5)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import transaction

from tutortrack.comms.models import Message
from tutortrack.core import audit
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.models import Student
from tutortrack.people.tests.factories import StudentFactory
from tutortrack.privacy import holds, registry, retention
from tutortrack.privacy.models import LegalHold, RetentionPolicy, RetentionRun

pytestmark = pytest.mark.django_db


def _archived_student(org, years_ago: int, **kwargs):
    student = StudentFactory(organisation=org, first_name="Old", last_name="Learner", **kwargs)
    with tenant_context(org):
        Student.objects.filter(pk=student.pk).update(
            archived_at=now() - timedelta(days=365 * years_ago), status="archived"
        )
    return student


def test_every_category_gets_a_policy_with_its_default(org):
    with tenant_context(org):
        policies = {p.category: p for p in retention.ensure_policies()}
    assert policies["archived_students"].period_days == 365 * 6 + 2
    assert policies["rejected_applications"].period_days == 183
    assert policies["audit_logs"].period_days >= 365 * 7
    assert {c.key for c in registry.retention_categories()} == set(policies)


def test_staff_change_periods_but_not_below_the_minimum(org, owner_api):
    listed = owner_api.get("/api/v1/retention-policies").json()
    policy = next(p for p in listed if p["category"] == "messages")
    assert policy["category_label"]
    ok = owner_api.patch(
        f"/api/v1/retention-policies/{policy['id']}", {"period_days": 400}, format="json"
    )
    assert ok.status_code == 200
    assert ok.json()["period_days"] == 400
    audit_policy = next(p for p in listed if p["category"] == "audit_logs")
    too_short = owner_api.patch(
        f"/api/v1/retention-policies/{audit_policy['id']}", {"period_days": 365}, format="json"
    )
    assert too_short.status_code == 422


def test_dry_run_reports_and_the_purge_erases_old_archived_students(org):
    old = _archived_student(org, 7)
    recent = _archived_student(org, 1)
    with tenant_context(org):
        run = retention.start_run(dry_run=True)
        report = retention.dry_run_report(run)
        assert report["archived_students"]["due"] == 1
        assert Student.objects.get(pk=old.pk).first_name == "Old"  # dry run changes nothing
        live = retention.start_run(dry_run=False)
        retention.dry_run_report(live)
        assert retention.purge_batch(live, "archived_students") == 1
        assert Student.objects.get(pk=old.pk).first_name.startswith("Erased Student #")
        assert Student.objects.get(pk=recent.pk).first_name == "Old"
        assert retention.purge_batch(live, "archived_students") == 0  # not twice
        finished = retention.finish_run(live)
    assert finished.status == "completed"
    assert finished.report["archived_students"]["done"] == 1


def test_legal_holds_are_skipped_by_the_purge(org, owner):
    held = _archived_student(org, 7)
    with tenant_context(org):
        holds.place(
            subject_type="people.student", subject_id=str(held.pk), reason="Claim", user=owner
        )
        run = retention.start_run(dry_run=False)
        assert retention.dry_run_report(run)["archived_students"]["due"] == 0
        assert retention.purge_batch(run, "archived_students") == 0
        assert Student.objects.get(pk=held.pk).first_name == "Old"


def test_disabled_policies_are_not_purged(org):
    _archived_student(org, 7)
    with tenant_context(org):
        retention.ensure_policies()
        RetentionPolicy.objects.filter(category="archived_students").update(enabled=False)
        run = retention.start_run(dry_run=False)
        assert "archived_students" not in retention.dry_run_report(run)
        assert retention.purge_batch(run, "archived_students") == 0


def test_old_messages_are_purged(org):
    with tenant_context(org):
        old = Message.objects.create(
            type_key="lesson_booked",
            channel="email",
            recipient_type="contact",
            recipient_id="x",
            to="a@example.com",
            body="old",
            dedupe_key="old",
        )
        Message.objects.filter(pk=old.pk).update(created_at=now() - timedelta(days=800))
        Message.objects.create(
            type_key="lesson_booked",
            channel="email",
            recipient_type="contact",
            recipient_id="x",
            to="a@example.com",
            body="new",
            dedupe_key="new",
        )
        run = retention.start_run(dry_run=False)
        assert retention.dry_run_report(run)["messages"]["due"] == 1
        assert retention.purge_batch(run, "messages") == 1
        assert list(Message.objects.values_list("body", flat=True)) == ["new"]


@pytest.mark.django_db(transaction=True, databases=["default", "platform"])
def test_audit_entries_past_the_period_are_purged_despite_the_append_only_trigger(org):
    with tenant_context(org), transaction.atomic():
        policy = RetentionPolicy.objects.create(category="audit_logs", period_days=365 * 7 + 2)
        entry = audit.record(policy, "test")
    with tenant_context(org):
        assert retention._purge_audit(now() - timedelta(days=1), True, 10) == 0
        assert retention._purge_audit(now() + timedelta(days=1), True, 10) >= 1
        assert retention._purge_audit(now() + timedelta(days=1), False, 10) >= 1
        assert not AuditEntry.objects.filter(pk=entry.pk).exists()
        # Outside a purge the table stays append-only for the application.
        other = audit.record(policy, "test")
        with pytest.raises(Exception, match="permission denied"), transaction.atomic():
            AuditEntry.objects.filter(pk=other.pk).delete()


def test_a_manual_run_starts_the_workflow(org, owner_api, monkeypatch):
    started = []
    monkeypatch.setattr("tutortrack.core.workflows.start", lambda *a, **k: started.append(k["id"]))
    response = owner_api.post("/api/v1/retention-runs", {"dry_run": True}, format="json")
    assert response.status_code == 201, response.content
    assert response.json()["trigger"] == "manual"
    assert started
    assert started[0].startswith("retention-purge:")


def test_only_privacy_admins_manage_retention(org):
    tutor = MembershipFactory(organisation=org, role="tutor").user
    assert client_for(org, tutor).get("/api/v1/retention-policies").status_code == 403


def test_legal_holds_api(org, family, owner_api):
    created = owner_api.post(
        "/api/v1/legal-holds",
        {
            "subject_type": "people.client",
            "subject_id": str(family.client.pk),
            "reason": "Fee dispute",
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    assert created.json()["subject_label"] == "The Patels"
    assert created.json()["active"] is True
    released = owner_api.post(
        f"/api/v1/legal-holds/{created.json()['id']}/release",
        {"reason": "Settled"},
        format="json",
    )
    assert released.json()["active"] is False
    with tenant_context(org):
        assert LegalHold.objects.get().release_reason == "Settled"


class TestLegalHoldIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/legal-holds"

    def make_object(self, organisation):
        student = StudentFactory(organisation=organisation)
        with tenant_context(organisation):
            return holds.place(
                subject_type="people.student", subject_id=str(student.pk), reason="Claim"
            )


class TestRetentionRunIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/retention-runs"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return RetentionRun.objects.create(started_at=now())
