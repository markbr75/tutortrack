"""Moving a client between payment providers (FR-11-2, ``ProviderMigrationWorkflow``):
send a setup link for the new provider → wait for the client to add a method → make it
the default for auto-pay → once nothing is being collected with the old method, cancel
it (the old mandate stays usable until then, and the invoice collection lock prevents
double collection meanwhile)."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.people.models import Client

from . import events
from .models import Payment, PaymentMethod, Provider, ProviderAccount, ProviderMigration


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def _payload(migration: ProviderMigration) -> dict[str, Any]:
    return {
        "subject_id": migration.pk,
        "client_id": str(migration.client_id),
        "to_provider": migration.to_provider,
    }


@transaction.atomic
def start_migration(client: Client, *, to_provider: str, user: Any = None) -> ProviderMigration:
    from . import services

    if to_provider not in (Provider.STRIPE, Provider.GOCARDLESS):
        raise _invalid("to_provider", _("Clients can be moved to Stripe or GoCardless."))
    services.active_account_for(client.branch_id, to_provider)
    if ProviderMigration.objects.filter(
        client=client,
        status__in=[ProviderMigration.Status.WAITING, ProviderMigration.Status.SWITCHED],
    ).exists():
        raise BusinessRuleViolation(_("This client is already being moved."))
    current = services.default_method(client)
    if current is not None and current.account.provider == to_provider:
        raise _invalid("to_provider", _("The client already pays with that provider."))
    migration = ProviderMigration.objects.create(
        client=client, from_method=current, to_provider=to_provider, created_by=user
    )
    audit.record_create(migration)
    from tutortrack.core.workflows import start

    from .processes import MigrationInput, ProviderMigrationWorkflow, migration_workflow_id

    migration.workflow_id = migration_workflow_id(migration.organisation_id, migration.pk)
    migration.save(update_fields=["workflow_id", "updated_at"])
    start(
        ProviderMigrationWorkflow,
        MigrationInput(
            organisation_id=str(migration.organisation_id), migration_id=str(migration.pk)
        ),
        id=migration.workflow_id,
        subject=("client", str(client.pk)),
        branch_id=client.branch_id,
    )
    publish(events.ProviderMigrationStarted(**_payload(migration)), branch_id=client.branch_id)
    return migration


@transaction.atomic
def cancel_migration(migration: ProviderMigration, *, user: Any = None) -> ProviderMigration:
    if migration.status != ProviderMigration.Status.WAITING:
        raise BusinessRuleViolation(
            _("Only migrations still waiting for the client can be cancelled.")
        )
    if migration.workflow_id:
        from tutortrack.core.workflows import signal

        signal(migration.workflow_id, "cancel")
    finish(migration.pk, ProviderMigration.Status.CANCELLED)
    migration.refresh_from_db()
    return migration


def on_method_added(client_id: Any, method_id: Any, provider: str) -> bool:
    """``payment_method.added``: tell a waiting migration to this provider."""
    migration = ProviderMigration.objects.filter(
        client_id=client_id, to_provider=provider, status=ProviderMigration.Status.WAITING
    ).first()
    if migration is None or not migration.workflow_id:
        return False
    from tutortrack.core.workflows import signal_now

    return signal_now(migration.workflow_id, "method_added", str(method_id))


# --- activities -------------------------------------------------------------------------------


def send_link(migration_id: Any, *, key: str) -> bool:
    from tutortrack.comms.services import notify

    from . import services

    migration = ProviderMigration.objects.select_related("client").filter(pk=migration_id).first()
    if migration is None or migration.status != ProviderMigration.Status.WAITING:
        return False
    url = services.create_setup_link(migration.client, provider=migration.to_provider)
    label = str(Provider(migration.to_provider).label)
    notify("payment_setup_link", (migration.client, url, label), key=key, immediate=True)
    return True


@transaction.atomic
def switch_default(migration_id: Any, method_id: str) -> bool:
    from . import services

    migration = ProviderMigration.objects.select_for_update().filter(pk=migration_id).first()
    method = (
        PaymentMethod.objects.select_related("account")
        .filter(pk=method_id, status=PaymentMethod.Status.ACTIVE)
        .first()
    )
    if migration is None or migration.status != ProviderMigration.Status.WAITING:
        return False
    if method is None or method.client_id != migration.client_id:
        return False
    services.set_default_method(method)
    with audit.track(migration, action="switch"):
        migration.new_method = method
        migration.status = ProviderMigration.Status.SWITCHED
        migration.save()
    publish(events.ProviderMigrationSwitched(**_payload(migration)))
    return True


def in_flight(migration_id: Any) -> int:
    """Collections still running (or debits pending) with the old method."""
    from tutortrack.billing.models import Invoice

    from . import services

    migration = ProviderMigration.objects.filter(pk=migration_id).first()
    if migration is None or migration.from_method_id is None:
        return 0
    pending = Payment.objects.filter(
        payment_method_id=migration.from_method_id, status=Payment.Status.PENDING
    ).count()
    running = sum(
        1
        for invoice in Invoice.objects.filter(
            client_id=migration.client_id, status__in=Invoice.OPEN
        )
        if services.collection_running(invoice)
    )
    return pending + running


@transaction.atomic
def finish(migration_id: Any, status: str) -> str:
    """Close the migration; when completed, cancel the old mandate or card."""
    from . import services

    migration = ProviderMigration.objects.select_for_update().filter(pk=migration_id).first()
    if migration is None or migration.status in {
        ProviderMigration.Status.COMPLETED,
        ProviderMigration.Status.CANCELLED,
        ProviderMigration.Status.EXPIRED,
    }:
        return migration.status if migration else "missing"
    if status == ProviderMigration.Status.COMPLETED and migration.from_method_id:
        old = PaymentMethod.objects.select_related("account", "client").get(
            pk=migration.from_method_id
        )
        if (
            old.status == PaymentMethod.Status.ACTIVE
            and old.account.status != ProviderAccount.Status.DISCONNECTED
        ):
            services.remove_method(old)
    with audit.track(migration, action=status):
        migration.status = status
        migration.completed_at = now()
        migration.save()
    publish(events.ProviderMigrationFinished(**_payload(migration), status=status))
    return status
