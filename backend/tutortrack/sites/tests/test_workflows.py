"""E24 custom-domain process on Temporal: CustomDomainWorkflow (verify with backoff and the
check-now signal, certificate polling with retries, monitoring, removal, failure after 72
hours) and replay of recorded histories."""

from __future__ import annotations

import json
import os
import time as clock
from collections.abc import Callable
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent
from tutortrack.sites.processes import CustomDomainWorkflow, domain_workflow_id
from tutortrack.sites.providers.certificates import FakeCertificates
from tutortrack.sites.providers.dns import FakeDnsResolver
from tutortrack.tenancy import custom_domains
from tutortrack.tenancy.models import OrganisationDomain

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


@pytest.fixture(autouse=True)
def _fakes():
    FakeDnsResolver.reset()
    FakeCertificates.reset()
    yield
    FakeDnsResolver.reset()
    FakeCertificates.reset()


def wait_for(check: Callable[[], bool], seconds: float = 20) -> None:
    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        if check():
            return
        clock.sleep(0.1)
    raise AssertionError("timed out waiting for the workflow")


def record(temporal_env, workflow_id: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(workflow_id))


def publish_txt(domain: OrganisationDomain) -> None:
    FakeDnsResolver.records[(f"_tutortrack-challenge.{domain.hostname}", "TXT")] = [
        domain.verification_token
    ]


def add(org, hostname: str) -> OrganisationDomain:
    with tenant_context(org), transaction.atomic():
        domain = custom_domains.add_custom_domain(hostname=hostname, purpose="app")
    return domain


def start(org, domain: OrganisationDomain) -> str:
    dispatch_batch()  # custom_domain.added -> CustomDomainWorkflow
    return domain_workflow_id(org.pk, domain.pk)


def fresh(domain: OrganisationDomain) -> OrganisationDomain:
    return OrganisationDomain.objects.get(pk=domain.pk)


def remove(org, domain: OrganisationDomain) -> None:
    with tenant_context(org), transaction.atomic():
        custom_domains.remove_custom_domain(fresh(domain))
    dispatch_batch()  # custom_domain.removed -> signal "remove"


def test_verified_domain_gets_a_certificate_then_removal_releases_it(org, temporal_env):
    """AC: after DNS verification the domain is live over HTTPS (well within 10 minutes)."""
    domain = add(org, "portal.example.com")
    publish_txt(domain)
    wid = start(org, domain)
    wait_for(lambda: fresh(domain).ssl_status == "active")
    live = fresh(domain)
    assert live.verification_status == "verified"
    assert live.cert_expires_at is not None
    assert org.base_url == "https://portal.example.com"
    types = set(OutboxEvent.objects.values_list("event_type", flat=True))
    assert {"custom_domain.verified", "custom_domain.activated"} <= types
    remove(org, domain)
    assert temporal_env.result(wid) == "removed"
    assert "portal.example.com" in FakeCertificates.released
    record(temporal_env, wid, "CustomDomainWorkflow-removed")


def test_check_now_signal_cuts_the_dns_wait_short(org, temporal_env):
    domain = add(org, "www.example.com")
    wid = start(org, domain)
    wait_for(lambda: fresh(domain).last_checked_at is not None)  # first check: not found
    assert fresh(domain).verification_status == "pending"
    publish_txt(domain)
    check_now(org, domain)
    # The 1-minute backoff isn't skipped while we poll; only the signal can wake it.
    wait_for(lambda: fresh(domain).ssl_status == "active", 15)
    remove(org, domain)
    assert temporal_env.result(wid) == "removed"
    record(temporal_env, wid, "CustomDomainWorkflow-check-now")


def check_now(org, domain: OrganisationDomain) -> None:
    with tenant_context(org), transaction.atomic():
        custom_domains.request_check(fresh(domain))
    dispatch_batch()  # custom_domain.check_requested -> signal "check_now"


def test_certificate_polls_and_retries_through_provider_errors(org, temporal_env):
    host = "learn.example.com"
    FakeCertificates.script[host] = ["issuing", "error", "issuing", "active"]
    domain = add(org, host)
    publish_txt(domain)
    wid = start(org, domain)
    wait_for(lambda: fresh(domain).ssl_status == "issuing")
    # 30-second polls only skip while awaiting the result; "check now" wakes the poll.
    check_now(org, domain)
    # The provider error fails the activity; Temporal retries it, which then sees "issuing".
    wait_for(lambda: FakeCertificates.script[host] == ["active"], 30)
    check_now(org, domain)
    wait_for(lambda: fresh(domain).ssl_status == "active")
    remove(org, domain)
    assert temporal_env.result(wid) == "removed"
    record(temporal_env, wid, "CustomDomainWorkflow-certificate-retry")


def test_dns_never_found_fails_after_72_hours(org, temporal_env):
    domain = add(org, "never.example.com")
    wid = start(org, domain)
    assert temporal_env.result(wid) == "failed"
    failed = fresh(domain)
    assert failed.verification_status == "failed"
    assert "72 hours" in failed.status_detail
    event = OutboxEvent.objects.get(event_type="custom_domain.failed")
    assert event.payload["data"]["stage"] == "verification"
    assert event.payload["actor"]["type"] == "workflow"
    record(temporal_env, wid, "CustomDomainWorkflow-failed")


def test_histories_replay():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("CustomDomainWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[CustomDomainWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
