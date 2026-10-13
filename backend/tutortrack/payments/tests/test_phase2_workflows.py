"""E11 Phase 2 workflows: ProviderMigrationWorkflow (FR-11-2) and BankFeedSyncWorkflow
(T13), with replayed histories."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.workflows import start_now
from tutortrack.payments import provider_migration, services
from tutortrack.payments.bank_feeds import set_transactions
from tutortrack.payments.models import (
    AccountRoute,
    BankTransaction,
    PaymentMethod,
    ProviderAccount,
    ProviderMigration,
)
from tutortrack.payments.processes import (
    BankFeedInput,
    BankFeedSyncWorkflow,
    ProviderMigrationWorkflow,
)
from tutortrack.payments.providers import get_provider
from tutortrack.payments.providers.base import MethodDetails
from tutortrack.people.tests.factories import ClientFactory, ContactFactory

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


@pytest.fixture(autouse=True)
def fresh_providers():
    get_provider.cache_clear()
    yield
    get_provider.cache_clear()


@pytest.fixture
def setup(org):
    with tenant_context(org):
        accounts = {}
        for provider, ref in (("stripe", "acct_m1"), ("gocardless", "OR_m1")):
            accounts[provider] = ProviderAccount.objects.create(
                provider=provider, account_ref=ref, status="active", charges_enabled=True
            )
            AccountRoute.objects.create(provider=provider, account_ref=ref, organisation_id=org.pk)
        client = ClientFactory(organisation=org, display_name="The Patels")
        contact = ContactFactory(organisation=org, client=client, email="priya@example.com")
        client.billing_contact = contact
        client.save()
        with transaction.atomic():
            old = services.save_method(
                client, accounts["stripe"], MethodDetails("pm_card_visa", "card", "visa", "4242")
            )
    return {"client": client, "accounts": accounts, "old": old}


def start(org, setup):
    with tenant_context(org), transaction.atomic():
        return provider_migration.start_migration(setup["client"], to_provider="gocardless")


def add_mandate(org, setup):
    with tenant_context(org), transaction.atomic():
        services.save_method(
            setup["client"],
            setup["accounts"]["gocardless"],
            MethodDetails("MD_m1", "bacs_debit", "", "1234", mandate_status="active"),
            make_default=False,
        )
    dispatch_batch()  # payment_method.added → signal "method_added"


def test_migration_switches_then_cancels_the_old_method(org, setup, temporal_env):
    migration = start(org, setup)
    add_mandate(org, setup)
    assert temporal_env.result(migration.workflow_id) == "completed"
    with tenant_context(org):
        migration.refresh_from_db()
        old = PaymentMethod.objects.get(pk=setup["old"].pk)
        new = PaymentMethod.objects.get(provider_ref="MD_m1")
    assert (migration.status, migration.new_method_id) == ("completed", new.pk)
    assert (old.status, new.is_default) == ("removed", True)


def test_migration_expires_without_a_new_method(org, setup, temporal_env):
    migration = start(org, setup)
    assert temporal_env.result(migration.workflow_id) == "expired"
    with tenant_context(org):
        assert ProviderMigration.objects.get().status == "expired"
        assert PaymentMethod.objects.get(pk=setup["old"].pk).status == "active"


def test_migration_can_be_cancelled_while_waiting(org, setup, temporal_env):
    migration = start(org, setup)
    with tenant_context(org):
        provider_migration.cancel_migration(migration)
    assert temporal_env.result(migration.workflow_id) == "cancelled"


def test_bank_feed_sync_workflow(org, temporal_env):
    from tutortrack.identity.tests.factories import MembershipFactory
    from tutortrack.integrations import services as integrations

    set_transactions("acc-w", [{
        "transactionId": "w-1", "bookingDate": "2026-10-05",
        "transactionAmount": {"amount": "12.00", "currency": "GBP"},
        "remittanceInformationUnstructured": "X",
    }])  # fmt: skip
    with tenant_context(org):
        user = MembershipFactory(organisation=org, role="owner").user
        connection = integrations.connect_with_credentials(
            user, provider="open_banking", level="organisation", username="acc-w",
            api_key="id:key",
        )  # fmt: skip
    wid = f"bank-feed:{org.pk}:{connection.pk}:test"
    start_now(
        BankFeedSyncWorkflow,
        BankFeedInput(organisation_id=str(org.pk), connection_id=str(connection.pk)),
        id=wid,
    )
    assert temporal_env.result(wid) == 1
    with tenant_context(org):
        assert BankTransaction.objects.get().external_id == "ob:w-1"


def test_migration_histories_replay():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("ProviderMigrationWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[ProviderMigrationWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )


def test_record_migration_history_if_requested(org, setup, temporal_env):
    if not os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        pytest.skip("set RECORD_WORKFLOW_HISTORIES=1 to (re)record")
    migration = start(org, setup)
    add_mandate(org, setup)
    temporal_env.result(migration.workflow_id)
    (HISTORIES / "ProviderMigrationWorkflow-completed.json").write_text(
        temporal_env.history_json(migration.workflow_id)
    )
