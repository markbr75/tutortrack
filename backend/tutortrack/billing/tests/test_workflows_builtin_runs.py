"""E33-T04: billing's built-in workflows running on Temporal: payment chasing from an
issued invoice to its last reminder, stopping when it is paid, and payment request
reminders."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tutortrack.automations import services as automations
from tutortrack.automations.models import AutomationRun
from tutortrack.billing import dunning, services
from tutortrack.billing.models import Charge
from tutortrack.billing.tests.test_billing import events_of, issued_invoice
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.money import Money

pytestmark = pytest.mark.django_db(transaction=True)


def run_for(org, key: str, subject_id) -> AutomationRun:
    with tenant_context(org):
        return AutomationRun.objects.select_related("automation").get(
            automation__builtin_key=key, subject_id=str(subject_id)
        )


def test_payment_chasing_reminds_applies_the_late_fee_and_stops_when_paid(
    org, family, temporal_env
):
    with tenant_context(org):
        automations.install_builtins()
        dunning.save_rule(None, kind="fixed", amount=Decimal("5"), days_overdue=14)
    dispatch_batch()
    invoice = issued_invoice(org, family)
    dispatch_batch()  # invoice.issued starts the run, which waits for 3 days before the due date
    run = run_for(org, "payment_chasing", invoice.pk)
    assert temporal_env.result(run.workflow_id) == "completed"
    # Six reminders (the activities see the real clock, so their wording isn't checked here).
    assert len(events_of(org, "invoice.reminder")) == 6
    assert len(events_of(org, "late_fee.applied")) == 1
    with tenant_context(org):
        assert Charge.objects.filter(kind=Charge.Kind.LATE_FEE).count() == 1

    paid = issued_invoice(org, family, count=1)
    with tenant_context(org):
        services.allocate_payment(paid, paid.balance_due)
    dispatch_batch()  # issued, then paid: the run stops at its first wait
    stopped = run_for(org, "payment_chasing", paid.pk)
    assert temporal_env.result(stopped.workflow_id) == "stopped"
    with tenant_context(org):
        stopped.refresh_from_db()
        assert stopped.stop_reason == "invoice.paid"
        assert not stopped.steps.filter(step_type="action").exists()


def test_payment_request_reminders_come_3_and_7_days_after(org, family, temporal_env):
    with tenant_context(org):
        automations.install_builtins()
        request = services.create_payment_request(
            client=family["client"], amount=Money(Decimal("50"), "GBP")
        )
    dispatch_batch()
    run = run_for(org, "payment_request_reminders", request.pk)
    assert temporal_env.result(run.workflow_id) == "completed"
    assert len(events_of(org, "payment_request.sent")) == 2
