"""Shared helpers for the accounting tests: a family that is invoiced, a Stripe account,
and connecting/mapping/enabling Xero or QuickBooks through the API (fake ledgers)."""

from __future__ import annotations

import urllib.parse
from decimal import Decimal
from typing import Any

import pytest

from tutortrack.accounting.models import AccountingConnection
from tutortrack.billing import services as billing
from tutortrack.catalogue.tests.factories import TaxRateFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.money import Money
from tutortrack.core.testing import client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.payments.models import AccountRoute, ProviderAccount
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, StudentFactory

ACCOUNTS = [
    ("revenue", "default", "acc-200"),
    ("clearing", "default", "acc-092"),
    ("clearing", "provider:stripe", "acc-091"),
    ("bank", "default", "acc-090"),
    ("fees", "default", "acc-404"),
    ("tutor_cost", "default", "acc-310"),
    ("expense", "default", "acc-420"),
    ("bad_debt", "default", "acc-684"),
    ("rounding", "default", "acc-860"),
    ("receivable", "default", "acc-610"),
    ("payable", "default", "acc-800"),
    ("sales_tax", "default", "acc-820"),
    ("purchase_tax", "default", "INPUT2"),
]


def gbp(amount: str) -> Money:
    return Money(Decimal(amount), "GBP")


@pytest.fixture
def world(org) -> dict[str, Any]:
    from tutortrack.payments.providers import get_provider

    get_provider.cache_clear()
    with tenant_context(org):
        finance = MembershipFactory(organisation=org, role="finance").user
        vat = TaxRateFactory(organisation=org, name="VAT", percent=Decimal("20"))
        client = ClientFactory(organisation=org, display_name="The Patels")
        contact = ContactFactory(organisation=org, client=client, email="priya@example.com")
        client.billing_contact = contact
        client.save()
        student = StudentFactory(organisation=org, client=client)
        account = ProviderAccount.objects.create(
            provider="stripe", account_ref="acct_e23", status="active", charges_enabled=True
        )
        AccountRoute.objects.create(
            provider="stripe", account_ref="acct_e23", organisation_id=org.pk
        )
    return {
        "finance": finance,
        "api": client_for(org, finance),
        "vat": vat,
        "client": client,
        "student": student,
        "account": account,
    }


def issue(org, w, amount: str = "100.00", *, vat: bool = True, n: int = 1) -> Any:
    out = []
    with tenant_context(org):
        for _ in range(n):
            billing.create_ad_hoc_charge(
                client=w["client"],
                student=w["student"],
                description="Tuition",
                unit_price=gbp(amount),
                tax_rate=w["vat"] if vat else None,
            )
            out.append(billing.issue_invoice(billing.create_draft(w["client"]), send=False))
    return out if n > 1 else out[0]


def connect(org, w, provider: str = "xero") -> AccountingConnection:
    api = w["api"]
    started = api.post(
        "/api/v1/integrations/oauth/start",
        {"provider": provider, "level": "organisation", "next": "/settings/accounting"},
        format="json",
    )
    assert started.status_code == 200, started.json()
    query = urllib.parse.parse_qs(urllib.parse.urlparse(started.json()["authorize_url"]).query)
    done = api.post(
        "/api/v1/integrations/oauth/complete",
        {"code": query["code"][0], "state": query["state"][0]},
        format="json",
    )
    assert done.status_code == 201, done.json()
    adopted = api.post(
        "/api/v1/accounting/connections", {"connection": done.json()["id"]}, format="json"
    )
    assert adopted.status_code == 201, adopted.json()
    with tenant_context(org):
        return AccountingConnection.objects.select_related("connection").get(
            pk=adopted.json()["id"]
        )


def map_all(org, w, provider: str = "xero") -> Any:
    response = w["api"].put(
        f"/api/v1/accounting/mappings/{provider}",
        {
            "accounts": [
                {"kind": kind, "key": key, "external_id": external}
                for kind, key, external in ACCOUNTS
            ],
            "taxes": [
                {"tax_rate": None, "external_id": "NONE"},
                {"tax_rate": str(w["vat"].pk), "external_id": "OUTPUT2"},
            ],
            "tracking": [],
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    return response.json()


def enabled(org, w, provider: str = "xero", **options: Any) -> AccountingConnection:
    conn = connect(org, w, provider)
    map_all(org, w, provider)
    if options:
        response = w["api"].patch(
            f"/api/v1/accounting/connections/{conn.pk}", options, format="json"
        )
        assert response.status_code == 200, response.json()
    response = w["api"].post(f"/api/v1/accounting/connections/{conn.pk}/enable", {}, format="json")
    assert response.status_code == 200, response.json()
    with tenant_context(org):
        return AccountingConnection.objects.select_related("connection").get(pk=conn.pk)
