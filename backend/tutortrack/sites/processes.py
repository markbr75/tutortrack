"""Custom domain verification, TLS and monitoring on Temporal (E24, FR-24-2).

``CustomDomainWorkflow`` ``custom-domain:{org}:{domain}`` starts when a domain is added
(``custom_domain.added``):

1. **Verify** the DNS (TXT token or CNAME to our edge), checking with backoff (1 minute
   rising to every 6 hours) for up to 72 hours. ``check_now`` (the button) cuts a wait short.
2. **Certificate**: ask the provider (Cloudflare for SaaS / Caddy on-demand / fake) and poll
   every 30 seconds for the first 10 minutes (the AC: reachable over HTTPS within 10 minutes
   of verification), then back off, giving up after 24 hours.
3. **Monitor** daily: record the certificate's expiry after automatic renewals and flag
   failures; continues-as-new every 30 days to keep the history short.

A failure parks the workflow for 30 days waiting for ``check_now``; ``remove`` (the domain
was deleted) releases the certificate and ends it. No ``next_check_at`` column or sweeper
(CLAUDE.md 4a).
"""

from __future__ import annotations

import contextlib
import dataclasses
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from tutortrack.core.workflows import (
    WorkflowInput,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step

PROCESS = "custom-domain"
TIMEOUT = timedelta(minutes=1)
ACTIVITY_RETRY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=5))

VERIFY_DELAYS = (
    timedelta(minutes=1),
    timedelta(minutes=2),
    timedelta(minutes=5),
    timedelta(minutes=10),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(hours=1),
    timedelta(hours=2),
    timedelta(hours=4),
    timedelta(hours=6),
)
VERIFY_WINDOW = timedelta(hours=72)
CERT_DELAYS = (
    *(timedelta(seconds=30),) * 20,  # 10 minutes of 30-second polls
    timedelta(minutes=2),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(hours=1),
)
CERT_WINDOW = timedelta(hours=24)
PARK = timedelta(days=30)
MONITOR_INTERVAL = timedelta(days=1)
MONITOR_ROUNDS = 30


def domain_workflow_id(org: object, domain_id: object) -> str:
    return workflow_id(PROCESS, org, domain_id)


@dataclass(frozen=True, kw_only=True)
class DomainInput(WorkflowInput):
    domain_id: str
    hostname: str
    phase: str = "provision"  # provision | monitor (after continue-as-new)


@dataclass(frozen=True, kw_only=True)
class FailInput(WorkflowInput):
    domain_id: str
    stage: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class ReleaseInput(WorkflowInput):
    hostname: str


# --- activities ----------------------------------------------------------------------------------


def _wid() -> str:
    return str(activity.info().workflow_id or "")


@tenant_activity
def check_domain_dns(input: DomainInput) -> str:
    """``verified``, ``pending`` or ``gone`` (the domain was removed)."""
    from tutortrack.tenancy import custom_domains

    from .providers import dns, dns_resolver

    domain = custom_domains.custom_domains().filter(pk=input.domain_id).first()
    if domain is None:
        return "gone"
    if domain.verified_at is not None:
        return "verified"
    result = dns.check(dns_resolver(), domain.hostname, domain.verification_token)
    if result.verified:
        custom_domains.mark_verified(domain.pk, method=result.method, workflow_id=_wid())
        return "verified"
    custom_domains.record_check(domain.pk, detail=result.detail)
    return "pending"


def _record_cert(domain_id: str, state: object) -> str:
    from tutortrack.tenancy import custom_domains

    from .providers.certificates import FAILED, CertState

    if not isinstance(state, CertState):
        raise TypeError("expected a CertState")
    if state.status == FAILED:
        custom_domains.mark_failed(
            domain_id, stage="certificate", reason=state.detail, workflow_id=_wid()
        )
        return "failed"
    found = custom_domains.record_certificate(
        domain_id,
        status=state.status,
        expires_at=state.expires_at,
        detail=state.detail,
        workflow_id=_wid(),
    )
    return state.status if found else "gone"


@tenant_activity
def request_domain_certificate(input: DomainInput) -> str:
    """``active``, ``issuing``, ``failed`` or ``gone``."""
    from tutortrack.tenancy import custom_domains

    from .providers import certificate_provider

    if not custom_domains.custom_domains().filter(pk=input.domain_id).exists():
        return "gone"
    return _record_cert(input.domain_id, certificate_provider().request(input.hostname))


@tenant_activity
def domain_certificate_status(input: DomainInput) -> str:
    from tutortrack.tenancy import custom_domains

    from .providers import certificate_provider

    if not custom_domains.custom_domains().filter(pk=input.domain_id).exists():
        return "gone"
    return _record_cert(input.domain_id, certificate_provider().status(input.hostname))


