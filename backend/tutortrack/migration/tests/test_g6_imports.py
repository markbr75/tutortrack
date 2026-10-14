"""G6 (FR-28-3/5): TutorCruncher agents, reviews, proformas and ad hoc charges, and
Teachworks wage tiers as E06 pay tiers."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction

from tutortrack.billing.models import Charge, PaymentRequest
from tutortrack.catalogue.models import PayTier, ServiceTierRate, TutorPayTierAssignment
from tutortrack.core.time import now
from tutortrack.growth.models import Affiliate, AffiliateReferral, CommissionRule, Review
from tutortrack.migration import services
from tutortrack.migration.connectors.base import source_for
from tutortrack.migration.models import ImportBatch
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, TutorProfileFactory

from .conftest import roll_back, run_import
from .test_connectors import KEY, finish_step_imports

pytestmark = pytest.mark.django_db
DONE = ImportBatch.Status.COMPLETED


def test_tutorcruncher_maps_agents_reviews_proformas_and_charges(tenant):
    source = source_for("tutorcruncher")
    cutover = now().date()
    agents = list(source.fetch(KEY, "affiliates", cutover=cutover))
    assert agents[0]["email"] == "sam.agent@example.com"
    assert agents[0]["commission_percent"] == "10.00"
    assert agents[0]["client_external_ids"] == "12"
    reviews = list(source.fetch(KEY, "reviews", cutover=cutover))
    assert (reviews[0]["rating"], reviews[0]["published"]) == ("5", "yes")
    requests = list(source.fetch(KEY, "payment_requests", cutover=cutover))
    assert {r["status"] for r in requests} == {"unpaid", "paid"}
    charges = list(source.fetch(KEY, "charges", cutover=cutover))
    assert [c["description"] for c in charges] == ["Exam entry fee"]  # older one: invoiced


@pytest.fixture
def family(tenant):
    client = ClientFactory(organisation=tenant, display_name="The Smiths")
    ContactFactory(organisation=tenant, client=client, email="jane@example.com")
    return client


def test_affiliates_with_commission_and_introduced_clients(tenant, family):
    batch = run_import(
        "affiliates",
        [{"Name": "PTA", "Email": "pta@example.com", "Commission": "12.5", "Clients": ""}],
    )
    assert batch.status == DONE, batch.stats
    affiliate = Affiliate.objects.get(email="pta@example.com")
    assert CommissionRule.objects.get(affiliate=affiliate).percent == Decimal("12.50")
    roll_back(batch)
    assert not Affiliate.objects.filter(email="pta@example.com").exists()


def test_affiliate_clients_are_attributed(tenant, family):
    run_import("clients", [{"Client ID": "F1", "First name": "Jane", "Email": "j2@example.com"}])
    batch = run_import(
        "affiliates",
        [{"Agent ID": "A1", "Name": "PTA", "Email": "pta@example.com", "Clients": "F1"}],
    )
    assert batch.status == DONE, batch.stats
    referral = AffiliateReferral.objects.get()
    assert referral.client.contacts.filter(email="j2@example.com").exists()


def test_reviews_are_imported_and_published_ones_approved(tenant, family):
    tutor = TutorProfileFactory(organisation=tenant, email="alex@example.com")
    batch = run_import(
        "reviews",
        [
            {"Client email": "jane@example.com", "Tutor email": "alex@example.com",
             "Rating": "5", "Review": "Brilliant", "Published": "yes"},
            {"Client email": "jane@example.com", "Rating": "3", "Review": "OK"},
        ],
    )  # fmt: skip
    assert batch.status == DONE, batch.stats
    published = Review.objects.get(rating=5)
    assert (published.source, published.status, published.tutor_id) == (
        "import",
        "approved",
        tutor.pk,
    )
    assert Review.objects.get(rating=3).status == "pending"
    roll_back(batch)
    assert Review.objects.filter(rating=3).count() == 0


def test_charges_and_unpaid_proformas(tenant, family):
    day = (now() + timedelta(days=2)).date().isoformat()
    charges = run_import(
        "charges",
        [
            {
                "Client email": "jane@example.com",
                "Description": "Exam fee",
                "Amount": "45",
                "Date": day,
            }
        ],
    )
    assert charges.status == DONE, charges.stats
    charge = Charge.objects.get(description="Exam fee")
    assert (charge.status, charge.gross.amount) == ("uninvoiced", Decimal("45.00"))
    requests = run_import(
        "payment_requests",
        [
            {"Client email": "jane@example.com", "Amount": "120", "Status": "unpaid"},
            {"Client email": "jane@example.com", "Amount": "60", "Status": "paid"},
        ],
    )
    assert requests.status == DONE, requests.stats
    assert list(PaymentRequest.objects.values_list("amount_amount", flat=True)) == [
        Decimal("120.00")
    ]
    roll_back(requests)
    assert PaymentRequest.objects.get().status == "cancelled"
    roll_back(charges)
    charge.refresh_from_db()
    assert charge.status == "void"


def test_teachworks_wage_tiers_become_pay_tiers(tenant, user, s3):
    with transaction.atomic():
        project = services.create_project(
            user=user, name="", source="teachworks", cutover_date=now().date(), api_key="tw-key"
        )
    services.start_step(project.pk, "people")
    finish_step_imports(project, "people")
    tier = PayTier.objects.get(name="Senior")
    assignment = TutorPayTierAssignment.objects.get()
    assert (assignment.tier_id, assignment.effective_from) == (tier.pk, project.cutover_date)
    services.complete_step(project, "people")
    services.start_step(project.pk, "services")
    finish_step_imports(project, "services")
    rate = ServiceTierRate.objects.get(tier=tier)
    assert rate.pay_rate.amount == Decimal("30.00")
