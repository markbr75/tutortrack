"""E12-T12 (Phase 3): Wise payouts, US 1099-NEC data and commission-based pay."""

from __future__ import annotations

import base64
import csv
import io
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.test import override_settings
from hypothesis import given
from hypothesis import strategies as st

from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.models import AuditEntry
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations.models import IntegrationConnection, WebhookRoute
from tutortrack.payroll import commission, services, tax_forms, wise_payouts
from tutortrack.payroll.models import PayItem, Payout, TaxFormFiling, TutorPayProfile
from tutortrack.payroll.payouts.wise import map_state, recipient_body
from tutortrack.payroll.payouts.wise_fake import FakeWise
from tutortrack.people.models import Address
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.tenancy import settings_service

from .test_payroll import completed, items, make_run

pytestmark = pytest.mark.django_db
UK_BANK = {
    "country": "GB",
    "account_name": "Nia Jones",
    "sort_code": "20-00-00",
    "account_number": "55779911",
}


@pytest.fixture
def world(org) -> dict[str, Any]:
    """Like ``test_payroll.world``: a tutor on an active job with a family and finance."""
    from tutortrack.catalogue.tests.factories import ServiceFactory
    from tutortrack.jobs import services as jobs
    from tutortrack.people.tests.factories import ClientFactory, StudentFactory

    with tenant_context(org):
        membership = MembershipFactory(organisation=org, role="tutor")
        tutor = TutorProfileFactory(
            organisation=org, status="active", first_name="Nia", membership=membership
        )
        client = ClientFactory(organisation=org)
        student = StudentFactory(organisation=org, client=client)
        service = ServiceFactory(organisation=org)
        job = jobs.create_job(
            client=client,
            service=service,
            students=[{"student": student}],
            tutors=[{"tutor": tutor}],
            status="active",
        )
        finance = MembershipFactory(organisation=org, role="finance")
    return {
        "tutor": tutor,
        "client": client,
        "student": student,
        "service": service,
        "job": job,
        "tutor_user": membership.user,
        "finance": finance.user,
    }


@pytest.fixture(autouse=True)
def _fake_wise():
    FakeWise.reset()
    yield
    FakeWise.reset()


def connect_wise(org) -> IntegrationConnection:
    with tenant_context(org):
        return IntegrationConnection.objects.create(
            provider="wise",
            level="organisation",
            status="active",
            secret="token",
            external_account_id="fake-profile",
            account_name="Bright Minds (Wise)",
        )


def wise_tutor(org, w) -> TutorPayProfile:
    with tenant_context(org):
        return services.update_profile(w["tutor"], method="wise", bank=UK_BANK)


# --- Wise payouts ---------------------------------------------------------------------------------


def test_wise_payout_is_sent_and_settles_by_polling(org, world):
    connect_wise(org)
    wise_tutor(org, world)
    completed(org, world)
    run = make_run(org)
    assert "no_wise" not in {w["code"] for w in run.warnings}
    with tenant_context(org):
        services.approve(run, user=world["finance"])
        assert services.send_payouts(run.pk) == 1  # processing at Wise
        payout = Payout.objects.get(pay_run=run)
        assert (payout.method, payout.status) == ("wise", "processing")
        assert payout.provider_ref.startswith("wise_fake_")
        profile = TutorPayProfile.objects.get(tutor=world["tutor"])
        assert profile.wise_recipient_id
    assert WebhookRoute.objects.filter(provider="wise", external_id=payout.provider_ref).exists()
    FakeWise.settle(payout.provider_ref)
    with tenant_context(org):
        assert wise_payouts.refresh(run) == 1
        assert services.finalise(run.pk) == "paid"
        payout.refresh_from_db()
    assert payout.status == "paid"
    assert all(i.status == "paid" for i in items(org, payout=payout))


