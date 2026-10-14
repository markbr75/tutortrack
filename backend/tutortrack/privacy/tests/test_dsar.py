"""E29-T05: data subject requests: intake, verification, deadline, the export compiler,
redaction and secure delivery (FR-29-4)."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import timedelta

import pytest
from django.db import transaction

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.growth.tests.factories import AffiliateFactory, ReviewFactory
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.learning.models import Goal, ProgressReport
from tutortrack.learning.tests.factories import GoalFactory, ProgressReportFactory
from tutortrack.privacy import dsar, erasure, export
from tutortrack.privacy.models import DataSubjectRequest, ErasureRecord
from tutortrack.privacy.tests.test_erasure import _file

pytestmark = pytest.mark.django_db


def _log(org, family, **kwargs):
    defaults = {
        "kind": "access",
        "subject_type": "people.student",
        "subject_id": str(family.student.pk),
        "requester_name": "Priya Patel",
        "requester_email": "priya@example.com",
        "relationship": "parent",
    }
    with tenant_context(org), transaction.atomic():
        return dsar.log_request(**{**defaults, **kwargs})


def _verified(org, family, **kwargs):
    request = _log(org, family, **kwargs)
    with tenant_context(org):
        return dsar.update_checks(
            request, {"identity": True, "matches_records": True, "authority": True}
        )


def test_staff_log_a_request_and_the_deadline_starts(org, family, owner_api):
    response = owner_api.post(
        "/api/v1/data-requests",
        {
            "kind": "access",
            "subject_type": "people.student",
            "subject_id": str(family.student.pk),
            "requester_name": "Priya Patel",
            "requester_email": "Priya@Example.com",
            "relationship": "parent",
            "channel": "email",
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["reference"] == "DSAR-00001"
    assert body["status"] == "received"
    assert body["subject_label"] == "Arjun Patel"
    assert body["requester_email"] == "priya@example.com"
    with tenant_context(org):
        received = DataSubjectRequest.objects.get(pk=body["id"])
    assert received.due_at - received.received_at == timedelta(days=30)
    assert [c["key"] for c in body["checklist"]] == ["identity", "matches_records", "authority"]
    assert OutboxEvent.objects.filter(event_type="data_request.received").exists()


def test_unknown_people_are_refused(org, owner_api):
    response = owner_api.post(
        "/api/v1/data-requests",
        {
            "kind": "access",
            "subject_type": "people.student",
            "subject_id": "nope",
            "requester_name": "X",
        },
        format="json",
    )
    assert response.status_code == 404


def test_verification_needs_every_required_check(org, family, owner_api):
    request = _log(org, family)
    url = f"/api/v1/data-requests/{request.pk}/verify"
    partial = owner_api.post(url, {"checks": {"identity": True}}, format="json").json()
    assert partial["status"] == "received"
    assert partial["verified_at"] is None
    done = owner_api.post(
        url,
        {"checks": {"matches_records": True, "authority": True}, "note": "ID seen"},
        format="json",
    ).json()
    assert done["status"] == "in_progress"
    assert done["verified_at"] is not None
    assert OutboxEvent.objects.filter(event_type="data_request.verified").count() == 1


def test_the_deadline_can_be_extended_by_two_months_at_most(org, family, owner_api):
    request = _log(org, family)
    url = f"/api/v1/data-requests/{request.pk}/extend"
    ok = owner_api.post(url, {"days": 60, "reason": "Complex: 5 years of records"}, format="json")
    assert ok.status_code == 200
    too_long = owner_api.post(url, {"days": 1, "reason": "More"}, format="json")
    assert too_long.status_code == 422


def test_reject_tells_the_requester(org, family, owner_api):
    request = _log(org, family)
    response = owner_api.post(
        f"/api/v1/data-requests/{request.pk}/reject",
        {"reason": "We could not verify your identity"},
        format="json",
    )
    assert response.json()["status"] == "rejected"


def test_the_export_covers_every_app_and_is_reviewed_before_delivery(org, family, owner, s3):
    GoalFactory(organisation=org, student=family.student, title="Grade 7 in the mock")
    ProgressReportFactory(organisation=org, student=family.student, summary="Arjun is flying")
    ReviewFactory(organisation=org, client=family.client, contact=family.contact, text="Great")
    with tenant_context(org):
        Message.objects.create(
            type_key="lesson_booked",
            channel="email",
            recipient_type="contact",
            recipient_id=str(family.contact.pk),
            to="priya@example.com",
            subject="Booked",
            body="Arjun's lesson is booked",
            target_type="people.client",
            target_id=str(family.client.pk),
            dedupe_key="t1",
        )
    request = _verified(org, family, subject_type="people.client", subject_id=str(family.client.pk))
    with tenant_context(org):
        result = dsar.compile_for_review(str(request.pk))
    assert result["status"] == "in_review"
    sections = result["summary"]["sections"]
    for key in (
        "people.clients",
        "people.contacts",
        "people.students",
        "learning.goals",
        "learning.progress_reports",
        "growth.reviews",
        "comms.messages",
        "identity.profile",
    ):
        assert sections.get(key), key

    api = client_for(org, owner)
    preview = api.get(f"/api/v1/data-requests/{request.pk}/export-preview").json()
    goals = next(s for s in preview["sections"] if s["key"] == "learning.goals")
    assert goals["records"][0]["title"] == "Grade 7 in the mock"
    with tenant_context(org):
        assert AuditEntry.objects.filter(object_id=str(request.pk), action="read").exists()

    student_row = next(s for s in preview["sections"] if s["key"] == "people.students")["records"][
        0
    ]
    response = api.put(
        f"/api/v1/data-requests/{request.pk}/redactions",
        {
            "redactions": [
                {"section": "learning.goals", "record_id": goals["records"][0]["id"]},
                {
                    "section": "people.students",
                    "record_id": student_row["id"],
                    "record_field": "learning_needs",
                    "reason": "third-party report",
                },
            ]
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    with tenant_context(org):
        package = export.build_package(DataSubjectRequest.objects.get(pk=request.pk))
        data = export.read(package)
    archive = zipfile.ZipFile(io.BytesIO(data))
    assert {"data.json", "summary.pdf", "README.txt"} <= set(archive.namelist())
    document = json.loads(archive.read("data.json"))
    keys = {s["key"]: s for s in document["sections"]}
    assert keys["learning.goals"]["records"] == []
    assert keys["people.students"]["records"][0]["learning_needs"] == "[redacted]"
    assert archive.read("summary.pdf").startswith(b"%PDF")


def test_documents_are_included_unless_redacted(org, family, s3):
    from tutortrack.crm.models import Document

    stored = _file(org, s3, "report.pdf")
    with tenant_context(org):
        Document.objects.create(
            target_type="people.student",
            target_id=str(family.student.pk),
            file=stored,
            title="Report",
        )
    request = _verified(org, family)
    with tenant_context(org):
        dsar.compile_for_review(str(request.pk))
        request = DataSubjectRequest.objects.get(pk=request.pk)
        names = zipfile.ZipFile(io.BytesIO(export.read(export.build_package(request)))).namelist()
        assert any(n.startswith("files/crm/") and n.endswith("report.pdf") for n in names)
        dsar.set_redactions(request, [{"file_id": str(stored.pk)}])
        request = DataSubjectRequest.objects.get(pk=request.pk)
        names = zipfile.ZipFile(io.BytesIO(export.read(export.build_package(request)))).namelist()
        assert not any(n.startswith("files/") for n in names)


def test_delivery_sends_an_expiring_link_and_downloads_are_audited(
    org, family, s3, django_capture_on_commit_callbacks
):
    request = _verified(org, family)
    with tenant_context(org):
        dsar.compile_for_review(str(request.pk))
        dsar.approve_redactions(DataSubjectRequest.objects.get(pk=request.pk))
        with django_capture_on_commit_callbacks(execute=True):
            dsar.deliver(str(request.pk))
        request = DataSubjectRequest.objects.get(pk=request.pk)
        message = Message.objects.get(type_key="privacy_dsar_requester")
    assert request.status == "delivered"
    assert request.link_expires_at - request.delivered_at == timedelta(days=7)
    token = message.body.split("/data-export/")[1].split()[0]
    api = client_for(org)
    response = api.get(f"/api/v1/data-export/{token}")
    assert response.status_code == 302
    assert "X-Amz-Signature" in response["Location"]
    with tenant_context(org):
        request.refresh_from_db()
        assert request.download_count == 1
        assert AuditEntry.objects.filter(object_id=str(request.pk), action="read").exists()
        DataSubjectRequest.objects.filter(pk=request.pk).update(
            link_expires_at=now() - timedelta(minutes=1)
        )
    assert api.get(f"/api/v1/data-export/{token}").status_code == 404
    assert api.get("/api/v1/data-export/not-a-token").status_code == 404


def test_expiry_deletes_the_package_and_completes_the_request(org, family, s3):
    request = _verified(org, family)
    with tenant_context(org):
        dsar.compile_for_review(str(request.pk))
        dsar.deliver(str(request.pk))
        assert dsar.expire_link(str(request.pk)) == "completed"
        request = DataSubjectRequest.objects.select_related("package_file").get(pk=request.pk)
    assert request.status == "completed"
    assert request.token_hash == ""
    assert request.package_file.filename == "erased"


def test_reminders_fall_due_before_the_deadline(
    org, family, owner, django_capture_on_commit_callbacks
):
    request = _log(org, family)
    with tenant_context(org):
        DataSubjectRequest.objects.filter(pk=request.pk).update(due_at=now() + timedelta(days=5))
        with django_capture_on_commit_callbacks(execute=True):
            assert dsar.send_reminder(str(request.pk)).startswith("due:7:")
        assert dsar.send_reminder(str(request.pk)) == ""  # 2 days: not yet
        state = dsar.workflow_state(str(request.pk))
        assert len(state["reminders"]) == 2
        assert Message.objects.filter(type_key="privacy_dsar_staff").exists()


def test_erasure_requests_are_previewed_and_need_approval(org, family, owner_api):
    request = _verified(org, family, kind="erasure")
    with tenant_context(org):
        result = dsar.compile_for_review(str(request.pk))
    assert result["summary"]["erasure"]["subjects"]["people.student"] == 1
    response = owner_api.post(f"/api/v1/data-requests/{request.pk}/approve-erasure")
    assert response.status_code == 200
    assert response.json()["erasure_approved_at"] is not None


def test_erasure_approval_is_refused_under_a_legal_hold(org, family, owner, owner_api):
    from tutortrack.privacy import holds

    request = _verified(org, family, kind="erasure")
    with tenant_context(org):
        dsar.compile_for_review(str(request.pk))
        holds.place(
            subject_type="people.student",
            subject_id=str(family.student.pk),
            reason="Court",
            user=owner,
        )
    response = owner_api.post(f"/api/v1/data-requests/{request.pk}/approve-erasure")
    assert response.status_code == 422
    assert response.json()["code"] == "legal_hold"


def test_erasure_runs_across_the_apps(org, family):
    GoalFactory(organisation=org, student=family.student)
    ProgressReportFactory(organisation=org, student=family.student)
    ReviewFactory(organisation=org, client=family.client, contact=family.contact, text="Great")
    affiliate = AffiliateFactory(organisation=org, user=family.parent, name="Priya Patel")
    request = _verified(
        org, family, kind="erasure", subject_type="people.client", subject_id=str(family.client.pk)
    )
    with tenant_context(org):
        record = erasure.erase_now("people.client", str(family.client.pk), request=request)
        assert not Goal.objects.filter(student=family.student).exists()
        assert not ProgressReport.objects.filter(student=family.student).exists()
        from tutortrack.growth.models import Affiliate, Review

        assert Review.objects.get(client=family.client).text == ""
        assert Affiliate.objects.get(pk=affiliate.pk).email == ""
    assert record.status == ErasureRecord.Status.COMPLETED
    assert record.report["learning"]["deleted"] >= 2


def test_the_portal_asks_for_their_own_or_their_childs_data(org, family):
    api = client_for(org, family.parent)
    mine = api.post("/api/v1/me/data-requests", {"kind": "access"}, format="json")
    assert mine.status_code == 201, mine.content
    child = api.post(
        "/api/v1/me/data-requests",
        {"kind": "erasure", "student_id": str(family.student.pk)},
        format="json",
    )
    assert child.status_code == 201
    listed = api.get("/api/v1/me/data-requests").json()
    assert {r["kind"] for r in listed} == {"access", "erasure"}
    with tenant_context(org):
        own = DataSubjectRequest.objects.get(pk=mine.json()["id"])
        assert own.subject_type == "identity.user"
        assert own.channel == "portal"
        assert own.checks == {"identity": True}  # signed in
        theirs = DataSubjectRequest.objects.get(pk=child.json()["id"])
        assert theirs.subject_type == "people.student"
        assert theirs.relationship == "parent"


def test_parents_cannot_ask_for_other_childrens_data(org, family):
    from tutortrack.people.tests.factories import StudentFactory

    stranger = StudentFactory(organisation=org)
    api = client_for(org, family.parent)
    response = api.post(
        "/api/v1/me/data-requests",
        {"kind": "access", "student_id": str(stranger.pk)},
        format="json",
    )
    assert response.status_code == 404


def test_only_privacy_staff_handle_requests(org, family):
    coordinator = MembershipFactory(organisation=org, role="coordinator").user
    assert client_for(org, coordinator).get("/api/v1/data-requests").status_code == 403


class TestDataRequestIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/data-requests"

    def make_object(self, organisation):
        from tutortrack.people.tests.factories import StudentFactory

        student = StudentFactory(organisation=organisation)
        with tenant_context(organisation), transaction.atomic():
            return dsar.log_request(
                kind="access",
                subject_type="people.student",
                subject_id=str(student.pk),
                requester_name="Someone",
            )


class TestErasureRecordIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/erasures"

    def make_object(self, organisation):
        from tutortrack.people.tests.factories import StudentFactory

        student = StudentFactory(organisation=organisation)
        with tenant_context(organisation):
            return erasure.plan("people.student", str(student.pk))
