"""E11-T01..T10: provider onboarding and webhooks, saved methods and consent, manual and
card payments, the pay page, auto-pay attempts, refunds, disputes, payouts, receipts."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.conf import settings
from django.core import mail

from tutortrack.billing import ledger
from tutortrack.billing import services as billing
from tutortrack.billing.models import Invoice
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict
from tutortrack.core.models import AuditEntry, OutboxEvent, WorkflowLink
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.payments import services
from tutortrack.payments.models import (
    AccountRoute,
    AutoPayConsent,
    Dispute,
    Payment,
    PaymentAttempt,
    PaymentMethod,
    ProviderAccount,
    ProviderPayout,
    ProviderWebhookEvent,
)
from tutortrack.payments.providers import get_provider
from tutortrack.payments.providers.base import MethodDetails
from tutortrack.payments.tasks import process_webhook
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, StudentFactory

pytestmark = pytest.mark.django_db


def gbp(amount: str) -> Money:
    return Money(Decimal(amount), "GBP")


@pytest.fixture(autouse=True)
def fake():
    get_provider.cache_clear()
    provider = get_provider("stripe")
    yield provider
    get_provider.cache_clear()


@pytest.fixture
def finance(org):
    return client_for(org, MembershipFactory(organisation=org, role="finance").user)


@pytest.fixture
def account(org):
    with tenant_context(org):
        acct = ProviderAccount.objects.create(
            provider="stripe", account_ref="acct_live1", status="active", charges_enabled=True
        )
        AccountRoute.objects.create(
            provider="stripe", account_ref="acct_live1", organisation_id=org.pk
        )
    return acct


@pytest.fixture
def family(org):
    client = ClientFactory(organisation=org, display_name="The Patels")
    contact = ContactFactory(organisation=org, client=client, email="priya@example.com")
    with tenant_context(org):
        client.billing_contact = contact
        client.save()
    student = StudentFactory(organisation=org, client=client)
    return {"client": client, "student": student}


def issue(org, family, amount="40.00", n=1):
    out = []
    with tenant_context(org):
        for _ in range(n):
            billing.create_ad_hoc_charge(
                client=family["client"],
                student=family["student"],
                description="Tuition",
                unit_price=gbp(amount),
            )
            out.append(billing.issue_invoice(billing.create_draft(family["client"]), send=False))
    return out if n > 1 else out[0]


def webhook(
    api_client, event_type, obj, *, account="acct_live1", event_id=None, sig="fake-signature"
):
    body = {
        "id": event_id or f"evt_{event_type}_{obj.get('id', '')}",
        "type": event_type,
        "account": account,
        "data": {"object": obj},
    }
    return api_client.post(
        "/webhooks/stripe",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=sig,
    )


def run_webhooks(org):
    with tenant_context(org):
        ids = list(
            ProviderWebhookEvent.objects.filter(processed_at__isnull=True).values_list(
                "pk", flat=True
            )
        )
    for pk in ids:
        process_webhook(organisation_id=str(org.pk), event_id=str(pk))


def events_of(org, kind):
    with tenant_context(org):
        return [e.payload["data"] for e in OutboxEvent.objects.filter(event_type=kind)]


# --- providers and webhooks (T01/T02) -----------------------------------------------------------


def test_connect_onboard_and_activate_by_webhook(org, finance, client):
    response = finance.post("/api/v1/payments/providers/stripe/connect", {}, format="json")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["url"].startswith("https://connect.example.test/onboard/acct_")
    assert body["account"]["status"] == "pending"
    ref = body["account"]["account_ref"]
    assert AccountRoute.objects.get(account_ref=ref).organisation_id == org.pk
    again = finance.post("/api/v1/payments/providers/stripe/connect", {}, format="json").json()
    assert again["account"]["id"] == body["account"]["id"]  # resumes onboarding

    update = {"id": ref, "charges_enabled": True, "payouts_enabled": True,
              "requirements": {"currently_due": []}, "default_currency": "gbp"}  # fmt: skip
    assert webhook(client, "account.updated", update, account=ref).status_code == 200
    assert webhook(client, "account.updated", update, account=ref).status_code == 200  # dup
    run_webhooks(org)
    providers = finance.get("/api/v1/payments/providers").json()
    assert (providers[0]["status"], providers[0]["default_currency"]) == ("active", "GBP")
    assert len(events_of(org, "provider_account.connected")) == 1
    with tenant_context(org):
        assert ProviderWebhookEvent.objects.count() == 1


def test_webhooks_need_a_valid_signature_and_known_account(org, client, account):
    assert webhook(client, "account.updated", {"id": "x"}, sig="nope").status_code == 400
    assert webhook(client, "account.updated", {"id": "x"}, account="acct_other").status_code == 200
    with tenant_context(org):
        assert not ProviderWebhookEvent.objects.exists()


def test_disconnect_is_blocked_while_clients_use_autopay(org, finance, account, family):
    with tenant_context(org):
        method = services.save_method(
            family["client"], account, MethodDetails("pm_card_visa", "card", "visa", "4242")
        )
        services.give_consent(family["client"], method, ip_address="10.0.0.1", user_agent="x")
    blocked = finance.post(f"/api/v1/payments/providers/{account.pk}/disconnect")
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "autopay_clients"


# --- methods and consent (T03) ------------------------------------------------------------------


def test_setup_link_saves_a_card_and_records_autopay_consent(
    org, finance, client, account, family, fake
):
    created = finance.post(f"/api/v1/clients/{family['client'].pk}/payment-methods/setup-link")
    assert created.status_code == 201
    token = created.json()["url"].rsplit("/", 1)[1]
    host = f"{org.slug}.{settings.TENANT_BASE_DOMAIN}"
    page = client.get(f"/api/v1/pay/setup/{token}", HTTP_HOST=host).json()
    assert page["client_secret"].endswith("_secret")
    assert "authorise Bright Minds" in page["consent_text"]
    fake.setup_methods[page["intent"]] = "pm_card_visa"
    done = client.post(
        f"/api/v1/pay/setup/{token}",
        {"intent": page["intent"], "autopay": True},
        format="json",
        HTTP_HOST=host,
        REMOTE_ADDR="203.0.113.9",
    )
    assert done.status_code == 200, done.json()
    assert done.json()["method"]["last4"] == "4242"
    assert done.json()["auto_pay"] is True
    with tenant_context(org):
        consent = AutoPayConsent.objects.select_related("payment_method").get()
        assert (consent.ip_address, consent.payment_method.brand) == ("203.0.113.9", "visa")
    assert client.get(f"/api/v1/pay/setup/{token}", HTTP_HOST=host).status_code == 404  # used
    listed = finance.get(f"/api/v1/clients/{family['client'].pk}/payment-methods").json()
    assert listed["auto_pay"] is True
    assert listed["methods"][0]["is_default"] is True


def test_autopay_needs_the_clients_consent(org, finance, account, family):
    response = finance.post(
        f"/api/v1/clients/{family['client'].pk}/autopay", {"enabled": True}, format="json"
    )
    assert (response.status_code, response.json()["code"]) == (422, "consent_required")
    with tenant_context(org):
        method = services.save_method(
            family["client"], account, MethodDetails("pm_card_visa", "card", "visa", "4242")
        )
        services.give_consent(family["client"], method, ip_address=None, user_agent="")
    off = finance.post(
        f"/api/v1/clients/{family['client'].pk}/autopay", {"enabled": False}, format="json"
    ).json()
    assert off["auto_pay"] is False
    with tenant_context(org):
        assert AutoPayConsent.objects.get().withdrawn_at is not None
        second = services.save_method(
            family["client"], account, MethodDetails("pm_debit_x", "bacs_debit", "", "6789")
        )
    assert finance.post(f"/api/v1/payment-methods/{method.pk}/default").json()["is_default"]
    assert finance.delete(f"/api/v1/payment-methods/{method.pk}").status_code == 204
    with tenant_context(org):
        second.refresh_from_db()
        assert second.is_default is True  # the remaining method takes over


# --- payments and allocation (T04) --------------------------------------------------------------


def test_manual_payment_pays_oldest_first_and_keeps_the_rest_as_credit(org, finance, family):
    first, second = issue(org, family, n=2)
    response = finance.post(
        "/api/v1/payments",
        {
            "client": str(family["client"].pk),
            "amount": {"amount": "100.00", "currency": "GBP"},
            "method": "bank_transfer",
            "reference": "PATEL OCT",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert [a["amount"]["amount"] for a in body["allocations"]] == ["40.00", "40.00"]
    assert body["unallocated"] == {"amount": "20.00", "currency": "GBP"}
    with tenant_context(org):
        first.refresh_from_db()
        assert first.status == "paid"
        balances = ledger.balances(family["client"])
    assert balances.available_credit == gbp("20.00")
    assert events_of(org, "payment.succeeded")[0]["invoice_ids"] == [str(first.pk), str(second.pk)]
    assert finance.post(
        "/api/v1/payments",
        {"client": str(family["client"].pk), "amount": {"amount": "5", "currency": "GBP"},
         "method": "card"},
        format="json",
    ).status_code == 400  # fmt: skip


def test_explicit_allocation_and_reallocation(org, finance, family):
    first, second = issue(org, family, n=2)
    payment = finance.post(
        "/api/v1/payments",
        {
            "client": str(family["client"].pk),
            "amount": {"amount": "40.00", "currency": "GBP"},
            "method": "cash",
            "allocations": [{"invoice": str(second.pk), "amount": "40.00"}],
        },
        format="json",
    ).json()
    moved = finance.post(
        f"/api/v1/payments/{payment['id']}/allocate",
        {"allocations": [{"invoice": str(first.pk), "amount": "40.00"}]},
        format="json",
    )
    assert moved.status_code == 200, moved.json()
    with tenant_context(org):
        first.refresh_from_db()
        second.refresh_from_db()
        assert (first.status, second.status) == ("paid", "issued")
        assert AuditEntry.objects.filter(action="reallocate").exists()
    too_much = finance.post(
        f"/api/v1/payments/{payment['id']}/allocate",
        {"allocations": [{"invoice": str(first.pk), "amount": "50.00"}]},
        format="json",
    )
    assert too_much.status_code == 422


def test_paying_a_payment_request_adds_credit(org, finance, family):
    with tenant_context(org):
        request = billing.create_payment_request(client=family["client"], amount=gbp("400"))
    finance.post(
        "/api/v1/payments",
        {
            "client": str(family["client"].pk),
            "amount": {"amount": "400.00", "currency": "GBP"},
            "method": "bank_transfer",
            "payment_request": str(request.pk),
        },
        format="json",
    )
    with tenant_context(org):
        request.refresh_from_db()
        assert request.status == "paid"
        assert ledger.balances(family["client"]).available_credit == gbp("400.00")


# --- the pay page (T05) -------------------------------------------------------------------------


def test_pay_page_card_payment_is_recorded_once(org, client, account, family, fake):
    invoice = issue(org, family)
    host = f"{org.slug}.{settings.TENANT_BASE_DOMAIN}"
    page = client.get(f"/api/v1/pay/{invoice.pay_token}", HTTP_HOST=host).json()
    assert (page["number"], page["amount_due"]["amount"]) == ("INV-000001", "40.00")
    assert page["can_pay_online"] is True
    assert client.get(f"/api/v1/pay/{invoice.pay_token}/pdf", HTTP_HOST=host).content.startswith(
        b"%PDF"
    )
    partial = client.post(
        f"/api/v1/pay/{invoice.pay_token}/intent",
        {"amount": "10.00"},
        format="json",
        HTTP_HOST=host,
    )
    assert partial.status_code == 422  # partial payments are off
    intent = client.post(
        f"/api/v1/pay/{invoice.pay_token}/intent",
        {"save_method": True},
        format="json",
        HTTP_HOST=host,
    ).json()
    assert intent["amount"]["amount"] == "40.00"
    fake.succeed_intent(intent["intent"])
    confirmed = client.post(
        f"/api/v1/pay/{invoice.pay_token}/confirm",
        {"intent": intent["intent"]},
        format="json",
        HTTP_HOST=host,
    )
    assert confirmed.json() == {"status": "succeeded"}
    obj = {"id": intent["intent"], "amount": 4000, "amount_received": 4000, "currency": "gbp",
           "metadata": {"invoice_id": str(invoice.pk), "organisation_id": str(org.pk)}}  # fmt: skip
    webhook(client, "payment_intent.succeeded", obj)
    run_webhooks(org)
    with tenant_context(org):
        invoice.refresh_from_db()
        [payment] = Payment.objects.all()
        assert PaymentMethod.objects.filter(client=family["client"]).exists()  # saved
    assert invoice.status == "paid"
    assert (payment.source, payment.fee) == ("pay_page", gbp("0.80"))
    assert payment.net == gbp("39.20")
    assert (
        client.get(f"/api/v1/pay/{invoice.pay_token}", HTTP_HOST=host).json()["amount_due"][
            "amount"
        ]
        == "0.00"
    )
    assert client.get("/api/v1/pay/not-a-real-token-at-all-xx", HTTP_HOST=host).status_code == 404


# --- auto-pay attempts (T06) --------------------------------------------------------------------


def autopay_client(org, account, family, method_ref="pm_card_visa"):
    kind = "bacs_debit" if "debit" in method_ref else "card"
    with tenant_context(org):
        method = services.save_method(
            family["client"], account, MethodDetails(method_ref, kind, "visa", "4242")
        )
        services.give_consent(family["client"], method, ip_address=None, user_agent="")
    return method


def test_collection_attempt_success_and_failure(org, account, family):
    autopay_client(org, account, family)
    invoice = issue(org, family)
    with tenant_context(org):
        assert services.should_autopay(invoice.pk) is True
        assert services.attempt_collection(invoice.pk, 1, "k1") == "succeeded"
        assert services.attempt_collection(invoice.pk, 1, "k1") == "succeeded"  # retried activity
        invoice.refresh_from_db()
        assert invoice.status == "paid"
        assert services.attempt_collection(invoice.pk, 2, "k2") == "settled"
    declined = ClientFactory(organisation=org)
    family2 = {"client": declined, "student": StudentFactory(organisation=org, client=declined)}
    autopay_client(org, account, family2, method_ref="pm_fail_card")
    unpaid = issue(org, family2)
    with tenant_context(org):
        assert services.attempt_collection(unpaid.pk, 1, "k3") == "failed"
        attempt = PaymentAttempt.objects.get(idempotency_key="k3")
        assert attempt.failure_code == "card_declined"
        services.collection_failed(unpaid.pk, 1, final=True)
    assert events_of(org, "payment.failed")[0]["final"] is True


def test_direct_debit_is_pending_until_confirmed(org, client, account, family):
    autopay_client(org, account, family, method_ref="pm_debit_bacs")
    invoice = issue(org, family)
    with tenant_context(org):
        assert services.attempt_collection(invoice.pk, 1, "dd1") == "processing"
        payment = Payment.objects.get()
        assert payment.status == "pending"
        assert ledger.ledger_balance(family["client"], "GBP") == gbp("40.00")  # not yet
    succeeded = {"id": payment.provider_ref, "amount": 4000, "currency": "gbp", "metadata": {}}
    webhook(client, "payment_intent.succeeded", succeeded)
    run_webhooks(org)
    with tenant_context(org):
        payment.refresh_from_db()
        invoice.refresh_from_db()
    assert (payment.status, invoice.status) == ("succeeded", "paid")


def test_collect_is_refused_while_a_collection_runs(org, finance, account, family):
    autopay_client(org, account, family)
    invoice = issue(org, family)
    from tutortrack.payments.processes import collect_workflow_id

    with tenant_context(org):
        WorkflowLink.objects.create(
            workflow_id=collect_workflow_id(org.pk, invoice.pk),
            workflow_type="PaymentCollectionWorkflow",
            process="collect",
            started_at=now(),
        )
        with pytest.raises(Conflict) as busy:
            services.start_collection(invoice)
    assert busy.value.extra["code"] == "collection_in_progress"
    response = finance.post(f"/api/v1/invoices/{invoice.pk}/collect")
    assert (response.status_code, response.json()["code"]) == (409, "collection_in_progress")


# --- refunds, disputes, payouts, receipts (T07..T09) --------------------------------------------


def test_refund_takes_credit_first_then_reopens_invoices_with_a_credit_note(
    org, finance, account, family, fake
):
    invoice = issue(org, family)
    with tenant_context(org):
        payment = services.record_provider_payment(
            account=account, client=family["client"], amount=gbp("50.00"), provider_ref="pi_x",
            invoice=invoice,
        )  # fmt: skip
    first = finance.post(
        f"/api/v1/payments/{payment.pk}/refund",
        {"amount": "10.00", "reason": "Overpaid"},
        format="json",
    )
    assert first.status_code == 201, first.json()
    assert ("refund", {"payment": "pi_x", "amount": "10.00"}) in fake.calls
    second = finance.post(
        f"/api/v1/payments/{payment.pk}/refund",
        {"amount": "40.00", "reason": "Lesson not delivered", "credit_note": True},
        format="json",
    ).json()
    assert second["credit_note"] is not None
    with tenant_context(org):
        payment.refresh_from_db()
        invoice.refresh_from_db()
        assert payment.status == "refunded"
        assert invoice.status == "paid"  # reopened, then credited to zero
        assert invoice.amount_paid == gbp("0.00")
        assert ledger.ledger_balance(family["client"], "GBP") == gbp("0.00")
    assert (
        finance.post(
            f"/api/v1/payments/{payment.pk}/refund", {"reason": "again"}, format="json"
        ).status_code
        == 422
    )


def test_lost_dispute_reverses_the_payment_and_reopens_the_invoice(org, client, account, family):
    invoice = issue(org, family)
    with tenant_context(org):
        payment = services.record_provider_payment(
            account=account, client=family["client"], amount=gbp("40.00"), provider_ref="pi_d",
            invoice=invoice,
        )  # fmt: skip
    obj = {"id": "dp_1", "payment_intent": "pi_d", "amount": 4000, "currency": "gbp",
           "reason": "fraudulent", "evidence_details": {"due_by": 1893456000}}  # fmt: skip
    webhook(client, "charge.dispute.created", obj)
    run_webhooks(org)
    with tenant_context(org):
        payment.refresh_from_db()
        assert payment.status == "disputed"
    assert events_of(org, "payment.disputed")[0]["dispute_id"]
    webhook(client, "charge.dispute.closed", {**obj, "status": "lost"}, event_id="evt_closed")
    run_webhooks(org)
    with tenant_context(org):
        invoice.refresh_from_db()
        assert Dispute.objects.get().status == "lost"
        assert invoice.status == "issued"
        assert ledger.ledger_balance(family["client"], "GBP") == gbp("40.00")


def test_payouts_and_receipts(org, finance, client, account, family):
    webhook(client, "payout.paid", {"id": "po_1", "amount": 12345, "currency": "gbp",
                                     "status": "paid", "arrival_date": 1791763200})  # fmt: skip
    run_webhooks(org)
    with tenant_context(org):
        assert ProviderPayout.objects.get().amount == gbp("123.45")
    assert finance.get("/api/v1/payments/payouts").json()["results"][0]["provider_ref"] == "po_1"
    invoice = issue(org, family)
    payment = finance.post(
        "/api/v1/payments",
        {"client": str(family["client"].pk), "amount": {"amount": "40.00", "currency": "GBP"},
         "method": "cheque"},
        format="json",
    ).json()  # fmt: skip
    from tutortrack.payments.tasks import send_receipt

    assert send_receipt(organisation_id=str(org.pk), payment_id=payment["id"]) is True
    assert mail.outbox[-1].to == ["priya@example.com"]
    assert mail.outbox[-1].attachments[0][2] == "application/pdf"
    assert finance.get(f"/api/v1/payments/{payment['id']}/receipt").content.startswith(b"%PDF")
    with tenant_context(org):
        invoice.refresh_from_db()
    assert invoice.status == "paid"


def test_coordinators_cannot_record_payments(org, family):
    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    assert coordinator.get("/api/v1/payments").status_code == 403


def test_record_rejects_bad_requests(org, family):
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation):
            services.record_manual_payment(client=family["client"], amount=gbp("0"), method="cash")
        other = ClientFactory(organisation=org)
        request = billing.create_payment_request(client=other, amount=gbp("10"))
        with pytest.raises(BusinessRuleViolation):
            services.record_manual_payment(
                client=family["client"], amount=gbp("10"), method="cash", payment_request=request
            )


# --- tenant isolation ---------------------------------------------------------------------------


class TestPaymentIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/payments"

    def make_object(self, organisation):
        with tenant_context(organisation):
            client = ClientFactory(organisation=organisation)
            return services.record_manual_payment(client=client, amount=gbp("10"), method="cash")


class TestPayoutIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/payments/payouts"

    def make_object(self, organisation):
        with tenant_context(organisation):
            account = ProviderAccount.objects.create(
                provider="stripe", account_ref=f"acct_{organisation.slug}", status="active"
            )
            return ProviderPayout.objects.create(
                account=account, provider_ref=f"po_{organisation.slug}", currency="GBP",
                amount=gbp("1"), status="paid",
            )  # fmt: skip

    def test_detail_of_other_organisation_is_404(self, org, other_org):
        pytest.skip("payouts have no detail endpoint")


def test_invoices_are_not_payable_across_tenants(org, other_org, client, account, family):
    invoice = issue(org, family)
    response = client.get(
        f"/api/v1/pay/{invoice.pay_token}",
        HTTP_HOST=f"{other_org.slug}.{settings.TENANT_BASE_DOMAIN}",
    )
    assert response.status_code == 404
    with tenant_context(org):
        assert Invoice.objects.filter(pk=invoice.pk).exists()