def test_wise_is_idempotent_and_recipients_follow_bank_detail_changes(org, world):
    connect_wise(org)
    profile = wise_tutor(org, world)
    with tenant_context(org):
        creds = wise_payouts._credentials()
        first = wise_payouts._recipient(profile, "GBP", creds)
        profile.refresh_from_db()
        assert wise_payouts._recipient(profile, "GBP", creds) == first  # reused
        profile = services.update_profile(
            world["tutor"], bank={**UK_BANK, "account_number": "11223344"}
        )
        assert wise_payouts._recipient(profile, "GBP", creds) != first
    client = FakeWise()
    one = client.transfer(
        creds,
        first,
        amount=Money("10.00", "GBP"),
        source_currency="GBP",
        reference="PR-1",
        idempotency_key="payout-1",
    )
    again = client.transfer(
        creds,
        first,
        amount=Money("10.00", "GBP"),
        source_currency="GBP",
        reference="PR-1",
        idempotency_key="payout-1",
    )
    assert one == again


def test_bounced_wise_transfer_returns_items_for_the_next_run(org, world):
    connect_wise(org)
    wise_tutor(org, world)
    completed(org, world)
    run = make_run(org)
    FakeWise.instant = False
    with tenant_context(org):
        services.approve(run, user=world["finance"])
        services.send_payouts(run.pk)
        payout = Payout.objects.get(pay_run=run)
    FakeWise.settle(payout.provider_ref, "failed")
    with tenant_context(org):
        wise_payouts.refresh(run)
        payout.refresh_from_db()
        assert payout.status == "failed"
        assert services.finalise(run.pk) == "partially_failed"
    [item] = items(org)
    assert (item.status, item.pay_run_id) == ("ready", None)


def test_wise_without_a_connection_fails_the_payout_and_warns(org, world):
    wise_tutor(org, world)
    completed(org, world)
    run = make_run(org)
    assert "no_wise" in {w["code"] for w in run.warnings}
    with tenant_context(org):
        services.approve(run, user=world["finance"])
        services.send_payouts(run.pk)
        payout = Payout.objects.get(pay_run=run)
    assert payout.status == "failed"
    assert "Wise" in payout.failure_reason


def _keys():
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )

    def sign(body: bytes) -> str:
        return base64.b64encode(key.sign(body, padding.PKCS1v15(), hashes.SHA256())).decode()

    return pem, sign


def test_wise_webhook_is_verified_and_settles_the_payout(org, world, client):
    connect_wise(org)
    wise_tutor(org, world)
    completed(org, world)
    run = make_run(org)
    with tenant_context(org):
        services.approve(run, user=world["finance"])
        services.send_payouts(run.pk)
        payout = Payout.objects.get(pay_run=run)
    pem, sign = _keys()
    body = json.dumps(
        {
            "event_type": "transfers#state-change",
            "data": {
                "resource": {"id": payout.provider_ref, "type": "transfer"},
                "current_state": "outgoing_payment_sent",
            },
        }
    ).encode()
    with override_settings(WISE={"API_URL": "https://api.wise.test", "WEBHOOK_PUBLIC_KEY": pem}):
        forged = client.post(
            "/webhooks/wise",
            body,
            content_type="application/json",
            HTTP_X_SIGNATURE_SHA256=sign(b"other"),
        )
        assert forged.status_code == 400
        ok = client.post(
            "/webhooks/wise",
            body,
            content_type="application/json",
            HTTP_X_SIGNATURE_SHA256=sign(body),
        )
        assert ok.status_code == 200
    with tenant_context(org):
        payout.refresh_from_db()
    assert payout.status == "paid"


def test_wise_request_shapes():
    body = recipient_body(
        currency="GBP",
        name="Nia",
        country="GB",
        profile="42",
        details={"sort_code": "200000", "account_number": "55779911"},
    )
    assert (body["type"], body["details"]["sortCode"]) == ("sort_code", "200000")
    iban = recipient_body(
        currency="EUR",
        name="Nia",
        country="IE",
        profile="42",
        details={"iban": "IE29AIBK93115212345678"},
    )
    assert iban["type"] == "iban"
    us = recipient_body(
        currency="USD",
        name="Nia",
        country="US",
        profile="42",
        details={"routing_number": "021000021", "account_number": "1234"},
    )
    assert us["details"]["abartn"] == "021000021"
    assert map_state("outgoing_payment_sent") == "paid"
    assert map_state("bounced_back") == "failed"
    assert map_state("processing") == "processing"


