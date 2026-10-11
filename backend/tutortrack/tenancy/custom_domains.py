"""Custom domain writes (E24 FR-24-2).

``OrganisationDomain`` is a platform routing table owned by tenancy, so every write to a
custom-domain row happens here. ``CustomDomainWorkflow`` (sites app) calls these from its
activities with the workflow's verdicts: DNS verified, certificate issued, renewal, failure.
Each mutation is audited and publishes its event inside the transaction.
"""

from __future__ import annotations

import ipaddress
import re
import secrets
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit, entitlements
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict
from tutortrack.core.time import now

from . import events
from .models import OrganisationDomain

MAX_CUSTOM_DOMAINS = 5
CHALLENGE_PREFIX = "_tutortrack-challenge"
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def _invalid(message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {"hostname": [message]}})


def platform_suffixes() -> tuple[str, ...]:
    """Hostnames under these belong to the platform and can't be claimed."""
    configured = getattr(settings, "CUSTOM_DOMAINS", {})
    values = {
        settings.TENANT_BASE_DOMAIN,
        configured.get("SITE_BASE_DOMAIN", ""),
        configured.get("CNAME_TARGET", ""),
        "tutortrack.app",
        "tutortrack.site",
    }
    return tuple(sorted(v.lower() for v in values if v))


def normalise_hostname(raw: str) -> str:
    """Lower-case, IDNA-encoded, no scheme/port/path; at least two labels; not an IP and not
    a platform hostname."""
    host = (raw or "").strip().lower()
    host = re.sub(r"^[a-z]+://", "", host).split("/")[0].split(":")[0].rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise _invalid(_("Enter a valid domain name, like portal.example.com.")) from exc
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise _invalid(_("Use a domain name, not an IP address."))
    labels = host.split(".")
    if len(host) > 253 or len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        raise _invalid(_("Enter a valid domain name, like portal.example.com."))
    if labels[-1].isdigit():
        raise _invalid(_("Enter a valid domain name, like portal.example.com."))
    for suffix in platform_suffixes():
        if host == suffix or host.endswith(f".{suffix}"):
            raise _invalid(_("That address belongs to TutorTrack; use your own domain."))
    return host


def challenge_name(hostname: str) -> str:
    return f"{CHALLENGE_PREFIX}.{hostname}"


def custom_domains() -> Any:
    return OrganisationDomain.objects.filter(
        organisation_id=require_organisation_id(), type=OrganisationDomain.Type.CUSTOM
    )


@transaction.atomic
def add_custom_domain(*, hostname: str, purpose: str) -> OrganisationDomain:
    """Claim ``hostname`` for the current organisation; verification starts on commit."""
    entitlements.require("custom_domain")
    host = normalise_hostname(hostname)
    if purpose not in OrganisationDomain.Purpose.values:
        raise BusinessRuleViolation(_("Choose what the domain is for."))
    if custom_domains().count() >= MAX_CUSTOM_DOMAINS:
        raise BusinessRuleViolation(
            _("You can add up to %(n)s custom domains.") % {"n": MAX_CUSTOM_DOMAINS}
        )
    if OrganisationDomain.objects.filter(hostname=host).exists():
        raise Conflict(_("That domain is already connected to an organisation."))
    domain = OrganisationDomain.objects.create(
        organisation_id=require_organisation_id(),
        hostname=host,
        type=OrganisationDomain.Type.CUSTOM,
        purpose=purpose,
        verification_token=f"tt-verify={secrets.token_urlsafe(24)}",
    )
    audit.record(domain, "create", {"hostname": [None, host], "purpose": [None, purpose]})
    publish(events.CustomDomainAdded(subject_id=domain.pk, hostname=host, purpose=purpose))
    return domain


