"""G6 (FR-29-5): retention for dispatched outbox events and the global login history."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.time import now
from tutortrack.identity.models import LoginEvent
from tutortrack.privacy import retention
from tutortrack.privacy.platform_retention import purge_platform_records

pytestmark = pytest.mark.django_db


def event(org=None, *, days_ago: int, dispatched: bool = True, dead: bool = False):
    moment = now() - timedelta(days=days_ago)
    return OutboxEvent.objects.create(
        organisation=org,
        event_type="client.created",
        payload={},
        dispatched_at=moment if dispatched else None,
        dead_lettered_at=moment if dead else None,
    )


def test_dispatched_events_are_a_retention_category(org, other_org):
    old = event(org, days_ago=200)
    recent = event(org, days_ago=10)
    pending = event(org, days_ago=200, dispatched=False)
    dead = event(org, days_ago=200, dispatched=False, dead=True)
    elsewhere = event(other_org, days_ago=200)
    with tenant_context(org):
        run = retention.start_run(dry_run=False)
        assert retention.dry_run_report(run)["dispatched_events"]["due"] == 1
        assert retention.purge_batch(run, "dispatched_events") == 1
    left = set(OutboxEvent.objects.values_list("pk", flat=True))
    assert old.pk not in left
    assert {recent.pk, pending.pk, dead.pk, elsewhere.pk} <= left


def test_platform_purge_removes_old_login_history_and_platform_events(org, settings):
    settings.LOGIN_HISTORY_RETENTION_DAYS = 400
    settings.OUTBOX_RETENTION_DAYS = 90
    old_login = LoginEvent.objects.create(email="a@example.com", method="password", success=True)
    LoginEvent.objects.filter(pk=old_login.pk).update(created_at=now() - timedelta(days=401))
    LoginEvent.objects.create(email="a@example.com", method="password", success=True)
    platform_old = event(None, days_ago=100)
    platform_new = event(None, days_ago=10)
    tenant_old = event(org, days_ago=100)  # the organisation's own policy decides
    assert purge_platform_records() == {"login_events": 1, "platform_events": 1}
    assert LoginEvent.objects.count() == 1
    left = set(OutboxEvent.objects.values_list("pk", flat=True))
    assert platform_old.pk not in left
    assert {platform_new.pk, tenant_old.pk} <= left