def test_wise_api_client_sends_quote_transfer_and_funding(monkeypatch):
    from tutortrack.integrations.providers import Credentials, http
    from tutortrack.payroll.payouts.wise import WiseApi

    calls: list[dict[str, Any]] = []

    def fake(method: str, url: str, **kwargs: Any) -> http.Response:
        calls.append({"method": method, "url": url, **kwargs})
        reply: dict[str, Any] = {}
        if url.endswith("/quotes"):
            reply = {"id": "quote-1"}
        elif url.endswith("/v1/transfers"):
            reply = {"id": 777, "status": "processing"}
        elif url.endswith("/payments"):
            reply = {"status": "COMPLETED"}
        return http.Response(200, None, json.dumps(reply).encode())  # type: ignore[arg-type]

    monkeypatch.setattr(http, "request", fake)
    result = WiseApi().transfer(
        Credentials(secret="tok", account_id="42"),
        "123",
        amount=Money("50.00", "GBP"),
        source_currency="GBP",
        reference="PR-0001",
        idempotency_key="payout-x",
    )
    assert (result.status, result.ref) == ("processing", "777")
    assert [c["url"].split("/v")[-1] for c in calls][:1] == ["3/profiles/42/quotes"]
    assert calls[0]["json_body"]["targetAmount"] == "50.00"  # never a float
    assert calls[1]["json_body"]["customerTransactionId"]
    assert all(c["user_url"] for c in calls)  # through core.net.safe_urlopen


# --- commission pay ------------------------------------------------------------------------------


@given(
    net=st.decimals(min_value=0, max_value=10000, places=2),
    total=st.decimals(min_value=Decimal("0.01"), max_value=10000, places=2),
    paid=st.decimals(min_value=0, max_value=20000, places=2),
    percent=st.decimals(min_value=Decimal("0.01"), max_value=100, places=2),
)
def test_commission_maths(net, total, paid, percent):
    collected = commission.collected([(net, total, paid)])
    assert Decimal(0) <= collected <= net
    amount = commission.amount(collected, percent, "GBP")
    assert amount.is_rounded()
    assert Decimal(0) <= amount.amount <= net
    # half-up at line level, from the unrounded figure
    expected = (collected * percent / 100).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
    assert amount.amount == expected
    # paying more never lowers commission
    more = commission.amount(commission.collected([(net, total, paid + 1)]), percent, "GBP")
    assert more.amount >= amount.amount


@given(st.lists(st.decimals(min_value=0, max_value=100, places=2), min_size=1, max_size=5))
def test_commission_is_never_negative_and_zero_without_payment(nets):
    lines = [(n, Decimal("100"), Decimal(0)) for n in nets]
    assert commission.amount(commission.collected(lines), Decimal("40"), "USD").is_zero()
    assert commission.amount(Decimal("-5"), Decimal("40"), "USD").is_zero()


def test_commission_needs_pay_when_client_paid_and_a_percentage(org, world):
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation):
            services.update_profile(world["tutor"], pay_basis="commission", commission_percent="40")
        settings_service.update_settings("payroll", {"payroll.pay_when_client_paid": True})
        with pytest.raises(BusinessRuleViolation):
            services.update_profile(world["tutor"], pay_basis="commission")
        with pytest.raises(BusinessRuleViolation):
            services.update_profile(
                world["tutor"], pay_basis="commission", commission_percent="140"
            )
        profile = services.update_profile(
            world["tutor"], pay_basis="commission", commission_percent="40"
        )
    assert (profile.pay_basis, profile.commission_percent) == ("commission", Decimal("40.00"))