@transaction.atomic
def request_check(domain: OrganisationDomain) -> OrganisationDomain:
    """The "check now" button. A failed verification goes back to waiting for DNS: the
    workflow parks after a failure and resumes on this signal (for 30 days)."""
    if domain.verification_status == OrganisationDomain.VerificationStatus.FAILED:
        domain.verification_status = OrganisationDomain.VerificationStatus.PENDING
        domain.status_detail = ""
        domain.save(update_fields=["verification_status", "status_detail", "updated_at"])
    publish(events.CustomDomainCheckRequested(subject_id=domain.pk, hostname=domain.hostname))
    return domain


@transaction.atomic
def remove_custom_domain(domain: OrganisationDomain) -> None:
    host = domain.hostname
    audit.record(domain, "delete", {"hostname": [host, None]})
    publish(events.CustomDomainRemoved(subject_id=domain.pk, hostname=host))
    domain.delete()


def _get(domain_id: Any) -> OrganisationDomain | None:
    return (
        OrganisationDomain.objects.select_for_update()
        .filter(pk=domain_id, organisation_id=require_organisation_id())
        .first()
    )


@transaction.atomic
def record_check(domain_id: Any, *, detail: str = "") -> OrganisationDomain | None:
    """A verification attempt that didn't find the record yet."""
    domain = _get(domain_id)
    if domain is None:
        return None
    domain.last_checked_at = now()
    domain.status_detail = detail[:500]
    domain.save(update_fields=["last_checked_at", "status_detail", "updated_at"])
    return domain


@transaction.atomic
def mark_verified(domain_id: Any, *, method: str, workflow_id: str = "") -> bool:
    domain = _get(domain_id)
    if domain is None:
        return False
    if domain.verified_at is None:
        with audit.track(domain, "verify"):
            domain.verified_at = now()
            domain.verification_status = OrganisationDomain.VerificationStatus.VERIFIED
            domain.ssl_status = OrganisationDomain.SSLStatus.ISSUING
            domain.last_checked_at = now()
            domain.status_detail = ""
            domain.save()
        publish(
            events.CustomDomainVerified(
                subject_id=domain.pk, hostname=domain.hostname, method=method
            ),
            actor={"type": "workflow", "id": workflow_id} if workflow_id else None,
            dedupe_key=f"custom-domain-verified:{domain.pk}",
        )
    return True


@transaction.atomic
def record_certificate(
    domain_id: Any,
    *,
    status: str,
    expires_at: datetime | None = None,
    detail: str = "",
    workflow_id: str = "",
) -> bool:
    """Store the certificate state; the first ``active`` publishes ``custom_domain.activated``."""
    domain = _get(domain_id)
    if domain is None:
        return False
    first_active = (
        status == OrganisationDomain.SSLStatus.ACTIVE
        and domain.ssl_status != OrganisationDomain.SSLStatus.ACTIVE
    )
    with audit.track(domain, "certificate"):
        domain.ssl_status = status
        if expires_at is not None:
            domain.cert_expires_at = expires_at
        domain.last_checked_at = now()
        domain.status_detail = detail[:500]
        domain.save()
    if first_active:
        publish(
            events.CustomDomainActivated(
                subject_id=domain.pk,
                hostname=domain.hostname,
                purpose=domain.purpose,
                cert_expires_at=expires_at.isoformat() if expires_at else None,
            ),
            actor={"type": "workflow", "id": workflow_id} if workflow_id else None,
        )
    return True


@transaction.atomic
def mark_failed(domain_id: Any, *, stage: str, reason: str, workflow_id: str = "") -> bool:
    domain = _get(domain_id)
    if domain is None:
        return False
    with audit.track(domain, "fail"):
        if stage == "verification":
            domain.verification_status = OrganisationDomain.VerificationStatus.FAILED
        else:
            domain.ssl_status = OrganisationDomain.SSLStatus.FAILED
        domain.status_detail = reason[:500]
        domain.last_checked_at = now()
        domain.save()
    publish(
        events.CustomDomainFailed(
            subject_id=domain.pk, hostname=domain.hostname, stage=stage, reason=reason[:500]
        ),
        actor={"type": "workflow", "id": workflow_id} if workflow_id else None,
    )
    return True