@tenant_activity
def monitor_domain(input: DomainInput) -> str:
    """Daily: certificate still valid (renewed automatically)? ``ok``, ``failed``, ``gone``."""
    from tutortrack.tenancy import custom_domains
    from tutortrack.tenancy.models import OrganisationDomain

    from .providers import certificate_provider
    from .providers.certificates import FAILED

    domain = custom_domains.custom_domains().filter(pk=input.domain_id).first()
    if domain is None:
        return "gone"
    state = certificate_provider().status(input.hostname)
    if state.status == FAILED:
        if domain.ssl_status != OrganisationDomain.SSLStatus.FAILED:
            custom_domains.mark_failed(
                domain.pk, stage="monitoring", reason=state.detail, workflow_id=_wid()
            )
        return "failed"
    custom_domains.record_certificate(
        domain.pk,
        status=state.status,
        expires_at=state.expires_at,
        detail=state.detail,
        workflow_id=_wid(),
    )
    return "ok"


@tenant_activity
def fail_domain(input: FailInput) -> bool:
    from tutortrack.tenancy import custom_domains

    return custom_domains.mark_failed(
        input.domain_id, stage=input.stage, reason=input.reason, workflow_id=_wid()
    )


@tenant_activity
def release_domain_certificate(input: ReleaseInput) -> bool:
    from .providers import certificate_provider

    certificate_provider().release(input.hostname)
    return True


# --- workflow ------------------------------------------------------------------------------------


@register_workflow(process=PROCESS, task_queue="default", cancel_permission="sites.domain.manage")
@workflow.defn
class CustomDomainWorkflow:
    def __init__(self) -> None:
        self.nudges = 0
        self.removed = False
        self.phase = "verifying"

    @workflow.signal(name="check_now")
    def check_now(self) -> None:
        self.nudges += 1

    @workflow.signal(name="remove")
    def remove(self) -> None:
        self.removed = True

    @workflow.query
    def state(self) -> dict[str, object]:
        return {"phase": self.phase, "removed": self.removed}

    async def _wait(self, timeout: timedelta) -> bool:
        """Sleep ``timeout``; True if woken early by ``check_now`` or ``remove``."""
        seen = self.nudges
        with contextlib.suppress(TimeoutError):
            await workflow.wait_condition(
                lambda: self.nudges != seen or self.removed, timeout=timeout
            )
            return True
        return False

    async def _call(self, fn: object, arg: object) -> str:
        return str(
            await workflow.execute_activity(
                fn,  # type: ignore[arg-type]
                arg,
                start_to_close_timeout=TIMEOUT,
                retry_policy=ACTIVITY_RETRY,
            )
        )

    async def _verify(self, input: DomainInput) -> str:
        self.phase = "verifying"
        started = workflow.now()
        attempt = 0
        while True:
            if self.removed:
                return "removed"
            result = await self._call(check_domain_dns, input)
            if result in ("verified", "gone"):
                return result
            if workflow.now() - started >= VERIFY_WINDOW:
                await self._call(
                    fail_domain,
                    FailInput(
                        organisation_id=input.organisation_id,
                        domain_id=input.domain_id,
                        stage="verification",
                        reason="The DNS records were not found within 72 hours.",
                    ),
                )
                return "failed"
            await self._wait(VERIFY_DELAYS[min(attempt, len(VERIFY_DELAYS) - 1)])
            attempt += 1

    async def _certificate(self, input: DomainInput) -> str:
        self.phase = "certificate"
        await report_step(input, "certificate")
        state = await self._call(request_domain_certificate, input)
        started = workflow.now()
        attempt = 0
        while state == "issuing":
            if self.removed:
                return "removed"
            if workflow.now() - started >= CERT_WINDOW:
                await self._call(
                    fail_domain,
                    FailInput(
                        organisation_id=input.organisation_id,
                        domain_id=input.domain_id,
                        stage="certificate",
                        reason="The certificate was not issued within 24 hours.",
                    ),
                )
                return "failed"
            await self._wait(CERT_DELAYS[min(attempt, len(CERT_DELAYS) - 1)])
            attempt += 1
            state = await self._call(domain_certificate_status, input)
        return state  # active | failed | gone

    async def _finish(self, input: DomainInput, outcome: str) -> str:
        self.phase = outcome
        await self._call(
            release_domain_certificate,
            ReleaseInput(organisation_id=input.organisation_id, hostname=input.hostname),
        )
        await report_step(input, outcome, status="completed")
        return outcome

    async def _monitor(self, input: DomainInput) -> str:
        self.phase = "active"
        for _round in range(MONITOR_ROUNDS):
            await self._wait(MONITOR_INTERVAL)
            if self.removed:
                return await self._finish(input, "removed")
            if await self._call(monitor_domain, input) == "gone":
                return await self._finish(input, "removed")
        workflow.continue_as_new(dataclasses.replace(input, phase="monitor"))

    @workflow.run
    async def run(self, input: DomainInput) -> str:
        if input.phase == "monitor":
            return await self._monitor(input)
        await report_step(input, "verifying")
        while True:
            outcome = await self._verify(input)
            if outcome == "verified":
                outcome = await self._certificate(input)
                if outcome == "active":
                    break
            if outcome in ("removed", "gone"):
                return await self._finish(input, "removed")
            # Failed: wait for "check now" (or removal) for 30 days.
            self.phase = "failed"
            await report_step(input, "failed")
            if not await self._wait(PARK):
                await report_step(input, "failed", status="completed")
                return "failed"
            if self.removed:
                return await self._finish(input, "removed")
        await report_step(input, "active")
        return await self._monitor(input)