def test_commission_follows_what_the_client_paid(org, world):
    """FR-12-10: 40% of collected revenue, computed after payment allocation."""
    from tutortrack.billing import services as billing

    with tenant_context(org):
        settings_service.update_settings("payroll", {"payroll.pay_when_client_paid": True})
        services.update_profile(world["tutor"], pay_basis="commission", commission_percent="40")
    done = completed(org, world)  # £40 lesson, nothing collected yet
    assert [i for i in items(org, lesson=done) if i.status != "void"] == []
    with tenant_context(org):
        billing.sync_lesson_charges(done.pk)
        invoice = billing.issue_invoice(billing.create_draft(world["client"]))
        billing.allocate_payment(invoice, Money(invoice.total.amount / 2, invoice.currency))
        commission.resync([done.pk])
    [half] = [i for i in items(org, lesson=done) if i.status != "void"]
    net = invoice.subtotal.amount
    assert half.amount == Money(net / 2 * Decimal("0.4"), "GBP").round_to_minor()
    assert half.status == "held"  # still waiting for the rest
    with tenant_context(org):
        invoice.refresh_from_db()
        billing.allocate_payment(invoice, invoice.balance_due)
        commission.resync([done.pk])
        services.reevaluate_lessons([done.pk])
    [full] = [i for i in items(org, lesson=done) if i.status != "void"]
    assert full.amount == Money(net * Decimal("0.4"), "GBP").round_to_minor()
    assert full.status == "ready"


# --- 1099-NEC ------------------------------------------------------------------------------------


@pytest.fixture
def us_world(org) -> dict[str, Any]:
    with tenant_context(org):
        org.country, org.default_currency, org.timezone = "US", "USD", "America/New_York"
        org.save()
        finance = MembershipFactory(organisation=org, role="finance").user
        address = Address.objects.create(
            line1="1 Main St", city="Austin", region="TX", postcode="73301", country="US"
        )
        tutor = TutorProfileFactory(
            organisation=org, status="active", first_name="Ava", last_name="Lee", address=address
        )
        employee = TutorProfileFactory(
            organisation=org, status="active", employment_type="employee"
        )
    return {"finance": finance, "tutor": tutor, "employee": employee}


_MONTHS = iter(range(10**6))


def pay(org, tutor, amount: str, *, kind: str = "bonus", year: int = 2025) -> None:
    """A payout paid in ``year`` (backdated), from its own pay run."""
    month = next(_MONTHS) % 12 + 1
    with tenant_context(org):
        item = services.create_manual_item(
            tutor=tutor,
            kind="bonus",
            description="Pay",
            amount=Money(amount, "USD"),
            day=datetime(year, month, 1).date(),
        )
        run, _ = services.create_pay_run(
            period_start=datetime(year, month, 1).date(),
            period_end=datetime(year, month, 28).date(),
            start_workflow=False,
        )
        services.assemble(run.pk)
        Payout.objects.filter(pay_run=run).update(
            status="paid", paid_at=datetime(year, month, 15, tzinfo=UTC)
        )
        PayItem.objects.filter(pk=item.pk).update(status="paid", kind=kind)


def test_tax_identity_is_encrypted_masked_and_audited(org, us_world):
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation):
            tax_forms.set_tax_identity(us_world["tutor"], tin="123", tin_type="ssn")
        with pytest.raises(BusinessRuleViolation):
            tax_forms.set_tax_identity(us_world["tutor"], tin="812-34-5678", tin_type="itin")
        profile = tax_forms.set_tax_identity(us_world["tutor"], tin="123-45-6789", tin_type="ssn")
        assert profile.tin_hint == "6789"
        assert tax_forms.tax_identity(profile, user=None, full=False)["tin"] == "•••-••-6789"
        with pytest.raises(PermissionDenied):
            tax_forms.tax_identity(
                profile, user=MembershipFactory(organisation=org, role="tutor").user, full=True
            )
        full = tax_forms.tax_identity(profile, user=us_world["finance"], full=True)
        assert full["tin"] == "123-45-6789"
        assert AuditEntry.objects.filter(action="read", object_id=str(profile.pk)).exists()
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT tin FROM payroll_tutorpayprofile WHERE id = %s", [profile.pk])
            assert "6789" not in cursor.fetchone()[0]  # encrypted at rest


