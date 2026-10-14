"""Gap batch G3 (payments): methods enabled per branch and card surcharges (FR-11-1),
expiring-card notices (FR-11-2), auto-pay N days before due (FR-11-3) and the bulk
payment-entry grid (FR-11-5)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.core import mail
from django.db import transaction
from hypothesis import HealthCheck, given
from hypothesis import settings as hsettings
from hypothesis import strategies as st
from rest_framework import serializers

from tutortrack.billing.models import Invoice
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.payments import notices, services, surcharges
from tutortrack.payments.models import Payment, PaymentMethod
from tutortrack.payments.providers.base import MethodDetails
from tutortrack.payments.tests.test_payments import (  # noqa: F401 - fixtures
    account,
    fake,
    family,
    finance,
    gbp,
    issue,
)
from tutortrack.people.tests.factories import ClientFactory
from tutortrack.tenancy import settings_service
from tutortrack.tenancy.models import Branch

pytestmark = pytest.mark.django_db


def in_country(org, code):
    org.country = code
    org.save(update_fields=["country"])


def branch_settings(org, values):
    with tenant_context(org):
        branch = Branch.objects.first()
        settings_service.update_settings("payments", values, branch=branch)


# --- legal limits and settings (FR-11-1) ---------------------------------------------------------


def test_surcharge_limits_by_country():
    assert surcharges.limit_for("GB") is None
    assert surcharges.limit_for("ie") is None  # EEA
    assert surcharges.limit_for("US") == Decimal("3")
    assert surcharges.limit_for("CA") == Decimal("2.4")
    assert surcharges.limit_for("AU") == Decimal("3")
    assert surcharges.limit_for("ZA") == Decimal("3")


def test_surcharge_setting_is_refused_where_banned_or_too_high(org):
    with tenant_context(org), pytest.raises(serializers.ValidationError):
        settings_service.update_settings("payments", {"payments.card_surcharge_percent": "1.5"})
    in_country(org, "US")
    with tenant_context(org):
        with pytest.raises(serializers.ValidationError):
            settings_service.update_settings("payments", {"payments.card_surcharge_percent": "3.5"})
        with pytest.raises(serializers.ValidationError):
            settings_service.update_settings(
                "payments", {"payments.card_surcharge_percent": "1.255"}
            )
        settings_service.update_settings("payments", {"payments.card_surcharge_percent": "2.5"})
        assert surcharges.surcharge_percent(None) == Decimal("2.5")
    in_country(org, "GB")  # moved: the stored value no longer applies
    with tenant_context(org):
        assert surcharges.surcharge_percent(None) == Decimal(0)


def test_enabled_methods_validation():
    assert surcharges.clean_methods(["cash", "card"]) == ["card", "cash"]
    for bad in ([], ["bitcoin"], "card"):
        with pytest.raises(serializers.ValidationError):
            surcharges.clean_methods(bad)


@hsettings(
    max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    amount=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("9999.99"), places=2),
    percent=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("3.00"), places=2),
)
def test_surcharge_rounds_half_up_to_pennies(org, amount, percent):
    in_country(org, "US")
    with tenant_context(org):
        settings_service.update_settings(
            "payments", {"payments.card_surcharge_percent": str(percent)}
        )
        value = surcharges.surcharge_for(None, Money(amount, "GBP"))
    exact = amount * percent / Decimal(100)
    assert value.is_rounded()
    assert abs(value.amount - exact) <= Decimal("0.005")
    assert value.amount >= 0


# --- methods per branch -------------------------------------------------------------------------


def test_pay_page_offers_only_enabled_providers(org, client, account, family):  # noqa: F811
    invoice = issue(org, family)
    host = f"{org.slug}.{settings.TENANT_BASE_DOMAIN}"
    assert client.get(f"/api/v1/pay/{invoice.pay_token}", HTTP_HOST=host).json()["providers"] == [
        "stripe"
    ]
    branch_settings(org, {"payments.enabled_methods": ["bank_transfer"]})
    page = client.get(f"/api/v1/pay/{invoice.pay_token}", HTTP_HOST=host).json()
    assert page["providers"] == []
    assert page["can_pay_online"] is False
    refused = client.post(
        f"/api/v1/pay/{invoice.pay_token}/intent", {}, format="json", HTTP_HOST=host
    )
    assert refused.status_code == 422


def test_manual_payment_methods_follow_the_branch(org, family):  # noqa: F811
    branch_settings(org, {"payments.enabled_methods": ["card", "bank_transfer"]})
    with tenant_context(org), transaction.atomic():
        with pytest.raises(BusinessRuleViolation):
            services.record_manual_payment(
                client=family["client"], amount=gbp("10.00"), method="cash"
            )
        paid = services.record_manual_payment(
            client=family["client"], amount=gbp("10.00"), method="bank_transfer"
        )
    assert paid.method == "bank_transfer"


# --- card surcharges (FR-11-1) -------------------------------------------------------------------


def test_card_surcharge_is_charged_and_invoiced_separately(org, client, account, family, fake):  # noqa: F811
    in_country(org, "US")
    branch_settings(org, {"payments.card_surcharge_percent": "2"})
    invoice = issue(org, family, amount="40.00")
    host = f"{org.slug}.{settings.TENANT_BASE_DOMAIN}"
    page = client.get(f"/api/v1/pay/{invoice.pay_token}", HTTP_HOST=host).json()
    assert page["card_surcharge_percent"] == "2"
    intent = client.post(
        f"/api/v1/pay/{invoice.pay_token}/intent", {}, format="json", HTTP_HOST=host
    ).json()
    assert intent["amount"]["amount"] == "40.80"
    assert intent["surcharge"]["amount"] == "0.80"
    fake.succeed_intent(intent["intent"])
    for _ in range(2):  # the page confirms; a repeat changes nothing
        confirmed = client.post(
            f"/api/v1/pay/{invoice.pay_token}/confirm",
            {"intent": intent["intent"]},
            format="json",
            HTTP_HOST=host,
        )
        assert confirmed.json() == {"status": "succeeded"}
    with tenant_context(org):
        invoice.refresh_from_db()
        [payment] = Payment.objects.all()
        fee_invoice = Invoice.objects.exclude(pk=invoice.pk).get()
        allocated = {a.invoice_id: a.amount for a in payment.allocations.all()}
    assert payment.amount == gbp("40.80")
    assert (invoice.status, invoice.total) == ("paid", gbp("40.00"))  # never changed
    assert (fee_invoice.status, fee_invoice.total) == ("paid", gbp("0.80"))
    assert allocated == {invoice.pk: gbp("40.00"), fee_invoice.pk: gbp("0.80")}
    with tenant_context(org):
        assert fee_invoice.lines.get().charge.kind == "surcharge"


def test_payment_requests_are_not_surcharged(org, account, family):  # noqa: F811
    in_country(org, "US")
    branch_settings(org, {"payments.card_surcharge_percent": "2"})
    from tutortrack.billing import services as billing

    with tenant_context(org), transaction.atomic():
        request = billing.create_payment_request(client=family["client"], amount=gbp("100.00"))
        out = services.create_pay_intent(request)
    assert out["amount"] == gbp("100.00")
    assert out["surcharge"].is_zero()


# --- expiring cards (FR-11-2) --------------------------------------------------------------------


def test_expiring_cards_are_told_once(org, account, family):  # noqa: F811
    today = date(2026, 11, 3)
    with tenant_context(org), transaction.atomic():
        card = services.save_method(
            family["client"],
            account,
            MethodDetails(
                "pm_card_visa", "card", brand="visa", last4="4242", exp_month=11, exp_year=2026
            ),
        )
        services.save_method(
            family["client"],
            account,
            MethodDetails(
                "pm_card_later", "card", brand="visa", last4="1111", exp_month=1, exp_year=2028
            ),
        )
    mail.outbox.clear()
    with tenant_context(org):
        assert [m.pk for m in notices.expiring(today)] == [card.pk]
        assert notices.notify_expiring(today) == 1
        assert notices.notify_expiring(today) == 0  # deduplicated
    [message] = mail.outbox
    assert "4242" in message.subject
    assert "/pay/setup/" in message.body
    with tenant_context(org):
        assert OutboxEvent.objects.filter(event_type="payment_method.expiring").count() == 1


def test_expiry_notices_can_be_switched_off(org, account, family):  # noqa: F811
    with tenant_context(org):
        settings_service.update_settings("payments", {"payments.card_expiry_notices": False})
        assert notices.notify_expiring(date(2026, 11, 3)) == 0


# --- auto-pay N days before due (FR-11-3) --------------------------------------------------------


def test_autopay_date(org):
    with tenant_context(org):
        today = services.billing.org_today()
        due = (today + timedelta(days=14)).isoformat()
        assert services.autopay_date(due) == ""  # default: on issue
        settings_service.update_settings(
            "payments",
            {"payments.autopay_timing": "before_due", "payments.autopay_days_before_due": 3},
        )
        assert services.autopay_date(due) == (today + timedelta(days=11)).isoformat()
        assert services.autopay_date((today + timedelta(days=2)).isoformat()) == ""  # passed
        assert services.autopay_date(None) == ""


# --- bulk payment entry (FR-11-5) ----------------------------------------------------------------


def test_bulk_entry_records_every_row_or_none(org, finance, family):  # noqa: F811
    first = issue(org, family, amount="30.00")
    other = ClientFactory(organisation=org)
    good = {
        "client": str(family["client"].pk),
        "amount": {"amount": "30.00", "currency": "GBP"},
        "method": "bank_transfer",
        "reference": "PATEL",
    }
    bad = {
        "client": str(other.pk),
        "amount": {"amount": "-5.00", "currency": "GBP"},
        "method": "cash",
    }
    refused = finance.post("/api/v1/payments/bulk", {"rows": [good, bad]}, format="json")
    assert refused.status_code == 422, refused.content
    assert "1" in refused.json()["errors"]["rows"]
    with tenant_context(org):
        assert not Payment.objects.exists()
    second = {
        **good,
        "client": str(other.pk),
        "amount": {"amount": "12.00", "currency": "GBP"},
        "method": "cash",
    }
    done = finance.post(
        "/api/v1/payments/bulk",
        {"rows": [good, second]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="bulk-1",
    )
    assert done.status_code == 201, done.content
    assert len(done.json()) == 2
    replay = finance.post(
        "/api/v1/payments/bulk",
        {"rows": [good, second]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="bulk-1",
    )
    assert replay.status_code == 201
    with tenant_context(org):
        first.refresh_from_db()
        assert Payment.objects.count() == 2  # the replay recorded nothing new
    assert first.status == "paid"


def test_bulk_entry_needs_permission(org, family):  # noqa: F811
    from tutortrack.core.testing import client_for
    from tutortrack.identity.tests.factories import MembershipFactory

    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    response = tutor.post("/api/v1/payments/bulk", {"rows": []}, format="json")
    assert response.status_code == 403


def test_payment_methods_saved_with_expiry(org, account, family):  # noqa: F811
    with tenant_context(org), transaction.atomic():
        method = services.save_method(
            family["client"],
            account,
            MethodDetails("pm_x", "card", brand="visa", last4="0005", exp_month=2, exp_year=2027),
        )
    with tenant_context(org):
        assert PaymentMethod.objects.get(pk=method.pk).exp_year == 2027
