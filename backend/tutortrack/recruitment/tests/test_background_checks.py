"""E18-T11: background check providers (uCheck, DBS Update Service, Checkr, AU WWCC):
starting, tracking, attaching results, webhooks, sensitive data and retention."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.models import AuditEntry
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations import routes
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.recruitment import background_checks as checks_service
from tutortrack.recruitment import compliance
from tutortrack.recruitment.checks import Candidate, dbs_update
from tutortrack.recruitment.checks.fake import FakeChecks
from tutortrack.recruitment.models import BackgroundCheck, ComplianceRecord

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fake_checks():
    FakeChecks.reset()
    yield
    FakeChecks.reset()


@pytest.fixture
def people(org) -> dict[str, Any]:
    with tenant_context(org):
        admin = MembershipFactory(organisation=org, role="admin").user
        membership = MembershipFactory(organisation=org, role="tutor")
        tutor = TutorProfileFactory(
            organisation=org,
            status="active",
            membership=membership,
            date_of_birth=date(1990, 5, 17),
        )
        compliance.ensure_requirement_types()
    return {"admin": admin, "tutor": tutor, "tutor_user": membership.user}


def start(org, people, provider="ucheck", **kwargs) -> BackgroundCheck:
    with tenant_context(org):
        check = checks_service.request_check(
            people["tutor"], provider=provider, user=people["admin"], consent=True, **kwargs
        )
        checks_service.initiate(check.pk)  # what the workflow's first activity does
        check.refresh_from_db()
        return check


def test_requesting_needs_consent_and_one_open_check_per_provider(org, people):
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation):
            checks_service.request_check(
                people["tutor"], provider="ucheck", user=people["admin"], consent=False
            )
        with pytest.raises(BusinessRuleViolation):
            checks_service.request_check(
                people["tutor"], provider="nope", user=people["admin"], consent=True
            )
    check = start(org, people)
    with tenant_context(org):
        assert (check.status, check.requirement.key) == ("invited", "dbs_enhanced")
    assert check.invite_url.startswith("https://")
    with tenant_context(org), pytest.raises(BusinessRuleViolation):
        checks_service.request_check(
            people["tutor"], provider="ucheck", user=people["admin"], consent=True
        )


def test_clear_result_is_attached_and_verified_by_the_provider(org, people):
    """FR-18-7: track status, attach results to the compliance record."""
    check = start(org, people, package="enhanced_barred")
    FakeChecks.advance(check.external_id, "completed", "clear")
    with tenant_context(org):
        assert checks_service.poll(check.pk) == "completed"
        check.refresh_from_db()
        record = ComplianceRecord.objects.get(pk=check.record_id)
    assert (check.result, check.invite_url) == ("clear", "")
    assert check.certificate_number == "001234567890"
    assert (record.status, record.verified_by_id) == ("verified", None)
    assert record.number == "001234567890"
    assert record.expiry_date == date(2029, 9, 1)  # 36 months after issue


def test_needs_review_results_wait_for_a_person(org, people):
    check = start(org, people)
    FakeChecks.advance(check.external_id, "completed", "consider")
    with tenant_context(org):
        checks_service.poll(check.pk)
        check.refresh_from_db()
        record = ComplianceRecord.objects.get(pk=check.record_id)
        assert record.status == "submitted"
        with pytest.raises(PermissionDenied):
            checks_service.record_outcome(check, user=people["tutor_user"], result="clear")
        checks_service.record_outcome(check, user=people["admin"], result="clear")
        record.refresh_from_db()
        check.refresh_from_db()
    assert (record.status, record.verified_by_id) == ("verified", people["admin"].pk)
    assert check.reviewed_by_id == people["admin"].pk


def test_results_are_encrypted_and_reading_them_is_audited(org, people):
    check = start(org, people)
    FakeChecks.advance(check.external_id, "completed", "clear")
    with tenant_context(org):
        checks_service.poll(check.pk)
        check.refresh_from_db()
        with pytest.raises(PermissionDenied):
            checks_service.details(check, user=people["tutor_user"])
        details = checks_service.details(check, user=people["admin"])
        assert details["certificate_number"] == "001234567890"
        assert details["summary"]["result"] == "clear"
        assert AuditEntry.objects.filter(action="read", object_id=str(check.pk)).exists()
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT certificate_number, result_details FROM recruitment_backgroundcheck "
                "WHERE id = %s",
                [check.pk],
            )
            number, raw = cursor.fetchone()
    assert "001234567890" not in number
    assert "clear" not in raw


def test_dbs_update_service_recheck_reports_new_information(org, people):
    with tenant_context(org), pytest.raises(BusinessRuleViolation):  # needs a number
        checks_service.request_check(
            people["tutor"], provider="dbs_update", user=people["admin"], consent=True
        )
    check = start(org, people, provider="dbs_update", certificate_number="001234567890")
    assert (check.status, check.result) == ("completed", "clear")
    with tenant_context(org):
        record = ComplianceRecord.objects.get(pk=check.record_id)
        assert record.status == "verified"
    FakeChecks.advance(check.external_id, "completed", "consider")
    with tenant_context(org):
        assert checks_service.recheck(check.pk) == "consider"
        record.refresh_from_db()
    assert record.status == "rejected"
    assert "new information" in record.rejection_reason


def test_wwcc_is_verified_by_staff_on_the_state_page(org, people):
    check = start(org, people, provider="wwcc", state_code="NSW")
    assert check.status == "in_progress"
    api = client_for(org, people["admin"])
    detail = api.get(f"/api/v1/background-checks/{check.pk}").json()
    assert detail["verification_link"].startswith("https://wwccheck.ocg.nsw.gov.au")
    with tenant_context(org):
        checks_service.record_outcome(
            check,
            user=people["admin"],
            result="clear",
            certificate_number="WWC1234567E",
            expiry_date=date(2030, 1, 1),
        )
        check.refresh_from_db()
    assert (check.status, check.result) == ("completed", "clear")


def test_cancel_and_expire(org, people):
    check = start(org, people)
    with tenant_context(org):
        assert checks_service.expire(check.pk) == "expired"
    second = start(org, people)
    with tenant_context(org):
        checks_service.cancel(second, user=people["admin"])
        second.refresh_from_db()
        with pytest.raises(BusinessRuleViolation):
            checks_service.cancel(second, user=people["admin"])
    assert second.status == "cancelled"
    assert FakeChecks.checks[second.external_id].status == "cancelled"


def test_checkr_webhook_is_routed_and_verified(org, people, client):
    from tutortrack.integrations.routes import hmac_hex

    with tenant_context(org):
        IntegrationConnection.objects.create(
            provider="checkr", level="organisation", status="active", secret="checkr-key"
        )
        check = BackgroundCheck.objects.create(
            tutor=people["tutor"],
            provider="checkr",
            status="invited",
            external_id="inv_1",
            candidate_ref="cand_1",
        )
        routes.remember("checkr", "cand_1")
    body = json.dumps(
        {"type": "report.completed", "data": {"object": {"id": "rep_1", "candidate_id": "cand_1"}}}
    ).encode()
    bad = client.post(
        "/webhooks/background-checks/checkr",
        body,
        content_type="application/json",
        HTTP_X_CHECKR_SIGNATURE="nope",
    )
    assert bad.status_code == 400
    ok = client.post(
        "/webhooks/background-checks/checkr",
        body,
        content_type="application/json",
        HTTP_X_CHECKR_SIGNATURE=hmac_hex("checkr-key", body),
    )
    assert ok.status_code == 200
    unknown = json.dumps({"data": {"object": {"candidate_id": "someone-else"}}}).encode()
    assert (
        client.post(
            "/webhooks/background-checks/checkr", unknown, content_type="application/json"
        ).status_code
        == 400
    )
    assert check.pk


def test_retention_purges_details_and_erasure_clears_them(org, people):
    from tutortrack.recruitment.privacy import _check_erase, _check_export

    check = start(org, people)
    FakeChecks.advance(check.external_id, "completed", "clear")
    with tenant_context(org):
        checks_service.poll(check.pk)
        assert checks_service.purge_details(now() + timedelta(days=1), True, 100) == 1
        assert checks_service.purge_details(now() + timedelta(days=1), False, 100) == 1
        check.refresh_from_db()
        assert (check.certificate_number, check.result_details) == ("", "")
        assert check.result == "clear"  # the fact of the check stays
        from tutortrack.privacy.registry import ErasureContext, Person

        person = Person("people.tutor", str(people["tutor"].pk))
        person.add("people.tutor", people["tutor"].pk)
        [section] = _check_export(person)
        assert section.records[0]["provider"] == "ucheck"
        assert "certificate_number" not in section.records[0]
        outcome = _check_erase(person, ErasureContext(labels={}, financial_cutoff=now()))
        assert outcome.retained == 1


def test_api_start_list_providers_and_own_checks(org, people):
    api = client_for(org, people["admin"])
    providers = api.get("/api/v1/background-checks/providers").json()
    keys = {p["key"]: p for p in providers}
    assert keys["ucheck"]["recommended"]
    assert not keys["checkr"]["recommended"]  # a UK org
    created = api.post(
        "/api/v1/background-checks",
        {"tutor": str(people["tutor"].pk), "provider": "ucheck", "consent": True},
        format="json",
    )
    assert created.status_code == 201, created.json()
    assert created.json()["status"] == "requested"
    with tenant_context(org):
        checks_service.initiate(created.json()["id"])
    listed = api.get(f"/api/v1/background-checks?tutor={people['tutor'].pk}").json()
    assert listed["results"][0]["status"] == "invited"
    assert "invite_url" not in listed["results"][0]
    mine = client_for(org, people["tutor_user"]).get("/api/v1/me/background-checks").json()
    assert mine[0]["invite_url"].startswith("https://checks.example.test/invite/")
    forbidden = client_for(org, people["tutor_user"]).post(
        "/api/v1/background-checks",
        {"tutor": str(people["tutor"].pk), "provider": "ucheck", "consent": True},
        format="json",
    )
    assert forbidden.status_code == 403


class TestBackgroundCheckIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/background-checks"

    def make_object(self, organisation: Any) -> BackgroundCheck:
        with tenant_context(organisation):
            tutor = TutorProfileFactory(organisation=organisation, status="active")
            return BackgroundCheck.objects.create(tutor=tutor, provider="ucheck")


# --- the real clients' requests (no network) ---------------------------------------------------


class Recorder:
    def __init__(self, replies: dict[str, Any]):
        self.replies = replies
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> Any:
        from tutortrack.integrations.providers import http

        self.calls.append({"method": method, "url": url, **kwargs})
        for fragment, reply in self.replies.items():
            if fragment in url:
                body = reply if isinstance(reply, bytes) else json.dumps(reply).encode()
                return http.Response(200, None, body)  # type: ignore[arg-type]
        return http.Response(200, None, b"{}")  # type: ignore[arg-type]


CANDIDATE = Candidate(
    ref="chk-1",
    first_name="Nia",
    last_name="Okafor",
    email="nia@example.com",
    date_of_birth="1990-05-17",
    certificate_number="0012 3456 7890",
    organisation_name="Bright Minds",
    requester_first_name="Ada",
    requester_last_name="Admin",
    work_location="CA",
)


def test_checkr_client_creates_a_candidate_and_invitation(monkeypatch):
    from tutortrack.integrations.providers import Credentials, http
    from tutortrack.recruitment.checks.checkr import CheckrClient

    recorder = Recorder(
        {
            "/candidates": {"id": "cand_9"},
            "/invitations": {"id": "inv_9", "invitation_url": "https://x.test/i"},
        }
    )
    monkeypatch.setattr(http, "request", recorder)
    started = CheckrClient().initiate(Credentials(secret="key"), CANDIDATE, "tasker_standard")
    assert (started.external_id, started.candidate_ref) == ("inv_9", "cand_9")
    assert recorder.calls[0]["json_body"]["custom_id"] == "chk-1"
    assert recorder.calls[1]["json_body"]["work_locations"] == [{"country": "US", "state": "CA"}]
    assert recorder.calls[0]["auth_header"].startswith("Basic ")
    assert all(c["user_url"] for c in recorder.calls)


def test_dbs_update_service_status_check(monkeypatch):
    from tutortrack.integrations.providers import Credentials, http

    xml = (
        b"<statusCheckResult><statusCheckResultType>NEW_INFO</statusCheckResultType>"
        b"</statusCheckResult>"
    )
    recorder = Recorder({"/crsc/api/status/": xml})
    monkeypatch.setattr(http, "request", recorder)
    state = dbs_update.DBSUpdateServiceClient().fetch(Credentials(), "x", CANDIDATE)
    assert (state.status, state.result) == ("completed", "consider")
    url = recorder.calls[0]["url"]
    assert "/001234567890?" in url
    assert "dateOfBirth=17%2F05%2F1990" in url
    assert "surname=OKAFOR" in url
    assert dbs_update.parse(b"<x/>") == ""


def test_ucheck_client_creates_an_application(monkeypatch):
    from tutortrack.integrations.providers import Credentials, http
    from tutortrack.recruitment.checks.ucheck import UCheckClient

    recorder = Recorder(
        {"/applications": {"id": "app-1", "status": "invited", "applicant_url": "https://u.test/a"}}
    )
    monkeypatch.setattr(http, "request", recorder)
    started = UCheckClient().initiate(Credentials(secret="key"), CANDIDATE, "enhanced")
    assert (started.external_id, started.invite_url) == ("app-1", "https://u.test/a")
    assert recorder.calls[0]["json_body"]["check_type"] == "enhanced"