def test_1099_totals_threshold_and_finalised_filings(org, us_world):
    tutor = us_world["tutor"]
    pay(org, tutor, "450.00")
    pay(org, tutor, "300.00", kind="adjustment")
    pay(org, tutor, "99.00", kind="expense")  # reimbursement: not box 1
    pay(org, us_world["employee"], "5000.00")  # employees get W-2s, not 1099s
    with tenant_context(org):
        summary = tax_forms.summary(2025)
        assert summary["threshold"] == "600"
        [row] = summary["rows"]
        assert (row["tutor"].pk, row["box1"]) == (tutor.pk, Money("750.00", "USD"))
        assert row["reportable"]
        assert row["problems"] == ["missing_tin"]
        with pytest.raises(BusinessRuleViolation):
            tax_forms.finalise(2025, user=us_world["finance"])
        tax_forms.set_tax_identity(tutor, tin="123-45-6789", tin_type="ssn")
        [filing] = tax_forms.finalise(2025, user=us_world["finance"])
        assert (filing.box1, filing.tin_hint) == (Money("750.00", "USD"), "6789")
        assert tax_forms.finalise(2025, user=us_world["finance"]) == []  # unchanged: kept
    pay(org, tutor, "50.00")
    with tenant_context(org):
        [correction] = tax_forms.finalise(2025, user=us_world["finance"])
        assert correction.corrects_id == filing.pk
        filing.refresh_from_db()
        assert filing.superseded
        assert tax_forms.threshold(2026) == Decimal(2000)
        with pytest.raises(BusinessRuleViolation):
            tax_forms.finalise(now().year, user=us_world["finance"])


def test_1099_csv_export_masks_unless_allowed(org, us_world):
    tutor = us_world["tutor"]
    pay(org, tutor, "900.00")
    with tenant_context(org):
        tax_forms.set_tax_identity(tutor, tin="123-45-6789", tin_type="ssn")
        tax_forms.finalise(2025, user=us_world["finance"])
    api = client_for(org, us_world["finance"])
    masked = api.get("/api/v1/payroll/tax-years/2025/1099/export")
    assert masked.status_code == 200
    rows = list(csv.reader(io.StringIO(masked.content.decode())))
    assert rows[0][0] == "Form Type"
    assert rows[1][6] == "XXX-XX-6789"
    assert rows[1][14] == "900.00"
    full = api.get("/api/v1/payroll/tax-years/2025/1099/export?full_tin=true")
    assert "123-45-6789" in full.content.decode()
    with tenant_context(org):
        assert AuditEntry.objects.filter(action="read", changes__reason="1099_export").exists()
    tutor_user = MembershipFactory(organisation=org, role="tutor").user
    assert (
        client_for(org, tutor_user)
        .get("/api/v1/payroll/tax-years/2025/1099/export?full_tin=true")
        .status_code
        == 403
    )


def test_1099_api_and_tutor_summary(org, us_world):
    tutor = us_world["tutor"]
    pay(org, tutor, "700.00")
    api = client_for(org, us_world["finance"])
    response = api.get("/api/v1/payroll/tax-years/2025/1099")
    assert response.status_code == 200
    assert response.json()["rows"][0]["box1"]["amount"] == "700.00"
    put = api.put(
        f"/api/v1/tutors/{tutor.pk}/tax-identity",
        {"tin_type": "ssn", "tin": "123-45-6789"},
        format="json",
    )
    assert put.status_code == 200
    assert put.json()["tin"] == "•••-••-6789"
    done = api.post("/api/v1/payroll/tax-years/2025/1099/finalise", HTTP_IDEMPOTENCY_KEY="k1")
    assert done.status_code == 201, done.json()
    with tenant_context(org):
        membership = MembershipFactory(organisation=org, role="tutor")
        tutor.membership = membership
        tutor.save()
    mine = client_for(org, membership.user).get("/api/v1/me/tax-summary?year=2025").json()
    assert (mine["box1"], mine["filed"], mine["reportable"]) == ("700.00", True, True)


class TestTaxFormIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/payroll/tax-forms"

    def make_object(self, organisation: Any) -> TaxFormFiling:
        with tenant_context(organisation):
            tutor = TutorProfileFactory(organisation=organisation, status="active")
            filing = TaxFormFiling(
                tutor=tutor, tax_year=2025, currency="USD", finalised_at=now() - timedelta(days=1)
            )
            filing.box1 = Money("700.00", "USD")
            filing.save()
            return filing
